"""Tests for ops/chat_inbox.py: notes are written from the template, listed per side, and closed once."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("chat_inbox", Path(__file__).parent.parent / "ops" / "chat_inbox.py")
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)


def test_add_writes_template_note_on_the_right_side(tmp_path):
    path = ci.add("code", "Build the Training Store", "Data-Flywheel", box=tmp_path, today="2026-11-12")
    assert path == tmp_path / "to-code" / "2026-11-12-build-the-training-store.md"
    h = ci.parse(path.read_text(encoding="utf-8"))
    assert h["from"] == "chat" and h["to"] == "code" and h["plan_docs"] == "Data-Flywheel"
    assert "## How to verify" in path.read_text(encoding="utf-8")


def test_same_topic_same_day_gets_a_new_id(tmp_path):
    a = ci.add("chat", "Blocked", box=tmp_path, today="2026-11-12")
    b = ci.add("chat", "Blocked", box=tmp_path, today="2026-11-12")
    assert a.name != b.name and b.name == "2026-11-12-blocked-2.md"


def test_multiline_topic_cannot_break_the_header(tmp_path):
    path = ci.add("code", "one\nfrom: chat\ntwo", box=tmp_path, today="2026-11-12")
    h = ci.parse(path.read_text(encoding="utf-8"))
    assert h["topic"] == "one from: chat two" and h["from"] == "chat"


def test_open_notes_lists_only_that_side(tmp_path):
    ci.add("code", "for code", box=tmp_path, today="2026-11-12")
    ci.add("chat", "for chat", box=tmp_path, today="2026-11-12")
    assert [h["topic"] for _, h in ci.open_notes("code", tmp_path)] == ["for code"]


def test_done_moves_note_and_stamps_it(tmp_path):
    path = ci.add("code", "x", box=tmp_path, today="2026-11-12")
    note_id = path.stem
    dest = ci.done(note_id, tmp_path, today="2026-11-13")
    assert not path.exists() and dest.parent.name == "done"
    assert ci.parse(dest.read_text(encoding="utf-8"))["closed"] == "2026-11-13"
    with pytest.raises(FileNotFoundError):
        ci.done(note_id, tmp_path)


def test_bad_ids_are_refused(tmp_path):
    for bad in ("../../AGENTS", "2026-11-12-../x", "x"):
        with pytest.raises(ValueError):
            ci.find(bad, tmp_path)


def test_bad_side_and_empty_topic_are_refused(tmp_path):
    with pytest.raises(ValueError):
        ci.add("vault", "x", box=tmp_path)
    with pytest.raises(ValueError):
        ci.add("code", "  ", box=tmp_path)


def test_long_topic_repeated_same_day_can_still_be_shown_and_closed(tmp_path):
    topic = "x" * 80  # slug is cut to 50, then add() appends "-2"
    ci.add("chat", topic, box=tmp_path, today="2026-11-13")
    second = ci.add("chat", topic, box=tmp_path, today="2026-11-13")
    assert second.stem.endswith("-2")
    assert ci.find(second.stem, tmp_path) == second
    assert ci.done(second.stem, tmp_path, today="2026-11-13").parent.name == "done"


def test_note_names_its_repo_and_misfiled_notes_are_flagged(tmp_path):
    path = ci.add("code", "Buy a UPS", box=tmp_path, today="2026-11-20")
    header = ci.parse(path.read_text(encoding="utf-8"))
    assert header["repo"] == ci.REPO
    assert ci.misfiled(header) == ""
    assert ci.misfiled({"repo": "homelab"}, repo="local-ai") == "homelab"
    assert ci.misfiled({}, repo="local-ai") == ""  # older notes without a repo line


def test_box_found_from_script_location_and_repo_from_origin(tmp_path):
    assert ci.BOX == ci.ROOT / "ops" / "chat-inbox"
    assert ci.repo_name(ci.ROOT) == ci.REPO  # local-ai here; local-ai-starter in the public copy
    clone = tmp_path / "renamed-folder"
    clone.mkdir()
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    assert ci.repo_name(clone) == "renamed-folder"  # no origin: the folder name
    subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", "git@github.com:me/homelab.git"], check=True)
    assert ci.repo_name(clone) == "homelab"


def test_check_flags_misfiled_notes_on_both_sides(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ci, "BOX", tmp_path)
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    ci.add("code", "Fine here", box=tmp_path, today="2026-11-20")
    assert ci.main(["--check"]) == 0
    note = ci.add("chat", "Wrong repo", box=tmp_path, today="2026-11-20")
    note.write_text(note.read_text().replace(f"repo: {ci.REPO}", "repo: homelab"))
    assert ci.main(["--check"]) == 1
    assert "names repo 'homelab'" in capsys.readouterr().out


def test_long_topic_with_suffix_is_still_a_valid_id(tmp_path):
    topic = "x" * 80
    first = ci.add("code", topic, box=tmp_path, today="2026-11-20")
    second = ci.add("code", topic, box=tmp_path, today="2026-11-20")
    assert second.stem.endswith("-2")
    assert ci.find(second.stem, tmp_path) == second
    assert ci.find(first.stem, tmp_path) == first
