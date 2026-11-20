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
        *(f"redact-{n:03d}" for n in range(1, 11)),
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
    run_id = er.run(["m:1"], [BY_ID["redact-001"]], con, asker=FakeAsker(), memory=PLENTY)
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
            "1.0, 1, 0, rules_total, '[]', NULL, NULL, NULL, item_sha FROM results WHERE run_id=? AND item_id=?",
            (run_id, item["id"]),
        )
    text = er.report(con, run_id)
    assert text.index("`good:1`") < text.index("`bad:1`")  # sorted best first
    assert f"| `good:1` | {len(ITEMS)} | {len(ITEMS)} | 100.0 |" in text


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


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def readings_guard(values, step=0.5):
    """Feed a MemoryGuard one reading per `step` seconds; return the reading index where it tripped (or None)."""
    clock, it = Clock(), iter(values)
    guard = er.MemoryGuard(memory=lambda: next(it), clock=clock)
    for i in range(len(values)):
        if guard.check():
            return i
        clock.t += step
    return None


def test_guard_allows_a_short_dip():
    """gemma4:31b-mlx, 2026-11-07: ~2 s at 19-23% right after loading, then 35-49%."""
    assert readings_guard([90, 48, 35, 20, 19, 20, 25, 45, 40, 47] * 3) is None


def test_guard_catches_a_slow_creep():
    """The 2026-11-04 freeze: memory fell and stayed down."""
    creep = [40, 35, 30, 26] + [24] * 20
    tripped = readings_guard(creep)
    assert tripped is not None and (tripped - 4) * 0.5 > er.LOW_GRACE_S  # only after the grace period


def test_guard_hard_floor_trips_at_once():
    assert readings_guard([90, 50, 11]) == 2


def test_guard_resets_when_memory_recovers():
    # two separate 4 s dips are each within the grace period
    assert readings_guard(([20] * 8 + [50]) * 2) is None


def test_stalled_answer_is_stopped_by_the_background_check(monkeypatch):
    """No tokens arrive (the model is stuck loading or thinking); the watcher still unloads it."""
    unloaded = []
    monkeypatch.setattr(er, "unload", lambda model, url=None: unloaded.append(model))
    monkeypatch.setattr(er, "WATCH_EVERY_S", 0.01)
    readings = iter([90] + [5] * 1000)  # fine at the start, then below the hard floor
    s = FakeStream([tok("x")] * 3, delay=0.3)
    with pytest.raises(er.LowMemory):
        er.ask("m:1", BY_ID["intent-001"], s.url, memory=lambda: next(readings))
    assert unloaded == ["m:1"]
    s.server.shutdown()


def test_run_waits_out_a_short_dip_before_an_item(con, monkeypatch):
    monkeypatch.setattr(er, "unload", lambda model, url=None: None)
    slept = []
    monkeypatch.setattr(er.time, "sleep", slept.append)
    readings = iter([90, 90, 20, 20, 60] + [90] * 100)  # item 2: low, still low after reload, fine after grace
    run_id = er.run(["m:1"], ITEMS[:3], con, asker=FakeAsker(), memory=lambda: next(readings))
    assert con.execute("SELECT COUNT(*) FROM results WHERE run_id=?", (run_id,)).fetchone()[0] == 3
    assert er.LOW_GRACE_S in slept


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


# ---------- run records, fingerprints, sync and rebuild (2026-11-12) ----------


def test_item_fingerprint_ignores_notes_only():
    item = BY_ID["intent-001"]
    assert er.item_sha(item) == er.item_sha({**item, "notes": "reworded note"})
    assert er.item_sha(item) != er.item_sha({**item, "input": item["input"] + " "})


def test_run_stamps_set_and_item_versions(con):
    run_id = er.run(["m:1"], ITEMS[:3], con, asker=FakeAsker(), memory=PLENTY)
    assert con.execute("SELECT set_sha FROM runs").fetchone()[0] == er.fingerprint(er.DEFAULT_SET.read_bytes())
    shas = [r[0] for r in con.execute("SELECT item_sha FROM results WHERE run_id=? ORDER BY item_id", (run_id,))]
    assert shas == sorted(er.item_sha(i) for i in ITEMS[:3]) or len(set(shas)) == 3


