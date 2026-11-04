#!/usr/bin/env bash
# First load of a newly pulled model on the Mac, in a macOS sandbox with no network.
# Mac version of firstload.ps1 (V1-SPEC rule: first load/eval in an isolated, no-network environment).
# Docker can't be used on the Mac: its Linux VM has no Apple GPU and no MLX runtime.
#
#   bash services/ollama/firstload-mac.sh <tag> [context]      e.g. qwen3.6:27b-mlx 8192
#
# Pass = every isolation check passes, a sensible answer, `ollama ps` showing 100% GPU (Apple silicon;
# Intel Macs run on the CPU), and a correct tool call.
# Only then use the model in the normal Ollama app.

set -u
model="${1:?usage: firstload-mac.sh <model-tag> [context]}"
context="${2:-8192}"
here="$(cd "$(dirname "$0")" && pwd)"
profile="$here/firstload-mac.sb"
real_home="$HOME"
models="$HOME/.ollama/models"
port=11435                      # the normal Ollama app keeps 11434

[ "$(uname)" = "Darwin" ] || { echo "FAIL  run this on the Mac"; exit 1; }
arch="$(uname -m)"   # arm64 = Apple silicon (GPU via Metal, MLX); x86_64 = Intel Mac (expect CPU only)
if [ "$arch" = "x86_64" ] && echo "$model" | grep -qi mlx; then
    echo "FAIL  $model is an MLX model; MLX needs Apple silicon. Pick a non-mlx tag on an Intel Mac."; exit 1
fi
command -v sandbox-exec >/dev/null || { echo "FAIL  sandbox-exec not found"; exit 1; }
ollama="$(command -v ollama || echo /Applications/Ollama.app/Contents/Resources/ollama)"
[ -x "$ollama" ] || { echo "FAIL  ollama not installed"; exit 1; }
if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "FAIL  port $port is in use; is another first load running?"; exit 1
fi

scratch="$(mktemp -d "${TMPDIR:-/tmp}/ollama-firstload.XXXXXX")"
scratch="$(cd "$scratch" && pwd -P)"   # the sandbox matches real paths (/private/var/...)
server_pid=""

sandboxed() {   # run a command under the profile
    sandbox-exec -f "$profile" -D "MODELS=$models" -D "MODELS_PARENT=$(dirname "$models")" -D "SCRATCH=$scratch" -D "HOME_DIR=$real_home" "$@"
}

cleanup() {
    # Stop only the server this script started, and its runner subprocesses.
    if [ -n "$server_pid" ] && kill -0 "$server_pid" 2>/dev/null; then
        children="$(pgrep -P "$server_pid" || true)"
        kill "$server_pid" $children 2>/dev/null
        wait "$server_pid" 2>/dev/null
    fi
    rm -rf "$scratch"
}
trap cleanup EXIT

fails=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }

echo "First load of $model on $(hostname), sandboxed (context $context)"

# 1. Prove the sandbox holds before any model runs. Each check needs a control that works
#    outside the sandbox, so a broken check can't pass by accident.
if curl -s -m 5 -o /dev/null https://ollama.com; then
    sandboxed /usr/bin/curl -s -m 5 -o /dev/null https://ollama.com \
        && fail "network reachable inside the sandbox" || pass "no network inside the sandbox"
else
    echo "INFO  Mac is offline; can't contrast, network check skipped"
fi
probe="$HOME/.zshrc"; [ -r "$probe" ] || probe="$HOME/Desktop"
sandboxed /bin/ls "$probe" >/dev/null 2>&1 \
    && fail "home folder readable inside the sandbox" || pass "home folder hidden"
sandboxed /bin/ls "$models/manifests" >/dev/null 2>&1 \
    && pass "models readable" || fail "models not readable inside the sandbox"
sandboxed /usr/bin/touch "$models/.write-probe" 2>/dev/null \
    && { rm -f "$models/.write-probe"; fail "models writable inside the sandbox"; } \
    || pass "models read-only"

if [ "$fails" -ne 0 ]; then
    echo; echo "Sandbox checks failed; not loading the model."; exit 1
fi

# 2. Sandboxed server: throwaway HOME (no keys or history), models read-only, cloud off.
(
    cd "$scratch" || exit 1
    export HOME="$scratch" OLLAMA_HOST="127.0.0.1:$port" OLLAMA_MODELS="$models" \
           OLLAMA_NOPRUNE=1 OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH="$context"
    exec sandbox-exec -f "$profile" -D "MODELS=$models" -D "MODELS_PARENT=$(dirname "$models")" -D "SCRATCH=$scratch" \
         -D "HOME_DIR=$real_home" \
         "$ollama" serve
) > "$scratch/server.log" 2>&1 &
server_pid=$!

for _ in $(seq 1 30); do
    curl -s -m 1 "http://127.0.0.1:$port/" >/dev/null && break
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 1
done
if ! curl -s -m 1 "http://127.0.0.1:$port/" >/dev/null; then
    echo "FAIL  sandboxed server didn't start. Log:"; tail -20 "$scratch/server.log"; exit 1
