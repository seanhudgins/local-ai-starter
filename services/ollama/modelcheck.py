# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Checks for a local model, the same on Mac and Windows. Standard library only, so it runs offline.

    uv run services/ollama/modelcheck.py verify <tag> [--models-dir DIR]   every file matches its sha256
    uv run services/ollama/modelcheck.py check  <tag> [--url URL] [--expect gpu|cpu|any]
    uv run services/ollama/modelcheck.py tools  <tag> [--url URL]           tool-call test only
    uv run services/ollama/modelcheck.py answer <tag> [--url URL]           synthetic prompt only
    uv run services/ollama/modelcheck.py embed  <tag> [--url URL]           embedding models only

`check` reads the model's capabilities and runs what applies: chat models get the synthetic
contact-center prompt, a tool-call test (tools are required) and a GPU check; embedding models get a
vector check. The first-load scripts call it after setting up isolation. Exit code = failed checks.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:11434"

PROMPT = (
    "Classify the intent of this synthetic customer message as one word "
    "(billing, outage, cancel, other): My bill doubled this month and nobody told me why."
)
EXPECTED_ANSWER = "billing"

TOOL = {
    "type": "function",
    "function": {
        "name": "get_account_balance",
        "description": "Look up the current balance of a customer account by its ID.",
        "parameters": {
            "type": "object",
            "properties": {"account_id": {"type": "string", "description": "Account ID, e.g. ACCT-0001"}},
            "required": ["account_id"],
        },
    },
}
TOOL_QUESTION = "What is the current balance on synthetic account ACCT-1042?"
EXPECTED_CALL = ("get_account_balance", "ACCT-1042")


@dataclass
class Result:
    ok: bool
    message: str

    def line(self) -> str:
        return f"{'PASS' if self.ok else 'FAIL'}  {self.message}"


# ---------- Ollama API ----------


class OllamaError(RuntimeError):
    pass


def call(url: str, path: str, body: dict | None = None, timeout: float = 600) -> dict:
    """POST (with body) or GET (without) to the Ollama API and return the JSON reply."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        with contextlib.suppress(ValueError):
            detail = json.loads(detail).get("error", detail)
        raise OllamaError(f"{path}: {detail}") from None
    except urllib.error.URLError as e:
        raise OllamaError(f"can't reach Ollama at {url} ({e.reason})") from None


def capabilities(url: str, model: str) -> list[str]:
    return call(url, "/api/show", {"model": model}).get("capabilities") or []


def identity(url: str, model: str) -> dict:
    """Ollama version and model digest: stamped on results so an update can't silently change them."""
    digest = next(
        (
            m.get("digest", "")
            for m in call(url, "/api/tags").get("models", [])
            if model in (m.get("name"), m.get("model"))
        ),
        "",
    )
    return {"ollama_version": call(url, "/api/version").get("version", ""), "model_digest": digest}


def chat(url: str, model: str, messages: list[dict], tools: list[dict] | None = None) -> dict:
    body: dict = {"model": model, "messages": messages, "stream": False}
    if tools:
        body["tools"] = tools
    return call(url, "/api/chat", body)


def tokens_per_second(reply: dict) -> float:
    count, ns = reply.get("eval_count") or 0, reply.get("eval_duration") or 0
    return round(count / (ns / 1e9), 1) if count and ns else 0.0


def gpu_share(url: str, model: str) -> int | None:
    """Percent of the loaded model in GPU memory, or None if it isn't loaded."""
    for m in call(url, "/api/ps").get("models", []):
        if model in (m.get("name"), m.get("model")):
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            return round(100 * vram / size) if size else 0
    return None


# ---------- checks ----------


def first_call(reply: dict) -> tuple[str, str]:
    """(tool name, account_id) of the first tool call in a chat reply; ("", "") if none."""
    calls = (reply.get("message") or {}).get("tool_calls") or []
    if not calls:
        return "", ""
    fn = calls[0].get("function") or {}
    args = fn.get("arguments") or {}
    if isinstance(args, str):  # some servers send arguments as a JSON string
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    return fn.get("name", ""), str(args.get("account_id", ""))


def check_answer(url: str, model: str) -> list[Result]:
    messages = [{"role": "user", "content": PROMPT}]
    start = time.monotonic()
    chat(url, model, messages)  # cold run: includes loading from disk
    cold = time.monotonic() - start
    warm = chat(url, model, messages)
    answer = ((warm.get("message") or {}).get("content") or "").strip()
    words = {w.strip(".,!*`'\"").lower() for w in answer.split()}
    return [
        Result(True, f"cold load + first answer {cold:.0f}s; warm {tokens_per_second(warm)} tok/s"),
        Result(EXPECTED_ANSWER in words, f"answer {answer[:40]!r} (want {EXPECTED_ANSWER!r})"),
    ]


