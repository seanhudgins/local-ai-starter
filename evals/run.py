"""Eval runner: send every item to local models, score with rule checks, judge with Claude, report.

    uv run evals/run.py run --models gemma4:26b-mlx qwen3.6:27b-mlx [--items redact- intent-001] [--note "..."]
    uv run evals/run.py export --run RUN_ID            judgment items -> evals/judging/RUN_ID.jsonl
    uv run evals/run.py import --run RUN_ID FILE       scores back from a graded file
    (next) judge --run RUN_ID --max-usd 5              grade with Claude via the API (the recorded run)
    uv run evals/run.py rescore --run RUN_ID           re-apply current rule checks to stored answers
    uv run evals/run.py load FILE                      load a run another machine wrote with --out
    uv run evals/run.py report [--run RUN_ID]          per-model results, from SQL

Every result is stamped with the machine, Ollama version and model digest, and stored in SQLite
(evals/results.db). Test runs are judged in chat (`export` / `import`, judge="chat"); the run that
goes in the README is judged through the API (judge="claude-opus-5-5").
"""

from __future__ import annotations

import argparse
import contextlib
import json
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "ollama"))
sys.path.insert(0, str(ROOT / "evals"))

import checks  # noqa: E402
import modelcheck  # noqa: E402

DEFAULT_SET = ROOT / "evals" / "sets" / "contact-center.jsonl"
DEFAULT_DB = ROOT / "evals" / "results.db"
JUDGING = ROOT / "evals" / "judging"
OLLAMA = modelcheck.DEFAULT_URL

