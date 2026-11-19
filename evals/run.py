"""Eval runner: send every item to local models, score with rule checks, judge with Claude, report.

    uv run evals/run.py run --models gemma4:26b-mlx qwen3.6:27b-mlx [--items redact- intent-001] [--note "..."]
    uv run evals/run.py export --run RUN_ID            judgment items -> evals/judging/RUN_ID.jsonl
    uv run evals/run.py import --run RUN_ID FILE       scores back from a graded file
    uv run evals/run.py judge --run RUN_ID --max-usd 2 [--limit 5]   grade with Claude via the API
    uv run evals/run.py rescore --run RUN_ID           re-apply current rule checks to stored answers
    uv run evals/run.py load FILE                      load one run file
    uv run evals/run.py sync                           load run files from git that aren't in the database yet
    uv run evals/run.py rebuild                        recreate the database from evals/runs/ (it's a cache)
    uv run evals/run.py report [--run RUN_ID]          per-model results, from SQL
    uv run evals/run.py compare --a RUN[:MODEL] --b RUN[:MODEL]   the model-origin rule, per task type

Every result is stamped with the machine, Ollama version, model digest and a fingerprint of the
item it answered, and stored in SQLite (evals/results.db). The record of each run is a JSONL file in
evals/runs/ (committed to git, rewritten after judging); the database is a local cache of those
files. Runs are judged through the API (`judge`, evals/judge.py; model and prices in
router/judge.json). `export` / `import` (judge="chat") remain for grading by hand.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "ollama"))
sys.path.insert(0, str(ROOT / "evals"))

import checks  # noqa: E402
import judge as jd  # noqa: E402  (standard library at import time; the API client loads only for `judge`)
import modelcheck  # noqa: E402

SETS = ROOT / "evals" / "sets"
DEFAULT_SET = SETS / "contact-center.jsonl"
DEFAULT_DB = ROOT / "evals" / "results.db"
JUDGING = ROOT / "evals" / "judging"
RUNS = ROOT / "evals" / "runs"  # one committed JSONL file per run: the record the database is built from
LEGACY_RESULTS = ROOT / "ops" / "results"  # inbox runs before 2026-11-12 came back as *.results.jsonl here
OLLAMA = modelcheck.DEFAULT_URL

SYSTEM = (
    "You are an assistant for a contact center. Follow the instructions exactly and reply with only what they ask for."
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started TEXT, machine TEXT, ollama_version TEXT, eval_set TEXT, note TEXT,
    set_sha TEXT
);
CREATE TABLE IF NOT EXISTS results (
    run_id TEXT, item_id TEXT, model TEXT, model_digest TEXT, task_type TEXT, industry TEXT,
    answer TEXT, error TEXT, latency_s REAL, completion_tokens INTEGER,
    rules_passed INTEGER, rules_total INTEGER, rule_details TEXT,
    judge TEXT, judge_score INTEGER, judge_reason TEXT, item_sha TEXT,
    PRIMARY KEY (run_id, item_id, model)
);
"""
# Columns added after the first databases were made; connect() adds them to older files.
ADDED_COLUMNS = {"runs": ["set_sha"], "results": ["item_sha"], "judge_calls": ["prompt_sha"]}


# ---------- data ----------


def set_path(name: str) -> Path:
    """evals/sets/<name>.jsonl for a set name like "my-work" (the .jsonl is optional)."""
    path = SETS / (name if name.endswith(".jsonl") else f"{name}.jsonl")
    if not path.is_file():
        have = ", ".join(sorted(p.stem for p in SETS.glob("*.jsonl")))
        raise SystemExit(f"no eval set {name!r} (have: {have})")
    return path


def run_set(con: sqlite3.Connection, run_id: str | None) -> Path:
    """The set a run was made from (older runs and unknown names fall back to the default set)."""
    row = con.execute("SELECT eval_set FROM runs WHERE run_id=?", (run_id,)).fetchone() if run_id else None
    path = SETS / row["eval_set"] if row and row["eval_set"] else DEFAULT_SET
    return path if path.is_file() else DEFAULT_SET


def load_items(path: Path = DEFAULT_SET, only: list[str] | None = None) -> list[dict]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if only:
        items = [i for i in items if any(i["id"].startswith(prefix) for prefix in only)]
    return items