def check_tools(url: str, model: str, caps: list[str] | None = None) -> Result:
    caps = capabilities(url, model) if caps is None else caps
    if "tools" not in caps:
        return Result(False, "model doesn't support tools (required for chat models)")
    got = first_call(chat(url, model, [{"role": "user", "content": TOOL_QUESTION}], [TOOL]))
    shown = f"{got[0]}({got[1]})" if got[0] else "nothing"
    return Result(got == EXPECTED_CALL, f"tool call {shown} (want {EXPECTED_CALL[0]}({EXPECTED_CALL[1]}))")


def check_embed(url: str, model: str) -> Result:
    reply = call(url, "/api/embed", {"model": model, "input": "Synthetic test: customer asks why the bill doubled."})
    dims = len((reply.get("embeddings") or [[]])[0])
    return Result(dims > 0, f"returns a {dims}-number vector")


def check_processor(url: str, model: str, expect: str) -> Result:
    share = gpu_share(url, model)
    if share is None:
        return Result(False, "model isn't loaded, so where it runs can't be checked")
    where = f"{share}% GPU"
    if expect == "gpu":
        return Result(share == 100, f"{where} (want 100% GPU)")
    if expect == "cpu":
        return Result(share == 0, f"{where} (CPU expected here)")
    return Result(True, where)


def check(url: str, model: str, expect: str = "gpu") -> list[Result]:
    caps = capabilities(url, model)
    ident = identity(url, model)
    print(
        f"INFO  {model} on Ollama {ident['ollama_version']}, digest {ident['model_digest'][:12]}, "
        f"capabilities: {', '.join(caps) or 'none'}"
    )
    if "embedding" in caps:
        results = [check_embed(url, model)]
    else:
        results = check_answer(url, model) + [check_tools(url, model, caps)]
    results.append(check_processor(url, model, expect))
    return results


# ---------- file check ----------


def models_dir() -> Path:
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def manifest_path(root: Path, tag: str) -> Path:
    name, _, version = tag.partition(":")
    repo = name if "/" in name else f"library/{name}"
    return root / "manifests" / "registry.ollama.ai" / repo / (version or "latest")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify(tag: str, root: Path | None = None) -> list[Result]:
    """Every file of a pulled model matches the sha256 its manifest names."""
    root = root or models_dir()
    manifest = manifest_path(root, tag)
    if not manifest.is_file():
        return [Result(False, f"no manifest at {manifest}")]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    digests = sorted({d["digest"] for d in [data.get("config", {}), *data.get("layers", [])] if d.get("digest")})
    bad = [
        d
        for d in digests
        if not (blob := root / "blobs" / d.replace(":", "-")).is_file() or f"sha256:{sha256(blob)}" != d
    ]
    results = [Result(False, f"{d} missing or changed") for d in bad]
    results.append(Result(bool(digests) and not bad, f"{tag}: {len(digests) - len(bad)} of {len(digests)} files match"))
    return results


# ---------- command line ----------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "tools", "answer", "embed", "verify"):
        sp = sub.add_parser(name)
        sp.add_argument("model")
        if name == "verify":
            sp.add_argument("--models-dir", type=Path, default=None, help="default: $OLLAMA_MODELS or ~/.ollama/models")
        else:
            sp.add_argument("--url", default=DEFAULT_URL)
        if name == "check":
            sp.add_argument("--expect", choices=("gpu", "cpu", "any"), default="gpu")
    a = p.parse_args(argv)

    try:
        if a.cmd == "verify":
            results = verify(a.model, a.models_dir)
        elif a.cmd == "check":
            results = check(a.url, a.model, a.expect)
        elif a.cmd == "tools":
            results = [check_tools(a.url, a.model)]
        elif a.cmd == "answer":
            results = check_answer(a.url, a.model)
        else:
            results = [check_embed(a.url, a.model)]
    except OllamaError as e:
        results = [Result(False, str(e))]

    for r in results:
        print(r.line())
    fails = sum(not r.ok for r in results)
    print("\nAll checks passed." if not fails else f"\n{fails} check(s) failed.")
    return fails


if __name__ == "__main__":
    sys.exit(main())