SYSTEM = (
    "You are an assistant for a contact center. Follow the instructions exactly and reply with only what they ask for."
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started TEXT, machine TEXT, ollama_version TEXT, eval_set TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS results (
    run_id TEXT, item_id TEXT, model TEXT, model_digest TEXT, task_type TEXT, industry TEXT,
    answer TEXT, error TEXT, latency_s REAL, completion_tokens INTEGER,
    rules_passed INTEGER, rules_total INTEGER, rule_details TEXT,
    judge TEXT, judge_score INTEGER, judge_reason TEXT,
    PRIMARY KEY (run_id, item_id, model)
);
"""


# ---------- data ----------


def load_items(path: Path = DEFAULT_SET, only: list[str] | None = None) -> list[dict]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if only:
        items = [i for i in items if any(i["id"].startswith(prefix) for prefix in only)]
    return items


def connect(db: Path = DEFAULT_DB) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA_SQL)
    return con


def build_prompt(item: dict) -> list[dict]:
    """The messages a model sees: fixed system line, the instructions, the schema if any, then the input."""
    parts = [item["instructions"]]
    if item.get("output_schema"):
        parts.append("JSON schema:\n" + json.dumps(item["output_schema"], indent=2))
    parts.append("Input:\n" + item["input"])
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]


# ---------- run ----------
#
# Safety rails (added 2026-11-05 after an uncapped run froze the Mac): every answer is capped
# (num_predict), the context is fixed (num_ctx), each item has a time limit, the runner stops cleanly
# when macOS memory gets low, and each model is unloaded when its turn ends.

MAX_TOKENS = 8192  # answer + thinking; hitting it is scored as a failure (redact-001 used 3,988 thinking)
CONTEXT = 16384  # the longest item plus a capped answer fits comfortably
ITEM_SECONDS = 300
MIN_FREE_PCT = 25  # stop if macOS reports less free memory than this
RELOAD_FREE_PCT = 40  # below this, unload and reload the model: Ollama's MLX runner keeps memory
# from every request (17 -> 24 GB over one 24-item run, 2026-11-05), so long runs reset it


def free_memory_pct() -> int | None:
    """macOS's own free-memory reading (0-100); None elsewhere."""
    try:
        out = subprocess.run(["sysctl", "-n", "kern.memorystatus_level"], capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


class LowMemory(RuntimeError):
    pass


def ask(model: str, item: dict, url: str = OLLAMA, memory=free_memory_pct) -> tuple[str, str, float, int]:
    """(answer, error, seconds, tokens) for one item, streamed so it can be stopped mid-answer.

    Raises LowMemory when free memory drops below MIN_FREE_PCT; any other failure is returned as an
    error string so one bad item doesn't stop the run.
    """
    body = {
        "model": model,
        "messages": build_prompt(item),
        "stream": True,
        "options": {"temperature": 0, "num_predict": MAX_TOKENS, "num_ctx": CONTEXT},
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    start, parts, tokens, done_reason = time.monotonic(), [], 0, ""
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            for n, line in enumerate(resp):
                chunk = json.loads(line)
                parts.append((chunk.get("message") or {}).get("content") or "")
                if chunk.get("done"):
                    tokens, done_reason = chunk.get("eval_count") or 0, chunk.get("done_reason", "")
                    break
                if n % 50 == 0:  # check about every 50 tokens; closing the stream stops the model
                    free = memory()
                    if free is not None and free < MIN_FREE_PCT:
                        raise LowMemory(f"free memory {free}% < {MIN_FREE_PCT}%")
                if time.monotonic() - start > ITEM_SECONDS:
                    return "".join(parts).strip(), f"time limit {ITEM_SECONDS}s", time.monotonic() - start, n
    except LowMemory:
        raise
    except Exception as e:
        return "".join(parts).strip(), f"{type(e).__name__}: {e}", time.monotonic() - start, tokens
    error = f"hit the {MAX_TOKENS}-token cap" if done_reason == "length" else ""
    return "".join(parts).strip(), error, time.monotonic() - start, tokens


def unload(model: str, url: str = OLLAMA) -> None:
    """Free the model's memory now instead of after Ollama's 5-minute keep-alive."""
    with contextlib.suppress(Exception):
        modelcheck.call(url, "/api/generate", {"model": model, "keep_alive": 0}, timeout=60)


def run(
    models: list[str],
    items: list[dict],
    con: sqlite3.Connection,
    url: str = OLLAMA,
    note: str = "",
    asker=ask,
    memory=free_memory_pct,
) -> str:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    version = modelcheck.call(url, "/api/version").get("version", "")
    con.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
        (
            run_id,
            datetime.now().isoformat(timespec="seconds"),
            socket.gethostname().split(".")[0],
            version,
            DEFAULT_SET.name,
            note,
        ),
    )
    con.commit()
    try:
        for model in models:
            digest = modelcheck.identity(url, model)["model_digest"]
            try:
                for n, item in enumerate(items, 1):
                    free = memory()
                    if free is not None and free < RELOAD_FREE_PCT:
                        print(f"  (free memory {free}%: reloading {model} to release Ollama's cache)", flush=True)
                        unload(model, url)
                        time.sleep(3)
                        free = memory()
                    if free is not None and free < MIN_FREE_PCT:
                        raise LowMemory(f"free memory {free}% < {MIN_FREE_PCT}% before {item['id']}")
                    answer, error, secs, tokens = asker(model, item, url)
                    results = checks.run_checks(item, answer) if not error else []
                    passed = sum(r.ok for r in results)
                    con.execute(
                        "INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            run_id,
                            item["id"],
                            model,
                            digest,
                            item["task_type"],
                            item["industry"],
                            answer,
                            error,
                            round(secs, 2),
                            tokens,
                            passed,
                            len(item["checks"]),
                            json.dumps([r.__dict__ for r in results]),
                            None,
                            None,
                            None,
                        ),
                    )
                    con.commit()
                    mark = "ERROR" if error else f"{passed}/{len(item['checks'])}"
                    free_now = memory()
                    print(
                        f"  {model:32s} {n:2d}/{len(items)} {item['id']:13s} {mark:6s} {secs:5.1f}s "
                        f"{tokens:5d} tok  mem free {free_now if free_now is not None else '?'}%",
                        flush=True,
                    )
            finally:
                unload(model, url)
    except LowMemory as e:
        print(f"\nSTOPPED to protect the Mac: {e}. Results so far are saved; close other apps and re-run.")
    return run_id


def rescore(con: sqlite3.Connection, run_id: str, items: dict[str, dict]) -> int:
    """Re-apply the current rule checks to a run's stored answers (after fixing a check or an item)."""
    n = 0
    for row in con.execute(
        "SELECT item_id, model, answer FROM results WHERE run_id=? AND error=''", (run_id,)
    ).fetchall():
        item = items.get(row["item_id"])
        if item is None:
            continue
        results = checks.run_checks(item, row["answer"])
        con.execute(
            "UPDATE results SET rules_passed=?, rules_total=?, rule_details=? WHERE run_id=? AND item_id=? AND model=?",
            (
                sum(r.ok for r in results),
                len(item["checks"]),
                json.dumps([r.__dict__ for r in results]),
                run_id,
                row["item_id"],
                row["model"],
            ),
        )
        n += 1
    con.commit()
    return n


def dump(con: sqlite3.Connection, run_id: str, path: Path) -> int:
    """Write a run (its runs row + every result) as JSONL, so another machine can load it."""
    meta = dict(con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())
    rows = [dict(r) for r in con.execute("SELECT * FROM results WHERE run_id=? ORDER BY rowid", (run_id,))]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps({"type": k, **v}, ensure_ascii=False) + "\n"
            for k, v in [("run", meta), *[("result", x) for x in rows]]
        ),
        encoding="utf-8",
    )
    return len(rows)


