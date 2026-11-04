# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the checks another machine left for this one in ops/inbox.json.

    uv run ops/run_inbox.py            run pending tasks for this machine
    uv run ops/run_inbox.py --list     show them without running
    uv run ops/run_inbox.py --hook     quiet unless there's work (the post-merge hook uses this)

A task names a machine, a check and a model tag. Only the checks in ALLOWED can run, each mapped to
a fixed `modelcheck.py` subcommand, and the tag is validated: the inbox can never hold an arbitrary
command, even though the hook runs it automatically after `git pull`.

Each result goes to ops/results/<task-id>.txt. A task with a result file is done, so it never runs
twice; delete the file to run it again. Commit the results so the other machine can read them.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "ops" / "inbox.json"
RESULTS = ROOT / "ops" / "results"
MODELCHECK = ROOT / "services" / "ollama" / "modelcheck.py"

ALLOWED = {"verify", "check", "tools", "answer", "embed"}  # modelcheck.py subcommands
TAG = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)?(:[a-z0-9][a-z0-9._-]*)?$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
EXPECT = {"gpu", "cpu", "any"}
TIMEOUT = 20 * 60  # seconds; a cold load from a SATA drive can take a minute or two


def this_machine() -> str:
    return socket.gethostname().split(".")[0].lower()


def load(inbox: Path | None = None) -> list[dict]:
    inbox = inbox or INBOX  # looked up at call time, so tests and callers can point elsewhere
    if not inbox.is_file():
        return []
    return json.loads(inbox.read_text()).get("tasks", [])


def command(task: dict) -> list[str]:
    """The exact command for a task, or ValueError if the task isn't allowed."""
    tid, check, model = task.get("id", ""), task.get("check", ""), task.get("model", "")
    if not TASK_ID.match(tid):
        raise ValueError(f"bad task id {tid!r}")
    if check not in ALLOWED:
        raise ValueError(f"check {check!r} isn't allowed (allowed: {', '.join(sorted(ALLOWED))})")
    if not TAG.match(model):
        raise ValueError(f"bad model tag {model!r}")
    cmd = [sys.executable, str(MODELCHECK), check, model]
    if "expect" in task:
        if check != "check" or task["expect"] not in EXPECT:
            raise ValueError(f"bad expect {task['expect']!r}")
        cmd += ["--expect", task["expect"]]
    return cmd


def pending(tasks: list[dict], machine: str, results: Path | None = None) -> list[dict]:
    results = results or RESULTS
    return [
        t
        for t in tasks
        if str(t.get("machine", "")).lower() == machine and not (results / f"{t.get('id')}.txt").exists()
    ]


def run(task: dict, machine: str, results: Path | None = None) -> int:
    results = results or RESULTS
    results.mkdir(parents=True, exist_ok=True)
    try:
        cmd = command(task)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
        code, output = proc.returncode, proc.stdout + proc.stderr
        shown = " ".join(["modelcheck.py", *cmd[2:]])
    except ValueError as e:
        code, output, shown = 2, f"REFUSED  {e}\n", "(not run)"
    except subprocess.TimeoutExpired:
        code, output, shown = 3, f"TIMEOUT  after {TIMEOUT}s\n", " ".join(["modelcheck.py", *cmd[2:]])
    header = (
        f"task: {task.get('id')}\nmachine: {machine}\nwhen: {datetime.now().isoformat(timespec='seconds')}\n"
        f"why: {task.get('why', '')}\ncommand: {shown}\nexit: {code}\n\n"
    )
    (results / f"{task.get('id')}.txt").write_text(header + output)
    return code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--list", action="store_true", help="show pending tasks without running them")
    p.add_argument("--hook", action="store_true", help="quiet unless there's work")
    a = p.parse_args(argv)

    machine = this_machine()
    todo = pending(load(), machine)
    if not todo:
        if not a.hook:
            print(f"No pending tasks for {machine}.")
        return 0
    print(f"{len(todo)} pending task(s) for {machine} from ops/inbox.json:")
    for t in todo:
        print(f"  {t.get('id')}: {t.get('check')} {t.get('model')}  ({t.get('why', '')})")
    if a.list:
        return 0
    failed = 0
    for t in todo:
        code = run(t, machine)
        failed += code != 0
        print(f"  {'done' if code == 0 else f'FAILED (exit {code})'}: {t.get('id')} -> ops/results/{t.get('id')}.txt")
    print("Commit and push ops/results/ so the other machine can read them.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
