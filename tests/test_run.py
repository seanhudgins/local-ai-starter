"""Tests for evals/run.py with a fake asker and a fake streaming Ollama (no models needed)."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("evalrun", Path(__file__).parent.parent / "evals" / "run.py")
er = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(er)

ITEMS = er.load_items()
BY_ID = {i["id"]: i for i in ITEMS}


class FakeAsker:
    """Stands in for ask(): answers each item with its reference answer, or a fixed reply."""

    def __init__(self, reply=None, fail_on=None):
        self.reply, self.fail_on, self.calls = reply, fail_on, []

    def __call__(self, model, item, url):
        self.calls.append((model, item["id"]))
        if self.fail_on and item["id"] == self.fail_on:
            return "", "TimeoutError: model too slow", 1.0, 0
        text = self.reply if self.reply is not None else er.checks.reference_reply(item)
        return text, "", 0.1, 42


PLENTY = lambda: 90  # noqa: E731  (free memory %)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(er.modelcheck, "call", lambda url, path, body=None, timeout=600: {"version": "0.40.14"})
    monkeypatch.setattr(er.modelcheck, "identity", lambda url, model: {"model_digest": "abc123", "ollama_version": ""})
    return er.connect(tmp_path / "results.db")


def test_prompt_has_instructions_schema_and_input():
    item = BY_ID["summary-001"]
    msgs = er.build_prompt(item)
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    assert user.startswith(item["instructions"])
    assert "JSON schema:" in user and '"disposition"' in user
    assert user.endswith(item["input"])


def test_prompt_without_schema_has_no_schema_block():
    assert "JSON schema" not in er.build_prompt(BY_ID["intent-001"])[1]["content"]


def test_item_filter_by_prefix():
    assert {i["id"] for i in er.load_items(only=["redact-", "intent-001"])} == {
        "redact-001",
        "redact-002",
        "redact-003",
        "redact-004",
        "intent-001",
    }


def test_reference_answers_score_100_percent(con):
    run_id = er.run(["m:1"], ITEMS, con, asker=FakeAsker(), memory=PLENTY)
    row = con.execute(
        "SELECT SUM(rules_passed), SUM(rules_total), COUNT(*) FROM results WHERE run_id=?", (run_id,)
    ).fetchone()
    assert row[0] == row[1] and row[2] == len(ITEMS)
    stamp = con.execute("SELECT DISTINCT model_digest FROM results").fetchone()[0]
    assert stamp == "abc123"


def test_a_failing_call_is_recorded_and_the_run_continues(con):
    run_id = er.run(["m:1"], ITEMS[:3], con, asker=FakeAsker(fail_on=ITEMS[1]["id"]), memory=PLENTY)
    rows = {r["item_id"]: r for r in con.execute("SELECT * FROM results WHERE run_id=?", (run_id,))}
    assert len(rows) == 3
    assert "TimeoutError" in rows[ITEMS[1]["id"]]["error"]
    assert rows[ITEMS[0]["id"]]["error"] == ""


def test_wrong_answers_lose_points(con):
    run_id = er.run(["m:1"], ITEMS, con, asker=FakeAsker(reply="other"), memory=PLENTY)
    passed, total = con.execute(
        "SELECT SUM(rules_passed), SUM(rules_total) FROM results WHERE run_id=?", (run_id,)
    ).fetchone()
    assert passed < total / 4


def test_export_then_import_round_trip(con, tmp_path):
    run_id = er.run(["m:1"], ITEMS, con, asker=FakeAsker(), memory=PLENTY)
    path = er.export(con, run_id, BY_ID, tmp_path)
    packets = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(packets) == sum(1 for i in ITEMS if i["grader"])  # judgment items only
    assert all({"rubric", "answer", "input", "item_id", "model"} <= set(p) for p in packets)
    graded = tmp_path / "graded.jsonl"
    graded.write_text("".join(json.dumps({**p, "score": 4, "reason": "ok"}) + "\n" for p in packets))
    assert er.import_grades(con, graded) == len(packets)
    assert er.export(con, run_id, BY_ID, tmp_path).read_text() == ""  # nothing left to judge
    assert "judge: chat" in er.report(con, run_id)


def test_import_rejects_out_of_range_scores(con, tmp_path):
    run_id = er.run(["m:1"], ITEMS[:5], con, asker=FakeAsker(), memory=PLENTY)
    p = er.to_judge(con, run_id, BY_ID)[0]
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({**p, "score": 9}) + "\n")
    with pytest.raises(ValueError):
        er.import_grades(con, bad)


def test_report_compares_models(con):
    run_id = er.run(["good:1"], ITEMS, con, asker=FakeAsker(), memory=PLENTY)
    con.execute("UPDATE runs SET run_id=run_id")  # same run gets a second model below
    for item in ITEMS:
        con.execute(
            "INSERT INTO results SELECT run_id, item_id, 'bad:1', model_digest, task_type, industry, 'x', '', "
            "1.0, 1, 0, rules_total, '[]', NULL, NULL, NULL FROM results WHERE run_id=? AND item_id=?",
            (run_id, item["id"]),
        )
    text = er.report(con, run_id)
    assert text.index("`good:1`") < text.index("`bad:1`")  # sorted best first
    assert "| `good:1` | 27 | 27 | 100.0 |" in text


# ---------- safety rails ----------


def test_low_memory_stops_the_run_cleanly_and_unloads(con, monkeypatch):
    unloaded = []
    monkeypatch.setattr(er, "unload", lambda model, url=None: unloaded.append(model))
    monkeypatch.setattr(er.time, "sleep", lambda s: None)
    readings = iter([90, 90, 10, 10] + [90] * 100)  # low before item 2, still low after a reload
    run_id = er.run(["m:1"], ITEMS[:5], con, asker=FakeAsker(), memory=lambda: next(readings))
    done = con.execute("SELECT COUNT(*) FROM results WHERE run_id=?", (run_id,)).fetchone()[0]
    assert done == 1  # stopped before item 2; item 1 kept
    assert unloaded == ["m:1", "m:1"]  # tried a reload first, then unloaded on the way out


def test_every_model_is_unloaded_after_its_turn(con, monkeypatch):
    unloaded = []
    monkeypatch.setattr(er, "unload", lambda model, url=None: unloaded.append(model))
    er.run(["a:1", "b:1"], ITEMS[:2], con, asker=FakeAsker(), memory=PLENTY)
    assert unloaded == ["a:1", "b:1"]


class FakeStream:
    """A fake Ollama /api/chat that streams NDJSON chunks."""

    def __init__(self, chunks, delay=0.0):
        fake = self
        self.chunks, self.delay, self.bodies = chunks, delay, []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                fake.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                try:
                    for c in fake.chunks:
                        self.wfile.write((json.dumps(c) + "\n").encode())
                        self.wfile.flush()
                        if fake.delay:
                            import time

                            time.sleep(fake.delay)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client stopped reading: that's the point

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def tok(text):
    return {"message": {"content": text}, "done": False}


def test_ask_sends_cap_and_context_and_joins_the_stream():
    s = FakeStream(
        [tok("bill"), tok("ing"), {"message": {"content": ""}, "done": True, "done_reason": "stop", "eval_count": 2}]
    )
    answer, error, _, tokens = er.ask("m:1", BY_ID["intent-001"], s.url, memory=PLENTY)
    assert (answer, error, tokens) == ("billing", "", 2)
    opts = s.bodies[0]["options"]
    assert opts["num_predict"] == er.MAX_TOKENS and opts["num_ctx"] == er.CONTEXT and opts["temperature"] == 0
    s.server.shutdown()


def test_hitting_the_token_cap_is_an_error():
    s = FakeStream([tok("loop " * 5), {"done": True, "done_reason": "length", "eval_count": er.MAX_TOKENS}])
    _, error, _, _ = er.ask("m:1", BY_ID["intent-001"], s.url, memory=PLENTY)
    assert "token cap" in error
    s.server.shutdown()


def test_low_memory_mid_answer_raises():
    s = FakeStream([tok("x")] * 200)
    with pytest.raises(er.LowMemory):
        er.ask("m:1", BY_ID["intent-001"], s.url, memory=lambda: 5)
    s.server.shutdown()


def test_time_limit_stops_a_slow_answer(monkeypatch):
    monkeypatch.setattr(er, "ITEM_SECONDS", 0.2)
    s = FakeStream([tok("x")] * 50, delay=0.02)
    _, error, secs, _ = er.ask("m:1", BY_ID["intent-001"], s.url, memory=PLENTY)
    assert "time limit" in error and secs < 2
    s.server.shutdown()


def test_low_memory_reloads_the_model_and_carries_on(con, monkeypatch):
    unloaded = []
    monkeypatch.setattr(er, "unload", lambda model, url=None: unloaded.append(model))
    monkeypatch.setattr(er.time, "sleep", lambda s: None)
    readings = iter([90, 90, 35, 90] + [90] * 100)  # dips below the reload line before item 2, recovers
    run_id = er.run(["m:1"], ITEMS[:3], con, asker=FakeAsker(), memory=lambda: next(readings))
    done = con.execute("SELECT COUNT(*) FROM results WHERE run_id=?", (run_id,)).fetchone()[0]
    assert done == 3  # nothing lost
    assert unloaded == ["m:1", "m:1"]  # one reload mid-run, one unload at the end


# ---------- moving runs between machines ----------


def test_dump_then_load_on_another_machine(con, tmp_path):
    run_id = er.run(["m:1"], ITEMS[:4], con, asker=FakeAsker(), memory=PLENTY)
    path = tmp_path / "pc.results.jsonl"
    assert er.dump(con, run_id, path) == 4
    other = er.connect(tmp_path / "mac.db")
    assert er.load(other, path) == (run_id, 4)
    assert er.load(other, path) == (run_id, 0)  # loading twice adds nothing
    a = [tuple(r) for r in con.execute("SELECT * FROM results ORDER BY item_id")]
    b = [tuple(r) for r in other.execute("SELECT * FROM results ORDER BY item_id")]
    assert a == b


def test_dump_is_utf8_on_every_os(con, tmp_path):
    # Windows defaults to cp1252, which can't write U+2011 and writes an em dash as byte 0x97.
    reply = "Caller‑ID verified — refund issued"
    run_id = er.run(["m:1"], ITEMS[:1], con, asker=FakeAsker(reply=reply), memory=PLENTY)
    path = tmp_path / "pc.results.jsonl"
    er.dump(con, run_id, path)
    assert reply.encode("utf-8") in path.read_bytes()
    other = er.connect(tmp_path / "mac.db")
    er.load(other, path)
    assert other.execute("SELECT answer FROM results").fetchone()[0] == reply


def test_eval_set_dashes_survive_loading():
    raw = (Path(__file__).parent.parent / "evals" / "sets" / "contact-center.jsonl").read_bytes().decode("utf-8")
    assert "—" in raw and "—" in json.dumps(ITEMS, ensure_ascii=False)
    assert "â€" not in json.dumps(ITEMS, ensure_ascii=False)  # cp1252 mojibake of a dash