def load(con: sqlite3.Connection, path: Path) -> tuple[str, int]:
    """Load a run written by dump() (e.g. from your PC via the inbox). Already-loaded runs are skipped."""
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    meta = next(x for x in lines if x["type"] == "run")
    if con.execute("SELECT 1 FROM runs WHERE run_id=?", (meta["run_id"],)).fetchone():
        return meta["run_id"], 0
    cols = ["run_id", "started", "machine", "ollama_version", "eval_set", "note"]
    con.execute(f"INSERT INTO runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [meta[c] for c in cols])
    n = 0
    for x in (x for x in lines if x["type"] == "result"):
        x = {k: v for k, v in x.items() if k != "type"}
        con.execute(f"INSERT INTO results ({', '.join(x)}) VALUES ({', '.join('?' * len(x))})", list(x.values()))
        n += 1
    con.commit()
    return meta["run_id"], n


# ---------- judging ----------


def to_judge(con: sqlite3.Connection, run_id: str, items: dict[str, dict]) -> list[dict]:
    rows = con.execute(
        "SELECT item_id, model, answer FROM results WHERE run_id=? AND judge_score IS NULL "
        "AND error='' ORDER BY item_id, model",
        (run_id,),
    ).fetchall()
    return [
        {
            "run_id": run_id,
            "item_id": r["item_id"],
            "model": r["model"],
            "instructions": items[r["item_id"]]["instructions"],
            "input": items[r["item_id"]]["input"],
            "rubric": items[r["item_id"]]["grader"]["rubric"],
            "answer": r["answer"],
        }
        for r in rows
        if items.get(r["item_id"], {}).get("grader")
    ]


def export(con: sqlite3.Connection, run_id: str, items: dict[str, dict], out_dir: Path = JUDGING) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_id}.jsonl"
    path.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in to_judge(con, run_id, items)), encoding="utf-8"
    )
    return path


def import_grades(con: sqlite3.Connection, path: Path, judge: str = "chat") -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        score = int(g["score"])
        if not 1 <= score <= 5:
            raise ValueError(f"score {score} for {g['item_id']}/{g['model']} isn't 1-5")
        n += con.execute(
            "UPDATE results SET judge=?, judge_score=?, judge_reason=? WHERE run_id=? AND item_id=? AND model=?",
            (judge, score, g.get("reason", ""), g["run_id"], g["item_id"], g["model"]),
        ).rowcount
    con.commit()
    return n


# ---------- report ----------

REPORT_SQL = """
SELECT model,
       COUNT(*)                                               AS items,
       SUM(rules_passed = rules_total AND error = '')         AS all_rules_pass,
       ROUND(100.0 * SUM(rules_passed) / SUM(rules_total), 1) AS rule_pct,
       ROUND(AVG(judge_score), 2)                             AS judge_avg,
       COUNT(judge_score)                                     AS judged,
       ROUND(AVG(latency_s), 1)                               AS avg_s,
       SUM(error != '')                                       AS errors
FROM results WHERE run_id = ? GROUP BY model ORDER BY rule_pct DESC, judge_avg DESC
"""

