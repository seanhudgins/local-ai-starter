"""The dependency audit fails on unreviewed or expired findings, and passes reviewed ones."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location("audit", Path(__file__).parent.parent / "ops" / "audit.py")
au = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(au)

REPORT = {
    "dependencies": [
        {"name": "pyjwt", "version": "2.13.0", "vulns": [{"id": "V-1", "fix_versions": ["2.14.0"]}]},
        {"name": "chromadb", "version": "1.5.9", "vulns": [{"id": "V-2", "fix_versions": []}]},
        {"name": "clean", "version": "1.0", "vulns": []},
    ]
}
TODAY = date(2026, 11, 12)


def test_parse_lists_each_vulnerability():
    found = au.parse(REPORT)
    assert set(found) == {"V-1", "V-2"} and found["V-1"]["package"] == "pyjwt"


def test_unreviewed_findings_fail():
    out = au.problems(au.parse(REPORT), {}, TODAY)
    assert len(out) == 2 and out[0].startswith("NEW") and "fixed in 2.14.0" in out[0] and "no fix yet" in out[1]


def test_accepted_findings_pass_until_their_review_date():
    accepted = {v: {"reason": "r", "review_by": "2026-12-01"} for v in ("V-1", "V-2")}
    assert au.problems(au.parse(REPORT), accepted, TODAY) == []
    late = au.problems(au.parse(REPORT), accepted, date(2026, 12, 2))
    assert len(late) == 2 and all(x.startswith("EXPIRED") for x in late)


def test_the_project_itself_has_no_acceptance_file():
    assert au.LOCKS[au.ROOT] is None
