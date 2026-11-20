# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Notes between planning chats (Claude on claude.ai) and coding agents (Claude Code) in this repo.

    uv run <path>/chat_inbox.py                 list open notes for coding agents (to-code/)
    uv run <path>/chat_inbox.py --for chat      list open notes for the planning chat (to-chat/)
    uv run <path>/chat_inbox.py show ID         print one note
    uv run <path>/chat_inbox.py add --to chat --topic "..." [--plan-doc X] [--body "..."]
    uv run <path>/chat_inbox.py done ID         close a note (moves it to done/ with today's date)
    (python3 works too: standard library only)

<path> is ops/ in local-ai and chat-inbox/ in the other private repos. One file, copied: local-ai's
ops/chat_inbox.py is the source; `uv run tools/sync_shared.py --check` finds copies that drifted.

Every note names its repo (`repo: homelab`). A note filed in the wrong repo is flagged when listed, so it
can be moved; the routing table is in local-ai docs/AI-SETUP.md section 4.

The machine inbox (local-ai ops/inbox.json) runs predefined checks automatically. This one never runs
anything: a note is plain text for the reader to weigh. Coding agents treat a to-code note as a
proposal from the owner's planning chat, still bound by the repo's AGENTS.md / CLAUDE.md and spec, and ask
the owner before acting on one that conflicts with them, deletes things, changes security rules or spends
money. Notes never change AGENTS.md or CLAUDE.md (hand-edit only). Private repos only (excluded from any
public copy).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# local-ai keeps the script in ops/ next to ops/chat-inbox/; the other repos keep it inside chat-inbox/.
BOX = _HERE if _HERE.name == "chat-inbox" else _HERE / "chat-inbox"
ROOT = BOX.parent.parent if BOX.parent.name == "ops" else BOX.parent


def repo_name(root: Path = ROOT) -> str:
    """The GitHub repo name from the origin URL (a clone can live in any folder); the folder name if no origin."""
    r = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True, text=True)
    url = r.stdout.strip().rstrip("/")
    if r.returncode == 0 and url:
        return url.rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git")
    return root.name


REPO = repo_name()  # local-ai, homelab, patient-access-agent-private
SIDES = {"code": "to-code", "chat": "to-chat"}
NOTE_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,59}$")  # slug (50) + "-N" suffix
FIELDS = ("id", "from", "to", "repo", "date", "topic", "plan_docs")


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:50].strip("-") or "note"


def parse(text: str) -> dict[str, str]:
    """Header fields of a note (the block between the first two `---` lines)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def open_notes(side: str, box: Path | None = None) -> list[tuple[Path, dict[str, str]]]:
    folder = (box or BOX) / SIDES[side]
    notes = []
    for path in sorted(folder.glob("*.md")):
        notes.append((path, parse(path.read_text(encoding="utf-8"))))
    return notes


def find(note_id: str, box: Path | None = None) -> Path:
    if not NOTE_ID.match(note_id):
        raise ValueError(f"bad note id {note_id!r}")
    for side in SIDES.values():
        path = (box or BOX) / side / f"{note_id}.md"
        if path.is_file():
            return path
    raise FileNotFoundError(f"no open note {note_id!r}")


def misfiled(header: dict[str, str], repo: str = "") -> str:
    """The repo a note names when it isn't this one ("" when it's here, or an older note with no repo line)."""
    named = header.get("repo", "").strip()
    return named if named and named != (repo or REPO) else ""


def render(note_id: str, sender: str, to: str, day: str, topic: str, plan_docs: str, body: str, repo: str = "") -> str:
    topic = " ".join(topic.split())  # one line: keeps the header parseable
    plan_docs = " ".join(plan_docs.split()) or "none"
    header = (
        f"---\nid: {note_id}\nfrom: {sender}\nto: {to}\nrepo: {repo or REPO}\ndate: {day}\n"
        f"topic: {topic}\nplan_docs: {plan_docs}\n---\n"
    )
    body = body.strip() or "## What to do\n-\n\n## Why\n-\n\n## How to verify\n-"
    return header + "\n" + body + "\n"


def add(to: str, topic: str, plan_docs: str = "", body: str = "", box: Path | None = None, today: str = "") -> Path:
    if to not in SIDES:
        raise ValueError(f"--to must be one of {', '.join(SIDES)}")
    if not topic.strip():
        raise ValueError("topic is required")
    day = today or date.today().isoformat()
    sender = "chat" if to == "code" else "code"
    base = f"{day}-{slug(topic)}"
    folder = (box or BOX) / SIDES[to]
    folder.mkdir(parents=True, exist_ok=True)
    note_id, n = base, 2
    while any(((box or BOX) / d / f"{note_id}.md").exists() for d in (*SIDES.values(), "done")):
        note_id, n = f"{base}-{n}", n + 1
    path = folder / f"{note_id}.md"
    path.write_text(render(note_id, sender, to, day, topic, plan_docs, body), encoding="utf-8", newline="\n")
    return path


def done(note_id: str, box: Path | None = None, today: str = "") -> Path:
    src = find(note_id, box)
    text = src.read_text(encoding="utf-8")
    closed = today or date.today().isoformat()
    text = text.replace("\n---\n", f"\nclosed: {closed}\n---\n", 1)
    dest = (box or BOX) / "done" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    src.unlink()
    return dest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--for", dest="side", choices=sorted(SIDES), default="code", help="whose notes to list")
    p.add_argument("--check", action="store_true", help="exit 1 if an open note (either side) names another repo")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("show")
    s.add_argument("id")
    a = sub.add_parser("add")
    a.add_argument("--to", required=True, choices=sorted(SIDES))
    a.add_argument("--topic", required=True)
    a.add_argument("--plan-doc", default="", help="plan doc(s) this note relates to")
    a.add_argument("--body", default="", help="note text (markdown); default is the empty template")
    d = sub.add_parser("done")
    d.add_argument("id")
    args = p.parse_args(argv)
    if args.check:
        bad = [(path, h) for side in SIDES for path, h in open_notes(side) if misfiled(h)]
        for path, h in bad:
            print(f"misfiled: {path.relative_to(ROOT).as_posix()} names repo {misfiled(h)!r}, this is {REPO!r}")
        return 1 if bad else 0
    try:
        if args.cmd == "show":
            print(find(args.id).read_text(encoding="utf-8"))
        elif args.cmd == "add":
            path = add(args.to, args.topic, args.plan_doc, args.body)
            print(f"Wrote {path.relative_to(ROOT).as_posix()}. Commit and push it.")
        elif args.cmd == "done":
            print(f"Closed: {done(args.id).relative_to(ROOT).as_posix()}. Commit and push it.")
        else:
            notes = open_notes(args.side)
            if not notes:
                print(f"No open notes in {SIDES[args.side]}/.")
            for _, h in notes:
                plan = h.get("plan_docs", "-")
                print(f"{h.get('id', '?')}  [{h.get('date', '?')}]  {h.get('topic', '?')}  (plan: {plan})")
                other = misfiled(h)
                if other:
                    print(f"  ^ filed here but addressed to repo {other!r}: move it there (git mv), then commit")
    except (ValueError, FileNotFoundError) as e:
        print(f"chat_inbox: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
