# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Session-start briefing: what an agent (or a person) needs before touching anything.

    uv run ops/session.py

Prints the machine, the branch and whether it's in step with GitHub, uncommitted changes, the
current step and next steps from STATUS.md, inbox tasks waiting for this machine, open notes from
the planning chat (ops/chat-inbox/to-code/), shared-tool copies that drifted, and eval runs in
git that this machine's results database hasn't loaded yet. Claude Code runs it at session start
(.claude/settings.json), so the "start any session" prompt isn't needed. Read-only apart from a
`git fetch`; never fails the session (problems are printed, exit code is always 0).
"""

from __future__ import annotations

import contextlib
import json
import platform
import re
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str, timeout: float = 15) -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def machine() -> str:
    role = {"Windows": "the PC (home node)", "Darwin": "the Mac (edge device)"}.get(platform.system(), "unknown role")
    return f"{socket.gethostname().split('.')[0]}: {role}"


def sync_state() -> str:
    git("fetch", "--quiet", timeout=20)  # best effort: offline just means the numbers may be stale
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    counts = git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if not counts:
        return f"{branch} (no upstream to compare with)"
    ahead, behind = counts.split()
    state = "in step with GitHub" if ahead == behind == "0" else f"{ahead} ahead, {behind} behind GitHub"
    changed = len([ln for ln in git("status", "--porcelain").splitlines() if ln])
    return f"{branch}, {state}" + (f", {changed} uncommitted change(s)" if changed else "")


def status_sections(text: str, names: tuple[str, ...] = ("Current step", "Next steps")) -> str:
    """The named `## ` sections of STATUS.md, verbatim."""
    out = []
    for name in names:
        m = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
        if m:
            out.append(f"## {name}\n{m.group(1).strip()}")
    return "\n\n".join(out)


def inbox_waiting(host: str) -> list[str]:
    try:
        tasks = json.loads((ROOT / "ops" / "inbox.json").read_text(encoding="utf-8")).get("tasks", [])
    except (OSError, ValueError):
        return []
    results = ROOT / "ops" / "results"
    return [
        f"{t.get('id')}: {t.get('check')} {t.get('model')}"
        for t in tasks
        if str(t.get("machine", "")).lower() == host and not (results / f"{t.get('id')}.txt").exists()
    ]


def chat_notes() -> list[str]:
    """Open notes the planning chat left for coding agents (ops/chat-inbox/to-code/)."""
    out = []
    for path in sorted((ROOT / "ops" / "chat-inbox" / "to-code").glob("*.md")):
        try:
            head = path.read_text(encoding="utf-8").split("\n---\n", 1)[0]
        except OSError:
            continue
        topic = next((ln.split(":", 1)[1].strip() for ln in head.splitlines() if ln.startswith("topic:")), "?")
        out.append(f"{path.stem}: {topic}")
    return out


def runs_not_loaded() -> int:
    """Run records in git (evals/runs/) missing from this machine's results database."""
    db, runs = ROOT / "evals" / "results.db", ROOT / "evals" / "runs"
    files = {p.stem for p in runs.glob("*.jsonl")}
    if not files or not db.exists():
        return len(files)
    try:
        with contextlib.closing(sqlite3.connect(db)) as con:
            have = {r[0] for r in con.execute("SELECT run_id FROM runs")}
    except sqlite3.Error:
        return len(files)
    return len(files - have)


def shared_drift() -> list[str]:
    """Warn (never fail) when copies of shared tools in sibling repos drifted from this repo's source."""
    try:
        r = subprocess.run(
            [sys.executable, "-I", str(ROOT / "tools" / "sync_shared.py"), "--check"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    drift = [line for line in r.stdout.splitlines() if line.startswith("DRIFT")]
    return [f"Shared tools: {len(drift)} copy(ies) drifted (uv run tools/sync_shared.py --check)"] if drift else []


def main() -> int:
    host = socket.gethostname().split(".")[0].lower()
    lines = [f"Machine: {machine()}", f"Branch: {sync_state()}"]
    waiting = inbox_waiting(host)
    if waiting:
        lines.append(f"Inbox: {len(waiting)} task(s) for this machine (run: uv run ops/run_inbox.py)")
        lines += [f"  {w}" for w in waiting]
    notes = chat_notes()
    if notes:
        lines.append(f"Chat inbox: {len(notes)} note(s) from the planning chat (uv run ops/chat_inbox.py show <id>)")
        lines += [f"  {n}" for n in notes]
    lines += shared_drift()
    missing = runs_not_loaded()
    if missing:
        lines.append(f"Eval runs in git not in this machine's database: {missing} (run: uv run evals/run.py sync)")
    try:
        lines += ["", status_sections((ROOT / "STATUS.md").read_text(encoding="utf-8"))]
    except OSError:
        lines.append("STATUS.md not found")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
