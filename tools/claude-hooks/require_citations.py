#!/usr/bin/env python3
"""Claude Code Stop / SubagentStop hook: a reply that used research must end with sources.

Plain English: when Claude is about to finish a reply, Claude Code runs this script and passes it a
little JSON about the turn. The script looks at which tools Claude used since your last message. If
it searched the web, fetched a page, used a search-type MCP tool, or relied on a helper agent whose
report contains web links, the reply must have a "Sources:" section with at least one link or file
path. If it doesn't, the script tells Claude to add one.

Safety: it asks at most once per reply (`stop_hook_active`), and if anything goes wrong it lets
Claude finish normally. Standard library only, so it runs anywhere Python 3.10+ does.

Install (both machines): copy to ~/.claude/hooks/ and add to ~/.claude/settings.json:
    "Stop" and "SubagentStop": command
    uv run --quiet --no-project "$HOME/.claude/hooks/require_citations.py"
($HOME works in macOS sh, Git Bash and PowerShell, which is where Claude Code runs hooks.)
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable

RESEARCH_TOOLS = {"WebSearch", "WebFetch"}
# MCP tools count only if their name looks like web research (e.g. mcp__brave__web_search).
RESEARCH_MCP = re.compile(r"search|fetch|browse|scrape|crawl|read_url|web", re.I)
HELPER_TOOLS = {"Agent", "Task"}  # helper agents: count when their report contains web links
URL = re.compile(r"https?://\S+")

# "Sources:" / "**Sources:**" / "## Sources" / "Source: ..." but not "Sources are mixed" or "Source code".
SOURCES_HEADING = re.compile(r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?[*_]{0,2}sources?[*_]{0,2}(?:[ \t]*:|[ \t]*$)")
LINK_OR_PATH = re.compile(
    r"https?://\S+|\[[^\]]+\]\([^)]+\)|(?:^|\s)[\w./\\-]+\.(?:md|pdf|txt|docx|csv|json|jsonl|py|ts|html)\b", re.I
)

REASON = (
    "You used research tools this turn but your reply has no 'Sources:' section. Add one at the end "
    "listing every source you relied on as [Title](URL) or a file path. Only list sources you used."
)


def is_research_tool(name: str) -> bool:
    return name in RESEARCH_TOOLS or (name.startswith("mcp__") and bool(RESEARCH_MCP.search(name)))


def read_jsonl(path: str) -> list[dict]:
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _blocks(entry: dict) -> list:
    content = (entry.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def is_user_prompt(entry: dict) -> bool:
    """A message from the person: typed text, a pasted document or an image. Not a tool result,
    and not text Claude Code injects itself (skills, reminders: marked isMeta)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    kinds = {b.get("type") for b in _blocks(entry) if isinstance(b, dict)}
    return bool(kinds) and "tool_result" not in kinds


def current_turn(entries: list[dict]) -> list[dict]:
    start = 0
    for i, entry in enumerate(entries):
        if is_user_prompt(entry):
            start = i + 1
    return entries[start:]


def _text_of(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text_of(v.get("text", "")) if isinstance(v, dict) else _text_of(v) for v in value)
    return ""


def scan(turn: Iterable[dict]) -> tuple[bool, str]:
    """(used research?, last assistant text) for one turn."""
    used, final_text, helpers = False, "", set()
    for entry in turn:
        for block in _blocks(entry):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if entry.get("type") == "assistant" and kind == "tool_use":
                name = block.get("name", "")
                if is_research_tool(name):
                    used = True
                elif name in HELPER_TOOLS:
                    helpers.add(block.get("id"))
            elif entry.get("type") == "assistant" and kind == "text":
                final_text = block.get("text", "")
            elif kind == "tool_result" and block.get("tool_use_id") in helpers:
                used = used or bool(URL.search(_text_of(block.get("content"))))
    return used, final_text


def has_sources(text: str) -> bool:
    headings = list(SOURCES_HEADING.finditer(text))
    return bool(headings) and bool(LINK_OR_PATH.search(text[headings[-1].start() :]))


def decide(data: dict) -> dict | None:
    """The hook's JSON reply, or None to let Claude finish."""
    if data.get("stop_hook_active"):
        return None
    path = data.get("agent_transcript_path") or data.get("transcript_path")  # subagent: its own transcript
    if not path:
        return None
    entries = read_jsonl(path)
    used, final_text = scan(entries if data.get("agent_transcript_path") else current_turn(entries))
    last = data.get("last_assistant_message")
    final_text = last if isinstance(last, str) and last else final_text
    if not used or has_sources(final_text):
        return None
    return {"decision": "block", "reason": REASON}


def main() -> None:
    try:
        reply = decide(json.load(sys.stdin))
    except Exception:  # never stop Claude because the hook itself failed
        reply = None
    if reply:
        print(json.dumps(reply))


if __name__ == "__main__":
    main()
