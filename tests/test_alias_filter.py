"""The alias filter swaps private names for placeholders and back exactly, and the guard catches leaks."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "alias_filter", Path(__file__).parent.parent / "tools" / "git-alias" / "alias_filter.py"
)
af = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(af)

TERMS = {"PCNAME": "pc", "NetCo-IoT": "iot-vlan", "NetCo": "isp", "Alex": "buddy"}


def test_clean_then_smudge_round_trips():
    text = "PCNAME on NetCo-IoT via NetCo; backups with Alex.\n"
    stored = af.clean(text, TERMS)
    assert stored == "{{alias:pc}} on {{alias:iot-vlan}} via {{alias:isp}}; backups with {{alias:buddy}}.\n"
    assert af.smudge(stored, TERMS) == text


def test_whole_words_only():
    assert af.clean("Alexandria and Alex", TERMS) == "Alexandria and {{alias:buddy}}"


def test_unknown_placeholders_and_no_map_pass_through():
    assert af.smudge("{{alias:other}} stays", TERMS) == "{{alias:other}} stays"
    assert af.clean("PCNAME", {}) == "PCNAME"


def test_map_keys_must_be_unique_and_simple(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"terms": {"A": "pc", "B": "pc"}}))
    with pytest.raises(SystemExit, match="unique"):
        af.load(p)
    p.write_text(json.dumps({"terms": {"A": "Has Space"}}))
    with pytest.raises(SystemExit):
        af.load(p)
    assert af.load(tmp_path / "missing.json") == {}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def test_end_to_end_in_a_real_repo(tmp_path, monkeypatch):
    amap = tmp_path / "aliases.json"
    amap.write_text(json.dumps({"terms": TERMS}))
    monkeypatch.setenv("LOCALAI_ALIASES", str(amap))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / ".gitattributes").write_text("*.md filter=alias\n")
    (repo / "notes.md").write_text("PCNAME uses NetCo.\n")
    monkeypatch.chdir(repo)
    af.install()
    git(repo, "add", "-A")
    assert af.guard(af.load()) == []  # staged content is already clean
    git(repo, "commit", "-q", "-m", "x")
    assert git(repo, "show", "HEAD:notes.md") == "{{alias:pc}} uses {{alias:isp}}.\n"  # what GitHub stores
    assert (repo / "notes.md").read_text() == "PCNAME uses NetCo.\n"  # what you see

    # A file outside the filter's patterns is staged raw: the guard blocks it.
    (repo / "leak.txt").write_text("PCNAME\n")
    git(repo, "add", "leak.txt")
    assert af.guard(af.load()) == ["leak.txt: PCNAME"]