fi
pass "sandboxed server up on 127.0.0.1:$port"

export OLLAMA_HOST="127.0.0.1:$port"
api="http://127.0.0.1:$port/api"
caps="$("$ollama" show "$model" 2>/dev/null | sed -n '/Capabilities/,/^$/p')"

# Embedding models can't chat: check they return a vector, then finish.
if echo "$caps" | grep -qw embedding; then
    start=$(date +%s)
    resp="$(curl -s -m 300 "$api/embed" -d "{\"model\":\"$model\",\"input\":\"Synthetic test: customer asks why the bill doubled.\"}")"
    dims="$(printf '%s' "$resp" | python3 -I -c 'import json,sys; e=json.load(sys.stdin).get("embeddings") or [[]]; print(len(e[0]))' 2>/dev/null || echo 0)"
    echo "--- embedding (cold load included): $(( $(date +%s) - start ))s"
    [ "${dims:-0}" -gt 0 ] && pass "embedding model returns a $dims-number vector" \
                           || fail "no embedding returned: $(printf '%s' "$resp" | head -c 200)"
    "$ollama" ps
else

# 3. Synthetic contact-center prompt (same as firstload.ps1); the first run is the cold load.
prompt="Classify the intent of this synthetic customer message as one word (billing, outage, cancel, other): My bill doubled this month and nobody told me why."
start=$(date +%s)
if ! cold="$("$ollama" run "$model" --hidethinking "$prompt" 2>&1)"; then
    fail "model didn't load: $(echo "$cold" | tail -1)"
    echo "--- server log (last 15 lines):"; tail -15 "$scratch/server.log"; exit 1
fi
echo "--- cold load + first answer: $(( $(date +%s) - start ))s"
echo "--- warm run:"
# The answer goes to stdout; the spinner and --verbose stats go to stderr.
answer="$("$ollama" run "$model" --hidethinking --verbose "$prompt" 2>"$scratch/stats" | tr -s '\n' ' ')"
echo "answer: $answer"
grep -E 'eval rate' "$scratch/stats" | sed -E $'s/\x1b\\[[0-9;?]*[a-zA-Z]//g'
echo "$answer" | grep -qiw 'billing' && pass "answer is 'billing'" || fail "expected 'billing'"
echo "--- ollama ps:"
ps_out="$("$ollama" ps)"; echo "$ps_out"
if [ "$arch" = "x86_64" ]; then
    echo "$ps_out" | grep -qE '100% (CPU|GPU)' && pass "runs ($(echo "$ps_out" | grep -oE '100% (CPU|GPU)')); CPU is expected on an Intel Mac" \
        || fail "split between CPU and GPU, or not loaded"
else
    echo "$ps_out" | grep -q '100% GPU' && pass "100% GPU" || fail "not fully on the GPU"
fi

# Tool use is a requirement on the Mac. The "tools" badge only means the model
# accepts tool definitions, so check it actually calls a synthetic tool with the right argument.
echo "--- tool call:"
if ! echo "$caps" | grep -qw tools; then
    fail "model doesn't support tools (required)"
else
    tool_req='{"model":"'"$model"'","stream":false,
      "messages":[{"role":"user","content":"What is the current balance on synthetic account ACCT-1042?"}],
      "tools":[{"type":"function","function":{"name":"get_account_balance",
        "description":"Look up the current balance of a customer account by its ID.",
        "parameters":{"type":"object","properties":{"account_id":{"type":"string","description":"Account ID, e.g. ACCT-0001"}},"required":["account_id"]}}}]}'
    tool_resp="$(curl -s -m 300 "$api/chat" -d "$tool_req")"
    call="$(printf '%s' "$tool_resp" | python3 -I -c '
import json, sys
calls = (json.load(sys.stdin).get("message") or {}).get("tool_calls") or []
f = calls[0]["function"] if calls else {}
args = f.get("arguments") or {}
if isinstance(args, str): args = json.loads(args)
print(f.get("name", "") + " " + str(args.get("account_id", "")))' 2>/dev/null)"
    echo "called: ${call:-nothing}"
    [ "$call" = "get_account_balance ACCT-1042" ] && pass "calls the tool with the right argument" \
        || fail "expected get_account_balance(ACCT-1042)"
fi
fi   # end chat-model checks

# 4. Anything the server tried to reach outside the Mac (blocked by the sandbox).
blocked="$(grep -iE 'dial tcp|no such host|network is unreachable' "$scratch/server.log")"
if [ -n "$blocked" ]; then
    echo "--- outbound attempts blocked by the sandbox:"; echo "$blocked" | cut -c1-200
else
    echo "--- no outbound attempts in the server log"
fi

echo
[ "$fails" -eq 0 ] && echo "All checks passed." || echo "$fails check(s) failed."
exit "$fails"
