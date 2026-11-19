"""The session-start briefing reads STATUS sections, inbox tasks and unloaded runs, and never fails."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sqlite3
from pathlib import Path

_spec = importlib.util.spec_from_file_location("session", Path(__file__).parent.parent / "ops" / "session.py")
se = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(se)

STATUS = """# status
## Current step
v1-1 in progress.

## Next steps
- do the thing

## Open problems
- not shown
"""


def test_status_sections_returns_only_the_named_ones():
    out = se.status_sections(STATUS)
    assert "v1-1 in progress." in out and "- do the thing" in out and "not shown" not in out


def test_inbox_and_unloaded_runs(tmp_path, monkeypatch):
    (tmp_path / "ops" / "results").mkdir(parents=True)
    (tmp_path / "ops" / "inbox.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": "a", "machine": "PC1", "check": "eval", "model": "m"},
                    {"id": "b", "machine": "PC1", "check": "verify", "model": "m"},
                    {"id": "c", "machine": "MAC1", "check": "verify", "model": "m"},
                ]
            }
        )
    )
    (tmp_path / "ops" / "results" / "b.txt").write_text("done")
    (tmp_path / "evals" / "runs").mkdir(parents=True)
    for rid in ("r1", "r2"):
        (tmp_path / "evals" / "runs" / f"{rid}.jsonl").write_text("{}")
    with contextlib.closing(sqlite3.connect(tmp_path / "evals" / "results.db")) as con:
        con.execute("CREATE TABLE runs (run_id TEXT)")
        con.execute("INSERT INTO runs VALUES ('r1')")
        con.commit()
    monkeypatch.setattr(se, "ROOT", tmp_path)
    assert se.inbox_waiting("pc1") == ["a: eval m"]
    assert se.runs_not_loaded() == 1


def test_main_never_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(se, "ROOT", tmp_path)  # not a git repo, no STATUS.md, no inbox
    assert se.main() == 0
    assert "Machine:" in capsys.readouterr().out


def test_chat_notes_lists_open_to_code_notes(tmp_path, monkeypatch):
    box = tmp_path / "ops" / "chat-inbox" / "to-code"
    box.mkdir(parents=True)
    (box / "2026-11-12-hello.md").write_text("---\nid: 2026-11-12-hello\ntopic: Say hello\n---\n\nbody\n")
    (tmp_path / "ops" / "chat-inbox" / "to-chat").mkdir()
    (tmp_path / "ops" / "chat-inbox" / "to-chat" / "2026-11-12-x.md").write_text("---\ntopic: not for code\n---\n")
    monkeypatch.setattr(se, "ROOT", tmp_path)
    assert se.chat_notes() == ["2026-11-12-hello: Say hello"]
