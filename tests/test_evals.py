"""The eval set is trustworthy: every reference answer passes its own rule checks, and obvious wrong
answers fail them. Also unit tests for the rule-check engine (evals/checks.py)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import checks as ck
import pytest

SET = Path(__file__).parent.parent / "evals" / "sets" / "contact-center.jsonl"
ITEMS = [json.loads(line) for line in SET.read_text().splitlines() if line.strip()]
BY_TYPE = {t: [i for i in ITEMS if i["task_type"] == t] for t in {i["task_type"] for i in ITEMS}}
KNOWN = {
    "exact_label",
    "must_contain",
    "must_not_contain",
    "json_schema",
    "field_equals",
    "field_range",
    "field_matches",
    "field_not_matches",
    "max_words",
}


# ---------- the set itself ----------


def test_set_shape():
    assert len(ITEMS) == 27
    assert len({i["id"] for i in ITEMS}) == len(ITEMS)
    prefixes = {i["id"].split("-")[0] for i in ITEMS}
    assert prefixes == {"intent", "redact", "summary", "extract", "qa", "risk", "followup", "route"}
    assert {i["industry"] for i in ITEMS} == {"healthcare", "banking"}


@pytest.mark.parametrize("item", ITEMS, ids=lambda i: i["id"])
def test_item_is_well_formed(item):
    for key in ("id", "task_type", "industry", "instructions", "input", "checks", "reference"):
        assert key in item, key
    for c in item["checks"]:
        assert c["type"] in KNOWN, c["type"]
        for p in c.get("patterns", []) + ([c["pattern"]] if "pattern" in c else []):
            re.compile(p)
        if c["type"] == "json_schema":
            assert "output_schema" in item
    assert item["grader"] is None or "rubric" in item["grader"]


@pytest.mark.parametrize("item", ITEMS, ids=lambda i: i["id"])
def test_reference_answer_passes_its_own_checks(item):
    results = ck.run_checks(item, ck.reference_reply(item))
    assert all(r.ok for r in results), [(r.check, r.detail) for r in results if not r.ok]


@pytest.mark.parametrize("item", BY_TYPE["redact"], ids=lambda i: i["id"])
def test_unredacted_input_fails_redaction_checks(item):
    """Echoing the transcript back unchanged must fail: proves the checks catch leaked PII."""
    assert not all(r.ok for r in ck.run_checks(item, item["input"]))


@pytest.mark.parametrize("item", [i for i in ITEMS if i.get("output_schema")], ids=lambda i: i["id"])
def test_empty_json_fails(item):
    assert not all(r.ok for r in ck.run_checks(item, "{}"))


@pytest.mark.parametrize("item", [i for i in ITEMS if i["checks"][0]["type"] == "exact_label"], ids=lambda i: i["id"])
def test_every_wrong_label_fails(item):
    check = item["checks"][0]
    for label in check["allowed"]:
        if label != check["expected"]:
            assert not ck.run_checks(item, label)[0].ok, label


def test_synthetic_data_only():
    """Fictional values only: reserved 555-01xx phones, example domains, test card and SSN."""
    text = SET.read_text()
    assert not re.search(r"\b555-0(?!1\d\d)\d{3}\b", text)  # only the reserved 555-0100..0199 range
    for email in re.findall(r"[\w.+-]+@([\w-]+\.[a-z]+)", text):
        assert email.split(".")[0] == "example", email
    for card in re.findall(r"\b\d{4} \d{4} \d{4} \d{4}\b", text):
        assert card == "4111 1111 1111 1111", card
    for ssn in re.findall(r"\b\d{3}-\d{2}-\d{4}\b", text):
        assert ssn.startswith("000-"), ssn  # area 000 is never issued


# ---------- the engine ----------


def test_exact_label_ignores_case_quotes_and_period():
    item = {"checks": [{"type": "exact_label", "expected": "card_fraud"}]}
    assert ck.run_checks(item, ' "Card_Fraud". ')[0].ok


def test_json_in_a_fence_or_with_chatter_is_parsed():
    assert ck.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ck.parse_json('Sure! Here it is: {"a": 1} Hope that helps.') == {"a": 1}


def test_schema_subset():
    schema = {
        "type": "object",
        "required": ["n", "s"],
        "properties": {
            "n": {"type": "integer", "minimum": 1, "maximum": 5},
            "s": {"type": "string", "pattern": r"^\d{4}$"},
            "e": {"enum": ["a", "b"]},
            "l": {"type": "array", "items": {"enum": ["x"]}},
        },
    }
    assert ck.schema_errors({"n": 3, "s": "2026"}, schema) == []
    assert ck.schema_errors({"n": 3.5, "s": "2026"}, schema)  # not an integer
    assert ck.schema_errors({"n": True, "s": "2026"}, schema)  # booleans aren't numbers
    assert ck.schema_errors({"n": 9, "s": "26", "e": "c", "l": ["y"]}, schema)
    assert ck.schema_errors({"s": "2026"}, schema)  # missing n


def test_field_equals_options():
    item = {"checks": []}
    run = lambda c, r: ck.run_check(c, r, item).ok  # noqa: E731
    assert run({"type": "field_equals", "field": "x", "expected": 212.40}, '{"x": 212.4}')
    assert not run({"type": "field_equals", "field": "x", "expected": 15}, '{"x": true}')
    assert run({"type": "field_equals", "field": "x", "expected": "spanish", "casefold": True}, '{"x": "Spanish"}')
    assert run({"type": "field_equals", "field": "x", "expected": ["a", "b"], "unordered": True}, '{"x": ["b", "a"]}')
    assert not run({"type": "field_equals", "field": "x", "expected": 1}, '{"y": 1}')


def test_non_json_reply_fails_json_checks_without_crashing():
    item = {"checks": [{"type": "json_schema"}], "output_schema": {"type": "object"}}
    result = ck.run_checks(item, "I can't help with that.")[0]
    assert not result.ok and "can't check" in result.detail


def test_lookalike_dashes_and_spaces_are_normalized():
    """Regression (north-mini-code wrote '5\u20117' with a non-breaking hyphen)."""
    item = {"checks": [{"type": "must_contain", "patterns": [r"5\s*(-|to)\s*7 business days"]}]}
    for dash in ("-", "\u2011", "\u2013", "\u2014"):
        assert ck.run_checks(item, f"ships in 5{dash}7\u00a0business days")[0].ok, repr(dash)