def test_record_round_trip_keeps_grades_and_judge_calls(con, tmp_path):
    run_id = er.run(["m:1"], [BY_ID["redact-001"]], con, asker=FakeAsker(), memory=PLENTY)
    con.execute("UPDATE results SET judge='claude-opus-5-5', judge_score=4, judge_reason='ok'")
    con.execute(
        "INSERT INTO judge_calls (run_id, item_id, model, judge, usd, outcome, prompt_sha) VALUES (?,?,?,?,?,?,?)",
        (run_id, "redact-001", "m:1", "claude-opus-5-5", 0.01, "ok", "abc"),
    )
    path = er.export_run(con, run_id, tmp_path / "runs")
    assert path.name == f"{run_id}.jsonl"
    other = er.connect(tmp_path / "other.db")
    assert er.load(other, path) == (run_id, 1)
    assert other.execute("SELECT judge_score FROM results").fetchone()[0] == 4
    assert other.execute("SELECT usd, prompt_sha FROM judge_calls").fetchone()[:] == (0.01, "abc")


def test_old_databases_gain_the_new_columns(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    old = sqlite3.connect(db)
    old.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, started TEXT, machine TEXT, ollama_version TEXT, "
        "eval_set TEXT, note TEXT)"
    )
    old.commit()
    old.close()
    con = er.connect(db)
    assert "set_sha" in {r["name"] for r in con.execute("PRAGMA table_info(runs)")}


def test_old_run_files_without_new_columns_still_load(con, tmp_path):
    path = tmp_path / "old.results.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "run",
                "run_id": "R1",
                "started": "2026-11-05T15:46:55",
                "machine": "PC1",
                "ollama_version": "0.40.14",
                "eval_set": "contact-center.jsonl",
                "note": "",
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "result",
                "run_id": "R1",
                "item_id": "intent-001",
                "model": "m",
                "answer": "x",
                "error": "",
                "future_column": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert er.load(con, path) == ("R1", 1)


def test_sync_loads_only_new_runs_and_rebuild_restores_everything(con, tmp_path):
    runs = tmp_path / "runs"
    a = er.run(["m:1"], ITEMS[:2], con, asker=FakeAsker(), memory=PLENTY)
    er.export_run(con, a, runs)
    db = tmp_path / "fresh.db"
    fresh = er.connect(db)
    assert er.sync(fresh, sorted(runs.glob("*.jsonl"))) == [a]
    assert er.sync(fresh, sorted(runs.glob("*.jsonl"))) == []  # nothing new the second time
    fresh.close()
    backup, n = er.rebuild(db, sorted(runs.glob("*.jsonl")))
    assert n == 1 and backup is not None and backup.exists()
    assert er.connect(db).execute("SELECT COUNT(*) FROM results").fetchone()[0] == 2


