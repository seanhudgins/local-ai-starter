"""The citation hook (tools/claude-hooks/require_citations.py): blocks a research reply with no
sources, and lets everything else through. Cases 5-11 are regressions from the review of the
original kit (2026-11-06), where the first version got them wrong."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import require_citations as rc

HOOK = Path(__file__).parent.parent / "tools" / "claude-hooks" / "require_citations.py"


def user(text):
    return {"type": "user", "message": {"content": text}}


def meta(text):
    return {"type": "user", "isMeta": True, "message": {"content": [{"type": "text", "text": text}]}}


def document():
    return {"type": "user", "message": {"content": [{"type": "document", "source": {}}]}}


def tool(name, tid="t1"):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}]}}


def result(text="ok", tid="t1"):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def say(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


SOURCED = "Answer.\n\nSources:\n- [Docs](https://example.com/docs)"


def decide(tmp_path, entries, last=None, **extra):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    data = {"hook_event_name": "Stop", "transcript_path": str(path), "stop_hook_active": False, **extra}
    if last is not None:
        data["last_assistant_message"] = last
    return "block" if rc.decide(data) else "pass"


CASES = [
    # (name, entries, last message, expected)
    ("research with sources", [user("q"), tool("WebSearch"), result()], SOURCED, "pass"),
    ("research, no sources", [user("q"), tool("WebSearch"), result()], "Answer only.", "block"),
    ("no research", [user("q")], "Answer.", "pass"),
    ("bold heading", [user("q"), tool("WebFetch"), result()], "Ans\n\n**Sources:**\n- [A](https://a.com)", "pass"),
    ("'Source code' line is not a heading", [user("q"), tool("WebSearch"), result()], "Source code: none.", "block"),
    (
        "'Sources are mixed' is not a heading",
        [user("q"), tool("WebSearch"), result()],
        "Sources are mixed. https://a.com",
        "block",
    ),
    (
        "IDE diagnostics MCP tool isn't research",
        [user("q"), tool("mcp__claude-vscode__getDiagnostics"), result()],
        "No errors.",
        "pass",
    ),
    ("search-type MCP tool is research", [user("q"), tool("mcp__brave__web_search"), result()], "Ans.", "block"),
    (
        "a skill loading mid-turn doesn't reset the turn",
        [user("q"), tool("WebSearch"), result(), meta("Base directory for this skill"), say("x")],
        "Ans.",
        "block",
    ),
    (
        "a pasted document starts a new turn",
        [user("old"), tool("WebSearch"), result(), say(SOURCED), document()],
        "Fresh answer.",
        "pass",
    ),
    ("helper agent with web links counts", [user("q"), tool("Agent"), result("see https://a.com")], "Ans.", "block"),
    ("helper agent without links doesn't", [user("q"), tool("Agent"), result("grep found 3 files")], "Ans.", "pass"),
    (
        "file path counts as a source",
        [user("q"), tool("WebSearch"), result()],
        "Ans\nSources:\n- docs/V1-SPEC.md",
        "pass",
    ),
    ("falls back to transcript text", [user("q"), tool("WebSearch"), result(), say(SOURCED)], None, "pass"),
]


@pytest.mark.parametrize("name,entries,last,want", CASES, ids=[c[0] for c in CASES])
def test_cases(tmp_path, name, entries, last, want):
    assert decide(tmp_path, entries, last) == want


def test_never_blocks_twice(tmp_path):
    assert decide(tmp_path, [user("q"), tool("WebSearch"), result()], "Ans.", stop_hook_active=True) == "pass"


def test_subagent_reads_its_own_transcript(tmp_path):
    sub = tmp_path / "agent.jsonl"
    sub.write_text("\n".join(json.dumps(e) for e in [user("task"), tool("WebFetch"), result()]), encoding="utf-8")
    main = [user("q")]  # the main transcript shows no research; the subagent's does
    assert decide(tmp_path, main, "Report.", agent_transcript_path=str(sub), hook_event_name="SubagentStop") == "block"


@pytest.mark.parametrize("stdin", ["", "not json", json.dumps({"transcript_path": "/no/such/file.jsonl"})])
def test_fails_open(stdin):
    """Bad input or a missing transcript: print nothing, exit 0, so Claude finishes normally."""
    run = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True)
    assert (run.returncode, run.stdout) == (0, "")


def test_block_output_format(tmp_path):
    """The JSON Claude Code expects from a Stop hook: decision 'block' plus a reason, on stdout."""
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [user("q"), tool("WebSearch"), result()]), encoding="utf-8")
    data = {"transcript_path": str(path), "last_assistant_message": "Ans.", "stop_hook_active": False}
    run = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data), capture_output=True, text=True)
    out = json.loads(run.stdout)
    assert run.returncode == 0 and out["decision"] == "block" and "Sources:" in out["reason"]
