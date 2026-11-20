"""The alias filter swaps private names for placeholders and back exactly, and the guard catches leaks."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
    assert af.guard(af.load()) == ["leak.txt: {{alias:pc}}"]  # keys only, never the name


# ---- 1Password sync and the drift check ----


class FakeOp:
    """Stands in for the 1Password CLI: one document in memory."""

    def __init__(self, doc: dict | None):
        self.doc = json.dumps(doc) if doc is not None else None
        self.calls: list[tuple] = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("document", "get"):
            if self.doc is None:
                raise SystemExit("not found")
            return self.doc
        if args[:2] in (("document", "edit"), ("document", "create")):
            path = args[3] if args[1] == "edit" else args[2]
            self.doc = Path(path).read_text()
            return ""
        raise AssertionError(args)


@pytest.fixture
def fake_op(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAI_ALIASES", str(tmp_path / "aliases.json"))
    op = FakeOp({"terms": TERMS})
    monkeypatch.setattr(af, "_op", op)
    monkeypatch.setattr(af, "_op_exists", lambda ref: op.doc is not None)
    return op


def test_pull_writes_private_copy_and_reports_keys_only(fake_op, capsys):
    assert af.pull() == TERMS
    assert af.load() == TERMS
    if sys.platform != "win32":  # Windows has no POSIX modes; the profile folder is already per-user
        assert oct(af.map_path().stat().st_mode & 0o777) == "0o600"
    out = capsys.readouterr().out
    assert "4 keys" in out and not any(real in out for real in TERMS)


def test_add_pulls_first_then_pushes(fake_op, capsys):
    af._write_map({"PCNAME": "pc"})  # this machine is behind 1Password
    af.add("BuddyName", "backup-buddy")
    pushed = json.loads(fake_op.doc)["terms"]
    assert pushed == {**TERMS, "BuddyName": "backup-buddy"}  # nothing another machine added was lost
    assert af.load() == pushed
    assert "BuddyName" not in capsys.readouterr().out


def test_add_rejects_duplicates_and_bad_keys(fake_op):
    with pytest.raises(SystemExit, match="already mapped"):
        af.add("PCNAME", "other")
    with pytest.raises(SystemExit, match="already used"):
        af.add("NewName", "pc")
    with pytest.raises(SystemExit, match="lowercase"):
        af.add("NewName", "Bad Key")


def test_push_creates_the_document_first_time(fake_op):
    fake_op.doc = None
    af.push({"PCNAME": "pc"})
    assert fake_op.calls[-1][:2] == ("document", "create")
    assert json.loads(fake_op.doc)["terms"] == {"PCNAME": "pc"}


def test_check_finds_missing_keys_and_stale_files_without_names(tmp_path, monkeypatch):
    amap = tmp_path / "aliases.json"
    amap.write_text(json.dumps({"terms": {"PCNAME": "pc"}}))  # this machine only knows one name
    monkeypatch.setenv("LOCALAI_ALIASES", str(amap))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / ".gitattributes").write_text("*.md filter=alias\n")
    # As cloned onto a machine whose map is behind: one unknown key, one key the map now has.
    (repo / "net.md").write_text("{{alias:isp}} and {{alias:iot-vlan}}\n")
    (repo / "pc.md").write_text("{{alias:pc}} is the desktop\n")
    (repo / "code.py").write_text("x = '{{alias:unknown}}'\n")  # not filtered: ignored
    monkeypatch.chdir(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")  # no filter configured yet, so files commit as-is
    af.install()
    (repo / "pc.md").write_text("{{alias:pc}} is the desktop\n")  # simulate a checkout from before the map had pc

    missing, stale = af.check(af.load())
    assert missing == {"iot-vlan": ["net.md"], "isp": ["net.md"]}
    assert stale == ["pc.md"]
    msg = af.report(missing, stale)
    assert "iot-vlan, isp" in msg and "PCNAME" not in msg

    # The pre-commit guard blocks while the map is missing keys.
    assert af.main(["x", "guard"]) == 1

    # After a sync brings the full map, refresh shows real names and the guard passes.
    amap.write_text(json.dumps({"terms": TERMS}))
    _, stale = af.check(af.load())
    assert af.refresh(stale) == []
    assert (repo / "net.md").read_text() == "NetCo and NetCo-IoT\n"
    assert af.check(af.load()) == ({}, [])
    assert af.main(["x", "guard"]) == 0


def test_op_runs_as_service_account_when_token_stored(monkeypatch):
    monkeypatch.setattr(af, "_service_token", lambda: "ops_test")
    assert af._op_env()["OP_SERVICE_ACCOUNT_TOKEN"] == "ops_test"
    monkeypatch.setattr(af, "_service_token", lambda: None)
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    assert "OP_SERVICE_ACCOUNT_TOKEN" not in af._op_env()  # falls back to the desktop app sign-in


# ---- Hardening from the 2026-11-20 review ----


def test_clean_ignores_case_and_smudge_restores_map_spelling():
    assert af.clean("pcname, Pcname and PCNAME", TERMS) == "{{alias:pc}}, {{alias:pc}} and {{alias:pc}}"
    assert af.names_in("ask alex", TERMS) == ["buddy"]
    assert af.names_in("alexandria", TERMS) == []


def _repo(tmp_path, monkeypatch, terms=TERMS):
    amap = tmp_path / "aliases.json"
    amap.write_text(json.dumps({"terms": terms}))
    monkeypatch.setenv("LOCALAI_ALIASES", str(amap))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / ".gitattributes").write_text("*.md filter=alias\n*.ps1 filter=alias\n")
    monkeypatch.chdir(repo)
    return repo, amap


def test_guard_catches_lowercase_names_and_file_names(tmp_path, monkeypatch):
    repo, _ = _repo(tmp_path, monkeypatch)
    af.install()
    (repo / "pcname-notes.txt").write_text("netco outage\n")  # not filtered, lowercase name, name in the path
    git(repo, "add", "-A")
    hits = af.guard(af.load())
    assert "pcname-notes.txt (file name): {{alias:pc}}" in hits
    assert "pcname-notes.txt: {{alias:isp}}" in hits
    assert not any("PCNAME" in h or "NetCo" in h for h in hits)


def test_utf16_and_crlf_files_are_filtered_both_ways(tmp_path, monkeypatch):
    repo, _ = _repo(tmp_path, monkeypatch)
    af.install()
    ps1 = "Write-Host 'PCNAME'\r\n".encode("utf-16-le")
    (repo / "setup.ps1").write_bytes(b"\xff\xfe" + ps1)  # what Windows PowerShell 5 writes
    (repo / "notes.md").write_bytes(b"PCNAME uses NetCo.\r\n")
    git(repo, "add", "-A")
    assert af.guard(af.load()) == []
    git(repo, "commit", "-q", "-m", "x")
    stored = subprocess.run(["git", "show", "HEAD:setup.ps1"], capture_output=True, check=True).stdout
    assert stored.startswith(b"\xff\xfe") and stored[2:].decode("utf-16-le") == "Write-Host '{{alias:pc}}'\r\n"
    raw = subprocess.run(["git", "show", "HEAD:notes.md"], capture_output=True, check=True).stdout
    assert raw == b"{{alias:pc}} uses {{alias:isp}}.\r\n"
    assert (repo / "setup.ps1").read_bytes() == b"\xff\xfe" + ps1  # smudged back on disk


def test_unfiltered_utf16_leak_is_blocked(tmp_path, monkeypatch):
    repo, _ = _repo(tmp_path, monkeypatch)
    af.install()
    (repo / "out.txt").write_bytes(b"\xff\xfe" + "PCNAME\r\n".encode("utf-16-le"))
    git(repo, "add", "-A")
    assert af.guard(af.load()) == ["out.txt: {{alias:pc}}"]


def test_guard_blocks_when_map_drops_a_key_the_repo_uses(tmp_path, monkeypatch, capsys):
    repo, amap = _repo(tmp_path, monkeypatch)
    af.install()
    (repo / "net.md").write_text("NetCo is the ISP\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    amap.write_text(json.dumps({"terms": {"PCNAME": "pc"}}))  # isp dropped; the file on disk still shows the name
    assert af.check(af.load()) == ({}, [])  # the working-file check can't see it...
    assert af.main(["x", "guard"]) == 1  # ...but HEAD still uses {{alias:isp}}, so the guard blocks
    err = capsys.readouterr().err
    assert "isp" in err and "NetCo" not in err


def test_guard_message_checks_message_and_branch(tmp_path, monkeypatch):
    repo, _ = _repo(tmp_path, monkeypatch)
    git(repo, "checkout", "-q", "-b", "fix-netco")
    msg = tmp_path / "MSG"
    msg.write_text("Fix the pcname backup\n# comment lines like PCNAME are skipped\n")
    hits = af.guard_message(msg.read_text(), af.load())
    assert hits == ["commit message: {{alias:pc}}", "branch name: {{alias:isp}}"]
    assert af.main(["x", "guard-msg", str(msg)]) == 1
    msg.write_text("Fix the {{alias:pc}} backup\n")
    git(repo, "checkout", "-q", "-b", "fix-backup")
    assert af.main(["x", "guard-msg", str(msg)]) == 0


def test_install_turns_on_repo_hooks(tmp_path, monkeypatch):
    repo, _ = _repo(tmp_path, monkeypatch)
    (repo / ".githooks").mkdir()
    (repo / "keep.txt").write_text("not filtered\n")
    af.install()
    assert git(repo, "config", "core.hooksPath").strip() == ".githooks"
    assert (repo / "keep.txt").exists()


def test_pull_refuses_to_drop_keys_without_force(fake_op):
    af._write_map({**TERMS, "BuddyName": "backup-buddy"})  # this machine has a key 1Password lost
    with pytest.raises(SystemExit, match="backup-buddy") as exc:
        af.pull()
    assert "BuddyName" not in str(exc.value)
    assert "backup-buddy" in af.load().values()  # nothing overwritten
    af.pull(force=True)
    assert "backup-buddy" not in af.load().values()


def test_push_merges_instead_of_overwriting(fake_op):
    af.push({"PCNAME": "pc", "BuddyName": "backup-buddy"})  # a stale machine pushing a partial map
    assert json.loads(fake_op.doc)["terms"] == {**TERMS, "BuddyName": "backup-buddy"}
    af.push({"PCNAME": "pc"}, replace=True)  # deliberate removal
    assert json.loads(fake_op.doc)["terms"] == {"PCNAME": "pc"}


def test_push_conflicts_name_keys_only(fake_op):
    with pytest.raises(SystemExit, match="conflict") as exc:
        af.push({"PCNAME": "desktop"})
    assert "PCNAME" not in str(exc.value)
    with pytest.raises(SystemExit, match="key 'pc'"):
        af.push({"OtherPC": "pc"})