def connect(db: Path = DEFAULT_DB) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA_SQL + jd.CALLS_SQL)
    for table, cols in ADDED_COLUMNS.items():
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
    con.commit()
    return con


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def item_sha(item: dict) -> str:
    """Fingerprint of everything that shapes an answer or its score (all but the notes), so a run is
    only compared with runs that saw the same version of an item."""
    stable = {k: v for k, v in item.items() if k != "notes"}
    return fingerprint(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode())


def build_prompt(item: dict) -> list[dict]:
    """The messages a model sees: the system line (the item's own, else the default), the instructions, the
    schema if any, then the input."""
    parts = [item["instructions"]]
    if item.get("output_schema"):
        parts.append("JSON schema:\n" + json.dumps(item["output_schema"], indent=2))
    parts.append("Input:\n" + item["input"])
    return [{"role": "system", "content": item.get("system", SYSTEM)}, {"role": "user", "content": "\n\n".join(parts)}]


# ---------- run ----------
#
# Safety rails (added 2026-11-05 after an uncapped run froze the Mac): every answer is capped
# (num_predict), the context is fixed (num_ctx), each item has a time limit, the runner stops cleanly
# when macOS memory stays low (or drops below a hard floor), and each model is unloaded when its turn ends.

MAX_TOKENS = 8192  # answer + thinking; hitting it is scored as a failure (redact-001 used 3,988 thinking)
CONTEXT = 16384  # the longest item plus a capped answer fits comfortably
ITEM_SECONDS = 300
MIN_FREE_PCT = 25  # stop if free memory stays below this for longer than LOW_GRACE_S
LOW_GRACE_S = 5.0  # gemma4:31b-mlx dips to ~19-23% for ~2 s right after loading, then holds 35-49%
# (2026-11-07); the 2026-11-04 freeze was a sustained fall, which this still catches
HARD_FLOOR_PCT = 12  # stop at once below this, however brief
WATCH_EVERY_S = 0.5  # how often the memory guard samples while an answer streams
EX_TEMPFAIL = 75  # "try again later" (sysexits.h): the inbox leaves the task pending
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


def keep_awake() -> None:
    """Stop idle sleep for as long as this process runs (a long run on a sleeping machine just stalls)."""
    with contextlib.suppress(Exception):
        if sys.platform == "darwin":
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])  # exits when we do
        elif sys.platform == "win32":
            import ctypes

            es_continuous, es_system_required = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)  # type: ignore[attr-defined]


GPU_BUSY_MEM_GB = 2.0  # NVIDIA memory in use with no model loaded: above this, something else (a game) has the GPU
GPU_BUSY_UTIL_PCT = 30


