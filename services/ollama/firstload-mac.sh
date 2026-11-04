#!/usr/bin/env bash
# First load of a newly pulled model on the Mac, in a macOS sandbox with no network.
# Mac version of firstload.ps1 (V1-SPEC rule: first load/eval in an isolated, no-network environment).
# Docker can't be used on the Mac: its Linux VM has no Apple GPU and no MLX runtime.
#
#   bash services/ollama/firstload-mac.sh <tag> [context]      e.g. qwen3.6:27b-mlx 8192
#
# Pass = every isolation check passes, then modelcheck.py passes: a sensible answer, a correct tool
# call, and 100% GPU on Apple silicon (Intel Macs run on the CPU). Embedding models get a vector check.
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
command -v uv >/dev/null || { echo "FAIL  uv not found (brew install uv)"; exit 1; }
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

# 3. Model checks (services/ollama/modelcheck.py): synthetic prompt, tool call (required for chat
#    models), vector check for embedding models, and where it runs. Run from outside the sandbox
#    as a client of the sandboxed server.
expect=gpu; [ "$arch" = "x86_64" ] && expect=cpu   # Intel Macs run on the CPU
if uv run --quiet "$here/modelcheck.py" check "$model" --url "http://127.0.0.1:$port" --expect "$expect" \
        > "$scratch/checks.txt" 2>&1; then
    grep -E '^(INFO|PASS|FAIL)' "$scratch/checks.txt"
else
    grep -E '^(INFO|PASS|FAIL)' "$scratch/checks.txt" || tail -5 "$scratch/checks.txt"
    fail "model checks (details above)"
fi

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
