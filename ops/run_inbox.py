# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the checks another machine left for this one in ops/inbox.json.

    uv run ops/run_inbox.py            run pending tasks for this machine
    uv run ops/run_inbox.py --list     show them without running
    uv run ops/run_inbox.py --hook     quiet unless there's work (the post-merge hook uses this)
    uv run ops/run_inbox.py add --machine your PC --check eval --model gemma4:12b --why "..."
                                        add a task (validated here, before it's pushed)

A task names a machine, a check and a model tag. Only the checks in ALLOWED can run, each mapped to
a fixed `modelcheck.py` subcommand, and the tag is validated: the inbox can never hold an arbitrary
command, even though the hook runs it automatically after `git pull`.

Each result goes to ops/results/<task-id>.txt. A task with a result file is done, so it never runs
twice; delete the file to run it again. An eval run also writes its record to evals/runs/. A task
that exits with 75 ("try later", e.g. the GPU is busy with a game) gets no result file and runs again
on the next pull. Commit the results so the other machine can read them.
"""

from __future__ import annotations

import argparse
import json
import os
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
EVAL_RUN = ROOT / "evals" / "run.py"

ALLOWED = {"verify", "check", "tools", "answer", "embed", "eval"}  # modelcheck.py subcommands + the eval run
TAG = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)?(:[a-z0-9][a-z0-9._-]*)?$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
EXPECT = {"gpu", "cpu", "any"}
TIMEOUT = 20 * 60  # seconds; a cold load from a SATA drive can take a minute or two
EVAL_TIMEOUT = 3 * 60 * 60  # one model on the full set: ~5-30 s per item normally; each item is capped at 5 min
TRY_LATER = 75  # exit code for "not now" (evals/run.py EX_TEMPFAIL): leave the task pending


def this_machine() -> str:
    return socket.gethostname().split(".")[0].lower()


def load(inbox: Path | None = None) -> list[dict]:
    inbox = inbox or INBOX  # looked up at call time, so tests and callers can point elsewhere
    if not inbox.is_file():
        return []
    return json.loads(inbox.read_text(encoding="utf-8")).get("tasks", [])


def command(task: dict) -> list[str]:
    """The exact command for a task, or ValueError if the task isn't allowed."""
    tid, check, model = task.get("id", ""), task.get("check", ""), task.get("model", "")
    if not TASK_ID.match(tid):
        raise ValueError(f"bad task id {tid!r}")
    if check not in ALLOWED:
        raise ValueError(f"check {check!r} isn't allowed (allowed: {', '.join(sorted(ALLOWED))})")
    if not TAG.match(model):
        raise ValueError(f"bad model tag {model!r}")
    if check == "eval":
        if "expect" in task:
            raise ValueError("expect isn't allowed on eval tasks")
        # Answers and rule-check results come back through git in evals/runs/<run_id>.jsonl
        return [sys.executable, str(EVAL_RUN), "run", "--models", model, "--note", f"inbox {tid}"]
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
        limit = EVAL_TIMEOUT if task.get("check") == "eval" else TIMEOUT
        # The child prints UTF-8 and we decode it as UTF-8 (Windows defaults to cp1252 for both).
        env = {**os.environ, "PYTHONUTF8": "1"}
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=limit, check=False
        )
        code, output = proc.returncode, proc.stdout + proc.stderr
        shown = " ".join([Path(cmd[1]).name, *cmd[2:]])
    except ValueError as e:
        code, output, shown = 2, f"REFUSED  {e}\n", "(not run)"
    except subprocess.TimeoutExpired:
        code, output, shown = 3, f"TIMEOUT  after {limit}s\n", " ".join([Path(cmd[1]).name, *cmd[2:]])
    if code == TRY_LATER:
        print(f"  deferred: {task.get('id')} ({output.strip().splitlines()[-1] if output.strip() else 'try later'})")
        return code
    header = (
        f"task: {task.get('id')}\nmachine: {machine}\nwhen: {datetime.now().isoformat(timespec='seconds')}\n"
        f"why: {task.get('why', '')}\ncommand: {shown}\nexit: {code}\n\n"
    )
    (results / f"{task.get('id')}.txt").write_text(header + output, encoding="utf-8")
    return code


def add(machine: str, check: str, model: str, why: str, expect: str | None = None, inbox: Path | None = None) -> dict:
    """Append a task after validating it exactly as the receiving machine will, so a bad task fails here."""
    inbox = inbox or INBOX
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    task: dict = {
        "id": f"{datetime.now():%Y-%m-%d}-{machine.lower()}-{check}-{slug}"[:61].rstrip("-"),
        "machine": machine,
        "check": check,
        "model": model,
        "why": why,
    }
    if expect:
        task["expect"] = expect
    if not why.strip():
        raise ValueError("say why the task is needed (--why)")
    command(task)  # raises ValueError if the receiving machine would refuse it
    data = json.loads(inbox.read_text(encoding="utf-8")) if inbox.is_file() else {"tasks": []}
    if any(t.get("id") == task["id"] for t in data["tasks"]):
        raise ValueError(f"task {task['id']} already exists (delete its result file to rerun it)")
    data["tasks"].append(task)
    inbox.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return task


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["add"]:
        ap = argparse.ArgumentParser(prog="run_inbox.py add", description="Add a task for another machine.")
        ap.add_argument("--machine", required=True, help="hostname of the machine that should run it")
        ap.add_argument("--check", required=True, choices=sorted(ALLOWED))
        ap.add_argument("--model", required=True)
        ap.add_argument("--why", required=True)
        ap.add_argument("--expect", choices=sorted(EXPECT))
        opts = ap.parse_args(argv[1:])
        try:
            task = add(opts.machine, opts.check, opts.model, opts.why, opts.expect)
        except ValueError as e:
            print(f"REFUSED  {e}")
            return 2
        print(f"added {task['id']}. Commit and push ops/inbox.json; it runs on {opts.machine}'s next `git pull`.")
        return 0
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
        if code == TRY_LATER:
            continue
        failed += code != 0
        print(f"  {'done' if code == 0 else f'FAILED (exit {code})'}: {t.get('id')} -> ops/results/{t.get('id')}.txt")
    print("Commit and push ops/results/ and evals/runs/ so the other machine can read them.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
