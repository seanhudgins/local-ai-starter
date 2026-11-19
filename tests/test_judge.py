"""The API judge grades pending judgment items, records cost per call, and stops at the spend cap.
A fake client stands in for the Anthropic SDK: no network, no key."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import judge as jd
import pytest
import run as rn

CFG = jd.Config(
    "claude-opus-5-5", "medium", 16000, {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.2}, "s", "a"
)
ITEMS = {
    "qa-001": {"instructions": "Score it.", "input": "transcript", "reference": {"x": 1}, "grader": {"rubric": "1-5"}},
    "qa-002": {"instructions": "Score it.", "input": "transcript", "reference": "ok", "grader": {"rubric": "1-5"}},
    "intent-001": {"instructions": "Label.", "input": "t", "reference": "a", "grader": None},
}


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        stop, text = self.replies.pop(0)
        usage = NS(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return NS(stop_reason=stop, content=[NS(type="text", text=text)], usage=usage)


@pytest.fixture
def con(tmp_path):
    c = rn.connect(tmp_path / "r.db")
    for item_id in ITEMS:
        c.execute(
            "INSERT INTO results (run_id, item_id, model, answer, error) VALUES (?,?,?,?,?)",
            ("R", item_id, "m", "an answer", ""),
        )
    c.commit()
    return c


def ok(score, reason="fine"):
    return ("end_turn", json.dumps({"score": score, "reason": reason}))


def test_cost_from_usage():
    usage = NS(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    assert jd.cost(usage, CFG.prices) == pytest.approx(0.004 + 0.01)


def test_grades_only_judgment_items_and_logs_cost(con):
    client = FakeClient([ok(4), ok(2)])
    graded, spent = jd.judge(con, "R", ITEMS, client, CFG, max_usd=5, say=lambda *_: None)
    assert graded == 2 and spent == pytest.approx(0.028)
    rows = {r["item_id"]: r for r in con.execute("SELECT * FROM results")}
    assert rows["qa-001"]["judge_score"] == 4 and rows["qa-001"]["judge"] == "claude-opus-5-5"
    assert rows["intent-001"]["judge_score"] is None
    assert con.execute("SELECT COUNT(*), SUM(usd) FROM judge_calls").fetchone()[0] == 2
    sent = client.calls[0]
    assert sent["model"] == "claude-opus-5-5" and sent["output_config"]["format"]["type"] == "json_schema"
    assert "<model_answer>\nan answer" in sent["messages"][0]["content"]


def test_stops_before_the_cap(con):
    client = FakeClient([ok(4), ok(2)])
    graded, spent = jd.judge(con, "R", ITEMS, client, CFG, max_usd=0.02, say=lambda *_: None)
    assert graded == 1 and len(client.calls) == 1  # a second $0.014 call could pass $0.02


def test_limit_measures_a_small_batch(con):
    client = FakeClient([ok(5)])
    assert jd.judge(con, "R", ITEMS, client, CFG, max_usd=5, limit=1, say=lambda *_: None)[0] == 1


def test_refusal_and_bad_json_stay_unscored(con):
    client = FakeClient([("refusal", ""), ("end_turn", "not json")])
    graded, _ = jd.judge(con, "R", ITEMS, client, CFG, max_usd=5, say=lambda *_: None)
    assert graded == 0
    outcomes = [r[0] for r in con.execute("SELECT outcome FROM judge_calls ORDER BY item_id")]
    assert outcomes[0] == "refusal" and outcomes[1].startswith("unreadable")


def test_already_judged_items_are_skipped(con):
    con.execute("UPDATE results SET judge_score=3 WHERE item_id='qa-001'")
    client = FakeClient([ok(4)])
    assert jd.judge(con, "R", ITEMS, client, CFG, max_usd=5, say=lambda *_: None)[0] == 1


def test_missing_key_explains_how_to_store_it(monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *_: None)
    with pytest.raises(SystemExit, match="security add-generic-password -s s -a a -w"):
        jd.make_client(CFG)


def test_config_file_loads():
    cfg = jd.load_config()
    assert cfg.model.startswith("claude-") and set(cfg.prices) == {"input", "output", "cache_write", "cache_read"}


def test_contact_center_judge_prompt_is_unchanged():
    """Scores already paid for were graded with this exact prompt; changing it would split the results."""
    assert jd.PROMPT_SHA == "9f67ec7e67ee"
    assert jd.system_for({"id": "intent-001"}) == jd.SYSTEM


def test_other_sets_name_their_kind_of_work():
    item = {"judge_subject": "everyday knowledge-work tasks"}
    system = jd.system_for(item)
    assert "everyday knowledge-work tasks" in system and "contact-center" not in system
    assert jd.prompt_sha(system) != jd.PROMPT_SHA