def test_gpu_guard(monkeypatch, tmp_path):
    class Out:
        def __init__(self, text):
            self.stdout = text

    calls = {"ps": {"models": []}}
    monkeypatch.setattr(er.modelcheck, "call", lambda url, path, body=None, timeout=600: calls["ps"])
    monkeypatch.setattr(er.subprocess, "run", lambda *a, **k: Out("85, 9000\n"))
    assert "GPU busy" in er.gpu_in_use()
    monkeypatch.setattr(er.subprocess, "run", lambda *a, **k: Out("3, 700\n"))
    assert er.gpu_in_use() == ""
    calls["ps"] = {"models": [{"name": "m"}]}
    monkeypatch.setattr(er.subprocess, "run", lambda *a, **k: Out("85, 9000\n"))
    assert er.gpu_in_use() == ""  # Ollama's own model explains the use

    def no_smi(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(er.subprocess, "run", no_smi)
    assert er.gpu_in_use() == ""  # no NVIDIA GPU (the Mac): never blocks


def test_busy_gpu_defers_the_run(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(er, "gpu_in_use", lambda url: "GPU busy before the run: 90% use")
    code = er.main(["--db", str(tmp_path / "r.db"), "run", "--models", "m:1"])
    assert code == er.EX_TEMPFAIL and "NOT STARTED" in capsys.readouterr().out


# ---------- compare: the model-origin rule ----------


def S(passed, n=4, judge=None, judged=0, secs=10.0):  # noqa: N802
    return {"n": n, "pass": passed, "judge": judge, "judged": judged, "secs": secs}


@pytest.mark.parametrize(
    ("a", "b", "needs", "oa", "ob", "want"),
    [
        (S(4), S(2), 0, "CN", "US", "a"),  # two more items passing all rules is a real win (WIN_ITEMS)
        (S(4), S(3), 0, "CN", "US", "b"),  # one item is noise on 10-item sets: a tie, which goes to the US model
        (S(4), S(4), 0, "CN", "US", "b"),  # a tie goes to the American model
        (S(4), S(4), 0, "US", "US", ""),  # same origin: a plain tie
        (S(4, judge=4.6, judged=4), S(4, judge=4.2, judged=4), 4, "CN", "US", "a"),  # 0.4 judge points
        (S(4, judge=4.4, judged=4), S(4, judge=4.2, judged=4), 4, "CN", "US", "b"),  # 0.2: tie -> American
        (S(4, judge=4.6, judged=4), S(4), 4, "CN", "US", "?"),  # rules tie and B isn't judged yet
    ],
)
def test_verdict_follows_the_model_origin_rule(a, b, needs, oa, ob, want):
    assert er.verdict(a, b, needs, oa, ob)[0] == want


def test_decide_who_keeps_a_place():
    assert er.decide("a", S(4), S(3), 0, "CN", "US") == "A, with B as the American fallback"
    assert er.decide("b", S(4, secs=30), S(4, secs=10), 0, "CN", "US") == "B only"
    # The Chinese loser is >=25% faster and meets the routine bar: cost may keep it for routine work.
    assert "may keep routine work" in er.decide("b", S(4, secs=5), S(4, secs=10), 0, "CN", "US")
    # ...but not if it misses the routine bar (an item failing its rules).
    assert er.decide("b", S(3, secs=5), S(4, secs=10), 0, "CN", "US") == "B only"
    assert er.decide("?", S(4), S(4), 4, "CN", "US") == "judge first"


def test_compare_skips_items_answered_in_a_different_version(con):
    a = er.run(["qwen:test"], [BY_ID["intent-001"], BY_ID["intent-002"]], con, asker=FakeAsker(), memory=PLENTY)
    b = er.run(["gemma:test"], [BY_ID["intent-001"], BY_ID["intent-002"]], con, asker=FakeAsker(), memory=PLENTY)
    con.execute("UPDATE results SET item_sha='old' WHERE run_id=? AND item_id='intent-002'", (a,))
    out = er.compare(con, (a, "qwen:test"), (b, "gemma:test"), BY_ID)
    assert "1 items compared; 1 skipped (different item versions)" in out
    assert "| intent | 1 | 1 | 1 |" in out


# ---------- more than one eval set (2026-11-13) ----------


def test_set_path_finds_sets_by_name():
    assert er.set_path("my-work") == er.SETS / "my-work.jsonl"
    assert er.set_path("contact-center.jsonl") == er.DEFAULT_SET
    with pytest.raises(SystemExit, match="no eval set"):
        er.set_path("nope")


def test_item_system_line_overrides_the_default():
    work = er.load_items(er.set_path("my-work"))[0]
    assert er.build_prompt(work)[0]["content"] == work["system"] != er.SYSTEM
    assert er.build_prompt(BY_ID["intent-001"])[0]["content"] == er.SYSTEM


def test_run_records_its_set_and_later_commands_reload_it(con):
    path = er.set_path("my-work")
    work = er.load_items(path)[:2]
    run_id = er.run(["m:1"], work, con, asker=FakeAsker(), memory=PLENTY, set_file=path)
    row = con.execute("SELECT eval_set, set_sha FROM runs WHERE run_id=?", (run_id,)).fetchone()
    assert tuple(row) == ("my-work.jsonl", er.fingerprint(path.read_bytes()))
    assert er.run_set(con, run_id) == path
    assert er.run_set(con, "no-such-run") == er.DEFAULT_SET


def test_machine_role_replaces_hostname():
    assert er.machine_role("Windows") == "pc"
    assert er.machine_role("Darwin") == "mac"
    assert er.machine_role("Linux") == "linux"