def gpu_in_use(url: str = OLLAMA, smi: str = "nvidia-smi") -> str:
    """Why the NVIDIA GPU looks busy with something other than Ollama, or "" (also "" with no NVIDIA GPU).
    Timings from a shared GPU aren't comparable, so `run` refuses unless told otherwise."""
    try:
        out = subprocess.run(
            [smi, "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        util, used_mb = (float(x) for x in out.stdout.strip().splitlines()[0].split(","))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return ""
    with contextlib.suppress(Exception):
        if modelcheck.call(url, "/api/ps").get("models"):
            return ""  # Ollama's own model explains the memory; it's unloaded per model anyway
    if used_mb / 1024 > GPU_BUSY_MEM_GB or util > GPU_BUSY_UTIL_PCT:
        return f"GPU busy before the run: {util:.0f}% use, {used_mb / 1024:.1f} GB in use with no model loaded"
    return ""


class MemoryGuard:
    """Trips when free memory stays below MIN_FREE_PCT for more than LOW_GRACE_S, or ever drops below
    HARD_FLOOR_PCT. A short dip (a model settling in after it loads) is allowed; a sustained fall is not."""

    def __init__(self, memory=None, clock=time.monotonic):
        self.memory, self.clock = memory or free_memory_pct, clock
        self.below_since: float | None = None
        self.tripped = ""

    def check(self) -> str:
        """Take one reading; return the reason once tripped (empty while all is well)."""
        free = self.memory()
        if self.tripped or free is None:
            return self.tripped
        now = self.clock()
        if free < HARD_FLOOR_PCT:
            self.tripped = f"free memory {free}% < {HARD_FLOOR_PCT}% (hard floor)"
        elif free < MIN_FREE_PCT:
            if self.below_since is None:
                self.below_since = now
            elif now - self.below_since > LOW_GRACE_S:
                self.tripped = f"free memory {free}% < {MIN_FREE_PCT}% for over {LOW_GRACE_S:g} s"
        else:
            self.below_since = None
        return self.tripped


def ask(model: str, item: dict, url: str = OLLAMA, memory=free_memory_pct) -> tuple[str, str, float, int]:
    """(answer, error, seconds, tokens) for one item, streamed so it can be stopped mid-answer.

    Raises LowMemory when the MemoryGuard trips (a background check unloads the model at once, so a
    stalled stream can't outlast it); any other failure is returned as an error string so one bad
    item doesn't stop the run.
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
    guard, stop, lock, unloaded = MemoryGuard(memory), threading.Event(), threading.Lock(), threading.Event()
    if guard.check():
        raise LowMemory(guard.tripped)

    def free_now() -> None:  # unload exactly once, whichever thread saw the trip first
        with lock:
            if not unloaded.is_set():
                unloaded.set()
                unload(model, url)

    def watch() -> None:  # samples between tokens too, and unloads at once if the guard trips
        while not stop.wait(WATCH_EVERY_S):
            if guard.check():
                free_now()
                return

    threading.Thread(target=watch, daemon=True).start()
    start, parts, tokens, done_reason = time.monotonic(), [], 0, ""
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            for n, line in enumerate(resp):
                if guard.tripped:  # closing the stream stops the model
                    raise LowMemory(guard.tripped)
                chunk = json.loads(line)
                parts.append((chunk.get("message") or {}).get("content") or "")
                if chunk.get("done"):
                    tokens, done_reason = chunk.get("eval_count") or 0, chunk.get("done_reason", "")
                    break
                if n % 50 == 0 and guard.check():
                    raise LowMemory(guard.tripped)
                if time.monotonic() - start > ITEM_SECONDS:
                    return "".join(parts).strip(), f"time limit {ITEM_SECONDS}s", time.monotonic() - start, n
    except LowMemory:
        raise
    except Exception as e:
        if guard.tripped:  # the guard unloaded the model mid-answer, which broke the stream
            raise LowMemory(guard.tripped) from e
        return "".join(parts).strip(), f"{type(e).__name__}: {e}", time.monotonic() - start, tokens
    finally:
        stop.set()
        if guard.tripped:
            free_now()
    if guard.tripped:
        raise LowMemory(guard.tripped)
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
    set_file: Path = DEFAULT_SET,
) -> str:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    version = modelcheck.call(url, "/api/version").get("version", "")
    con.execute(
        "INSERT INTO runs (run_id, started, machine, ollama_version, eval_set, note, set_sha) VALUES (?,?,?,?,?,?,?)",
        (
            run_id,
            datetime.now().isoformat(timespec="seconds"),
            socket.gethostname().split(".")[0],
            version,
            set_file.name,
            note,
            fingerprint(set_file.read_bytes()),
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
                    if free is not None and MIN_FREE_PCT > free >= HARD_FLOOR_PCT:
                        time.sleep(LOW_GRACE_S)  # give a short dip the same grace as mid-answer
                        free = memory()
                    if free is not None and free < MIN_FREE_PCT:
                        raise LowMemory(f"free memory {free}% < {MIN_FREE_PCT}% before {item['id']}")
                    answer, error, secs, tokens = asker(model, item, url)
                    results = checks.run_checks(item, answer) if not error else []
                    passed = sum(r.ok for r in results)
                    con.execute(
                        "INSERT INTO results (run_id, item_id, model, model_digest, task_type, industry, answer, "
                        "error, latency_s, completion_tokens, rules_passed, rules_total, rule_details, judge, "
                        "judge_score, judge_reason, item_sha) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                            item_sha(item),
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
    """Write a run (its runs row, every result and every judge call) as JSONL: the run's record."""
    meta = dict(con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())
    rows = [dict(r) for r in con.execute("SELECT * FROM results WHERE run_id=? ORDER BY rowid", (run_id,))]
    calls = [dict(r) for r in con.execute("SELECT * FROM judge_calls WHERE run_id=? ORDER BY rowid", (run_id,))]
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [("run", meta), *[("result", x) for x in rows], *[("judge_call", x) for x in calls]]
    path.write_text(
        "".join(json.dumps({"type": k, **v}, ensure_ascii=False) + "\n" for k, v in records), encoding="utf-8"
    )
    return len(rows)


def export_run(con: sqlite3.Connection, run_id: str, runs_dir: Path | None = None) -> Path:
    """(Re)write evals/runs/<run_id>.jsonl after a run, a judge pass or an import, for committing."""
    path = (runs_dir or RUNS) / f"{run_id}.jsonl"
    dump(con, run_id, path)
    return path


def _insert(con: sqlite3.Connection, table: str, row: dict) -> None:
    have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
    row = {k: v for k, v in row.items() if k in have}  # tolerate files from newer or older versions
    con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def load(con: sqlite3.Connection, path: Path) -> tuple[str, int]:
    """Load a run file (evals/runs/, or an older inbox file). Runs already in the database are skipped."""
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    meta = next(x for x in lines if x["type"] == "run")
    if con.execute("SELECT 1 FROM runs WHERE run_id=?", (meta["run_id"],)).fetchone():
        return meta["run_id"], 0
    tables = {"run": "runs", "result": "results", "judge_call": "judge_calls"}
    n = 0
    for x in lines:
        _insert(con, tables[x["type"]], {k: v for k, v in x.items() if k != "type"})
        n += x["type"] == "result"
    con.commit()
    return meta["run_id"], n


def run_files(runs_dir: Path | None = None, legacy_dir: Path | None = None) -> list[Path]:
    """Every run file, evals/runs/ first, so a judged copy wins over an older inbox copy of the same run."""
    runs_dir, legacy_dir = runs_dir or RUNS, legacy_dir or LEGACY_RESULTS
    return sorted(runs_dir.glob("*.jsonl")) + sorted(legacy_dir.glob("*.results.jsonl"))


def sync(con: sqlite3.Connection, files: list[Path] | None = None) -> list[str]:
    """Load run files that aren't in the database yet (e.g. runs another machine pushed). Returns their ids."""
    loaded = []
    for f in run_files() if files is None else files:
        before = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        run_id, _ = load(con, f)
        if con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] > before:  # counts runs stopped before item 1
            loaded.append(run_id)
    return loaded


def rebuild(db: Path = DEFAULT_DB, files: list[Path] | None = None) -> tuple[Path | None, int]:
    """Recreate the database from the run files. The old file is kept as a dated backup."""
    backup = None
    if db.exists():
        backup = db.with_name(f"{db.stem}.{datetime.now():%Y%m%d-%H%M%S}.bak")
        db.rename(backup)
    con = connect(db)
    n = len(sync(con, files))
    con.close()
    return backup, n


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


# ---------- compare: the model-origin rule (docs/V1-SPEC.md), applied per task type ----------

REGISTRY = ROOT / "router" / "models.json"
WIN_ITEMS = 1  # a real win: at least this many more items passing every rule check...
WIN_JUDGE = 0.3  # ...or, with equal rule results, this much higher judge average
ROUTINE_JUDGE = 4.0  # routine bar: every item passes all rules and the judge average is at least this
CHEAPER = 0.25  # a model must be at least this much cheaper to keep a place on cost


def origin(model: str) -> str:
    """Country of the model's maker from router/models.json ("" if unlisted)."""
    with contextlib.suppress(OSError, ValueError):
        for m in json.loads(REGISTRY.read_text(encoding="utf-8"))["models"]:
            if model in (m["tag"], m["tag"].removesuffix(":latest")):
                return m["country"]
    return ""


def side_stats(rows: list[sqlite3.Row]) -> dict:
    judged = [r["judge_score"] for r in rows if r["judge_score"] is not None]
    return {
        "n": len(rows),
        "pass": sum(r["rules_passed"] == r["rules_total"] and not r["error"] for r in rows),
        "judge": sum(judged) / len(judged) if judged else None,
        "judged": len(judged),
        "secs": sum(r["latency_s"] or 0 for r in rows) / max(len(rows), 1),
    }


def verdict(a: dict, b: dict, needs_judge: int, origin_a: str, origin_b: str) -> tuple[str, str]:
    """(winner "a" | "b" | "" for a tie or not enough data, why) for one task type."""
    if abs(a["pass"] - b["pass"]) >= WIN_ITEMS:
        return ("a" if a["pass"] > b["pass"] else "b"), f"rules {a['pass']} vs {b['pass']}"
    if needs_judge and (a["judged"] < needs_judge or b["judged"] < needs_judge):
        return "?", "rules tie; needs judging"
    if a["judge"] is not None and b["judge"] is not None and abs(a["judge"] - b["judge"]) >= WIN_JUDGE:
        return ("a" if a["judge"] > b["judge"] else "b"), f"judge {a['judge']:.2f} vs {b['judge']:.2f}"
    if {origin_a, origin_b} == {"US", "CN"}:
        return ("a" if origin_a == "US" else "b"), "tie; ties go to the American model"
    return "", "tie"


def meets_routine_bar(s: dict, needs_judge: int) -> bool:
    return s["pass"] == s["n"] and (not needs_judge or (s["judge"] is not None and s["judge"] >= ROUTINE_JUDGE))


def compare(con: sqlite3.Connection, a: tuple[str, str], b: tuple[str, str], items: dict[str, dict]) -> str:
    """Per task type (item id prefix): quality winner by the model-origin rule and who keeps a place.
    Only items both sides answered in the same version (matching fingerprints) count. Cost uses
    seconds per item until watts are measured (v1-4): on one machine, faster means cheaper."""
    q = "SELECT * FROM results WHERE run_id=? AND model=?"
    ra = {r["item_id"]: r for r in con.execute(q, a)}
    rb = {r["item_id"]: r for r in con.execute(q, b)}
    common = [i for i in sorted(ra.keys() & rb.keys()) if ra[i]["item_sha"] == rb[i]["item_sha"]]
    skipped = len(ra.keys() & rb.keys()) - len(common)
    oa, ob = origin(a[1]), origin(b[1])
    lines = [
        f"A = `{a[1]}` ({oa or 'origin?'}, run {a[0]})  vs  B = `{b[1]}` ({ob or 'origin?'}, run {b[0]})",
        f"{len(common)} items compared" + (f"; {skipped} skipped (different item versions)" if skipped else ""),
        "",
        "| Task | Items | A pass | B pass | A judge | B judge | A s/item | B s/item | Winner | Why | Keep |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for prefix in sorted({i.split("-")[0] for i in common}):
        ids = [i for i in common if i.startswith(prefix + "-")]
        sa, sb = side_stats([ra[i] for i in ids]), side_stats([rb[i] for i in ids])
        needs = sum(bool((items.get(i) or {}).get("grader")) for i in ids)
        win, why = verdict(sa, sb, needs, oa, ob)
        keep = decide(win, sa, sb, needs, oa, ob)
        fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
        lines.append(
            f"| {prefix} | {len(ids)} | {sa['pass']} | {sb['pass']} | {fmt(sa['judge'])} | {fmt(sb['judge'])} | "
            f"{sa['secs']:.1f} | {sb['secs']:.1f} | {win.upper() or 'tie'} | {why} | {keep} |"
        )
    return "\n".join(lines)


def decide(win: str, sa: dict, sb: dict, needs: int, oa: str, ob: str) -> str:
    """Who keeps a place for this task type, per V1-SPEC §Model-origin rule."""
    if win == "?":
        return "judge first"
    if not win:
        return "either"
    winner, loser, o_win, o_lose = (sa, sb, oa, ob) if win == "a" else (sb, sa, ob, oa)
    w_name, l_name = win.upper(), ("B" if win == "a" else "A")
    cheaper = loser["secs"] <= (1 - CHEAPER) * winner["secs"] and meets_routine_bar(loser, needs)
    if o_win == "CN" and o_lose == "US":
        return f"{w_name}, with {l_name} as the American fallback"
    if o_win == "US" and o_lose == "CN":
        if cheaper:
            return f"{w_name}; {l_name} may keep routine work if $/task confirms ≥25% cheaper"
        return f"{w_name} only"
    return w_name + (f"; {l_name} takes routine work (≥25% faster, meets the bar)" if cheaper else "")


# ---------- command line ----------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--set", default=DEFAULT_SET.stem, help="eval set in evals/sets/, e.g. my-work")
    r.add_argument("--items", nargs="*", help="id prefixes, e.g. redact- intent-001")
    r.add_argument("--url", default=OLLAMA)
    r.add_argument("--note", default="")
    r.add_argument("--out", type=Path, help="also write the run to this file (it always goes to evals/runs/)")
    r.add_argument("--allow-busy-gpu", action="store_true", help="run even if another program is using the GPU")
    ld = sub.add_parser("load")
    ld.add_argument("file", type=Path)
    sub.add_parser("sync")
    sub.add_parser("rebuild")
    e = sub.add_parser("export")
    e.add_argument("--run", required=True)
    i = sub.add_parser("import")
    i.add_argument("--run", required=True)
    i.add_argument("file", type=Path)
    rs = sub.add_parser("rescore")
    rs.add_argument("--run", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--run", required=True)
    j.add_argument("--max-usd", type=float, required=True, help="stop before spend could pass this")
    j.add_argument("--limit", type=int, help="grade only the first N answers (measure cost first)")
    cp = sub.add_parser("compare")
    cp.add_argument("--a", required=True, help="RUN_ID or RUN_ID:MODEL")
    cp.add_argument("--b", required=True, help="RUN_ID or RUN_ID:MODEL")
    rp = sub.add_parser("report")
    rp.add_argument("--run")
    a = p.parse_args(argv)

    if a.cmd == "rebuild":
        backup, n = rebuild(a.db)
        print(f"{n} runs loaded into {a.db}" + (f" (old database kept as {backup.name})" if backup else ""))
        return 0
    con = connect(a.db)
    items = {it["id"]: it for it in load_items(run_set(con, getattr(a, "run", None)))}
    if a.cmd == "run":
        busy = gpu_in_use(a.url)
        if busy and not a.allow_busy_gpu:
            print(f"NOT STARTED: {busy}. Timings would be skewed; close the other program or pass --allow-busy-gpu.")
            return EX_TEMPFAIL
        note = f"{a.note} [{busy}]".strip() if busy else a.note
        set_file = set_path(a.set)
        chosen = load_items(set_file, only=a.items)
        print(f"{len(chosen)} items x {len(a.models)} model(s)")
        if free_memory_pct() is None:
            print("NOTE  memory watchdog not available on this OS; the answer cap and fixed context still apply")
        keep_awake()
        run_id = run(a.models, chosen, con, a.url, note, set_file=set_file)
        print(f"run record: {export_run(con, run_id).relative_to(ROOT)} (commit it)")
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
    elif a.cmd == "sync":
        loaded = sync(con)
        if loaded:
            print(f"loaded {len(loaded)} new run(s) from git: {', '.join(loaded)}")
    elif a.cmd == "rescore":
        print(f"{rescore(con, a.run, items)} answers rescored")
    elif a.cmd == "judge":
        cfg = jd.load_config()
        jd.judge(con, a.run, items, jd.make_client(cfg), cfg, a.max_usd, a.limit)
        print(f"run record: {export_run(con, a.run).relative_to(ROOT)} (commit it)\n")
        print(report(con, a.run))
    elif a.cmd == "compare":
        sides = []
        for spec in (a.a, a.b):
            run_id, _, model = spec.partition(":")
            if not model:
                found = [
                    r["model"] for r in con.execute("SELECT DISTINCT model FROM results WHERE run_id=?", (run_id,))
                ]
                if len(found) != 1:
                    print(f"run {run_id} has {len(found)} models; name one as {run_id}:MODEL")
                    return 2
                model = found[0]
            sides.append((run_id, model))
        print(compare(con, sides[0], sides[1], items))
    elif a.cmd == "import":
        print(f"{import_grades(con, a.file)} scores imported")
        print(f"run record: {export_run(con, a.run).relative_to(ROOT)} (commit it)")
    else:
        print(report(con, a.run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