BY_TASK_SQL = """
SELECT model, task_type, ROUND(100.0 * SUM(rules_passed) / SUM(rules_total)) AS rule_pct
FROM results WHERE run_id = ? GROUP BY model, task_type ORDER BY model, task_type
"""


def report(con: sqlite3.Connection, run_id: str | None = None) -> str:
    if run_id is None:
        row = con.execute("SELECT run_id FROM runs ORDER BY started DESC LIMIT 1").fetchone()
        if row is None:
            return "No runs yet."
        run_id = row["run_id"]
    meta = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    judges = sorted(
        {r["judge"] for r in con.execute("SELECT DISTINCT judge FROM results WHERE run_id=?", (run_id,)) if r["judge"]}
    )
    lines = [
        f"Run {run_id} on {meta['machine']}, Ollama {meta['ollama_version']}, judge: {', '.join(judges) or 'none yet'}"
        + (f" ({meta['note']})" if meta["note"] else ""),
        "",
        "| Model | Items | All rules pass | Rule checks % | Judge avg (1-5) | Judged | Avg s | Errors |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in con.execute(REPORT_SQL, (run_id,)):
        lines.append(
            f"| `{r['model']}` | {r['items']} | {r['all_rules_pass']} | {r['rule_pct']} | "
            f"{r['judge_avg'] if r['judge_avg'] is not None else '-'} | {r['judged']} | {r['avg_s']} | "
            f"{r['errors']} |"
        )
    by_task: dict[str, dict[str, float]] = {}
    for r in con.execute(BY_TASK_SQL, (run_id,)):
        by_task.setdefault(r["model"], {})[r["task_type"]] = r["rule_pct"]
    if by_task:
        tasks = sorted({t for v in by_task.values() for t in v})
        lines += ["", "| Model | " + " | ".join(tasks) + " |", "|---|" + "---|" * len(tasks)]
        lines += [f"| `{m}` | " + " | ".join(f"{v.get(t, '-'):.0f}" for t in tasks) + " |" for m, v in by_task.items()]
    return "\n".join(lines)


# ---------- command line ----------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--items", nargs="*", help="id prefixes, e.g. redact- intent-001")
    r.add_argument("--url", default=OLLAMA)
    r.add_argument("--note", default="")
    r.add_argument("--out", type=Path, help="also write the run as JSONL (how inbox runs come back)")
    ld = sub.add_parser("load")
    ld.add_argument("file", type=Path)
    e = sub.add_parser("export")
    e.add_argument("--run", required=True)
    i = sub.add_parser("import")
    i.add_argument("--run", required=True)
    i.add_argument("file", type=Path)
    rs = sub.add_parser("rescore")
    rs.add_argument("--run", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--run")
    a = p.parse_args(argv)

    con = connect(a.db)
    items = {it["id"]: it for it in load_items()}
    if a.cmd == "run":
        chosen = load_items(only=a.items)
        print(f"{len(chosen)} items x {len(a.models)} model(s)")
        if free_memory_pct() is None:
            print("NOTE  memory watchdog not available on this OS; the answer cap and fixed context still apply")
        run_id = run(a.models, chosen, con, a.url, a.note)
        if a.out:
            print(f"{dump(con, run_id, a.out)} results written to {a.out}")
        print(f"\nrun {run_id}\n")
        print(report(con, run_id))
    elif a.cmd == "export":
        path = export(con, a.run, items)
        print(f"{sum(1 for _ in path.open(encoding='utf-8'))} answers to judge -> {path.relative_to(ROOT)}")
    elif a.cmd == "load":
        run_id, n = load(con, a.file)
        print(f"run {run_id}: {n} results loaded" if n else f"run {run_id} was already loaded")
    elif a.cmd == "rescore":
        print(f"{rescore(con, a.run, items)} answers rescored")
    elif a.cmd == "import":
        print(f"{import_grades(con, a.file)} scores imported")
    else:
        print(report(con, a.run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
