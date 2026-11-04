"""Tests for services/ollama/modelcheck.py against a fake Ollama server (no models needed)."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import modelcheck as mc
import pytest

TOOL_REPLY = {
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "get_account_balance", "arguments": {"account_id": "ACCT-1042"}}}],
    }
}


class FakeOllama:
    """Answers the Ollama API paths modelcheck uses, from a dict the test sets up."""

    def __init__(self) -> None:
        self.caps = ["completion", "tools"]
        self.answer = "Billing"
        self.tool_reply: dict = TOOL_REPLY
        self.size_vram = 100
        self.loaded = True
        self.requests: list[tuple[str, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep test output quiet
                pass

            def reply(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/api/version":
                    self.reply(200, {"version": "0.40.14"})
                elif self.path == "/api/tags":
                    self.reply(200, {"models": [{"name": "m:1", "model": "m:1", "digest": "abc123def456789"}]})
                elif self.path == "/api/ps":
                    models = [{"name": "m:1", "size": 100, "size_vram": fake.size_vram}] if fake.loaded else []
                    self.reply(200, {"models": models})
                else:
                    self.reply(404, {"error": "not found"})

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append((self.path, body))
                if body.get("model") != "m:1":
                    self.reply(404, {"error": f"model '{body.get('model')}' not found"})
                elif self.path == "/api/show":
                    self.reply(200, {"capabilities": fake.caps})
                elif self.path == "/api/chat" and "tools" in body:
                    self.reply(200, fake.tool_reply)
                elif self.path == "/api/chat":
                    self.reply(
                        200, {"message": {"content": fake.answer}, "eval_count": 80, "eval_duration": 1_000_000_000}
                    )
                elif self.path == "/api/embed":
                    self.reply(200, {"embeddings": [[0.1] * 768]})
                else:
                    self.reply(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def ollama():
    fake = FakeOllama()
    yield fake
    fake.server.shutdown()


# ---------- chat models ----------


def test_chat_model_passes_everything(ollama):
    results = mc.check(ollama.url, "m:1")
    assert all(r.ok for r in results), [r.line() for r in results]
    assert "80.0 tok/s" in results[0].message


def test_wrong_answer_fails(ollama):
    ollama.answer = "outage"
    assert not mc.check_answer(ollama.url, "m:1")[1].ok


def test_answer_with_punctuation_and_case_passes(ollama):
    ollama.answer = "**Billing.**"
    assert mc.check_answer(ollama.url, "m:1")[1].ok


def test_no_tool_support_fails_without_calling_chat(ollama):
    ollama.caps = ["completion"]
    result = mc.check_tools(ollama.url, "m:1")
    assert not result.ok and "doesn't support tools" in result.message
    assert not any(path == "/api/chat" for path, _ in ollama.requests)


def test_tool_call_with_wrong_argument_fails(ollama):
    ollama.tool_reply = {
        "message": {
            "tool_calls": [{"function": {"name": "get_account_balance", "arguments": {"account_id": "ACCT-9999"}}}]
        }
    }
    assert not mc.check_tools(ollama.url, "m:1").ok


def test_tool_call_with_string_arguments_passes(ollama):
    ollama.tool_reply = {
        "message": {
            "tool_calls": [
                {"function": {"name": "get_account_balance", "arguments": json.dumps({"account_id": "ACCT-1042"})}}
            ]
        }
    }
    assert mc.check_tools(ollama.url, "m:1").ok


def test_no_tool_call_fails(ollama):
    ollama.tool_reply = {"message": {"content": "I can't look that up."}}
    result = mc.check_tools(ollama.url, "m:1")
    assert not result.ok and "nothing" in result.message


def test_tool_request_sends_the_tool(ollama):
    mc.check_tools(ollama.url, "m:1")
    sent = next(body for path, body in ollama.requests if path == "/api/chat")
    assert sent["tools"][0]["function"]["name"] == "get_account_balance"


# ---------- where it runs ----------


@pytest.mark.parametrize(
    ("vram", "expect", "ok"),
    [(100, "gpu", True), (60, "gpu", False), (0, "cpu", True), (100, "cpu", False), (60, "any", True)],
)
def test_processor_expectations(ollama, vram, expect, ok):
    ollama.size_vram = vram
    assert mc.check_processor(ollama.url, "m:1", expect).ok is ok


def test_model_not_loaded_fails(ollama):
    ollama.loaded = False
    assert not mc.check_processor(ollama.url, "m:1", "any").ok


# ---------- embedding models ----------


def test_embedding_model_gets_vector_check_not_chat(ollama):
    ollama.caps = ["embedding"]
    results = mc.check(ollama.url, "m:1")
    assert all(r.ok for r in results)
    assert "768-number vector" in results[0].message
    assert not any(path == "/api/chat" for path, _ in ollama.requests)


# ---------- errors and the command line ----------


def test_unknown_model_fails_cleanly(ollama):
    assert mc.main(["check", "nope:1", "--url", ollama.url]) == 1


def test_unreachable_server_fails_cleanly():
    assert mc.main(["tools", "m:1", "--url", "http://127.0.0.1:9"]) == 1


def test_exit_code_counts_failures(ollama):
    ollama.answer, ollama.caps = "outage", ["completion"]  # wrong answer + no tools
    assert mc.main(["check", "m:1", "--url", ollama.url]) == 2


def test_identity_stamps_version_and_digest(ollama):
    assert mc.identity(ollama.url, "m:1") == {"ollama_version": "0.40.14", "model_digest": "abc123def456789"}


# ---------- file check ----------


def make_model(root: Path, tag: str, blobs: dict[str, bytes]) -> None:
    """A fake Ollama model store: blobs named by their sha256, plus a manifest listing them."""
    (root / "blobs").mkdir(parents=True)
    digests = []
    for content in blobs.values():
        d = "sha256:" + hashlib.sha256(content).hexdigest()
        (root / "blobs" / d.replace(":", "-")).write_bytes(content)
        digests.append(d)
    manifest = mc.manifest_path(root, tag)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"config": {"digest": digests[0]}, "layers": [{"digest": d} for d in digests[1:]]}))


def test_verify_passes_when_files_match(tmp_path):
    make_model(tmp_path, "m:1", {"config": b"{}", "weights": b"w" * 5000})
    results = mc.verify("m:1", tmp_path)
    assert all(r.ok for r in results) and "2 of 2" in results[-1].message


def test_verify_fails_on_changed_file(tmp_path):
    make_model(tmp_path, "m:1", {"config": b"{}", "weights": b"w" * 5000})
    blob = next(p for p in (tmp_path / "blobs").iterdir() if p.stat().st_size == 5000)
    blob.write_bytes(b"tampered")
    results = mc.verify("m:1", tmp_path)
    assert not results[-1].ok and "1 of 2" in results[-1].message


def test_verify_fails_on_missing_file(tmp_path):
    make_model(tmp_path, "m:1", {"config": b"{}", "weights": b"w"})
    next((tmp_path / "blobs").iterdir()).unlink()
    assert not mc.verify("m:1", tmp_path)[-1].ok


def test_verify_fails_without_manifest(tmp_path):
    assert not mc.verify("absent:1", tmp_path)[0].ok


@pytest.mark.parametrize(
    ("tag", "parts"),
    [
        ("gemma4:12b", ("library", "gemma4", "12b")),
        ("gemma4", ("library", "gemma4", "latest")),
        ("user/model:q4", ("user", "model", "q4")),
    ],
)
def test_manifest_path(tmp_path, tag, parts):
    assert mc.manifest_path(tmp_path, tag).parts[-3:] == parts
