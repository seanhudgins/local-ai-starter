#!/usr/bin/env bash
# Check Ollama's safety settings on the Mac (docs/setup/MAC.md). Loads no model; run any time.
#   bash services/ollama/check-mac.sh
# First load of a new model is a separate step: services/ollama/firstload-mac.sh.
set -u
fails=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }

[ "$(uname)" = "Darwin" ] || { echo "FAIL  run this on the Mac (macOS)"; exit 1; }
app=/Applications/Ollama.app
ollama="$(command -v ollama || echo "$app/Contents/Resources/ollama")"
[ -x "$ollama" ] || { echo "FAIL  ollama not installed"; exit 1; }
echo "ollama $("$ollama" --version 2>/dev/null | awk '{print $NF}') on $(hostname)"

# 1. The app is the real one: signed by Ollama's developer ID and notarized by Apple.
if spctl -a -vv "$app" 2>&1 | grep -q 'Notarized Developer ID' \
   && codesign --verify --deep --strict "$app" 2>/dev/null; then
    pass "app signed and notarized ($(codesign -dv "$app" 2>&1 | sed -n 's/^TeamIdentifier=//p'))"
else
    fail "app signature or notarization check failed"
fi

# 2. Listening on localhost only.
listen="$(lsof -nP -iTCP:11434 -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $9}' | sort -u)"
if [ -z "$listen" ]; then
    fail "nothing listening on 11434 (is the Ollama app running?)"
elif echo "$listen" | grep -qvE '^(127\.0\.0\.1|\[::1\]):11434$'; then
    fail "Ollama listens beyond localhost: $listen (turn off 'Expose Ollama to the network')"
else
    pass "listens on localhost only ($listen)"
fi

# 3. Cloud disabled, in the config file and in the running server.
grep -q '"disable_ollama_cloud": *true' ~/.ollama/server.json 2>/dev/null \
    && pass "cloud disabled in ~/.ollama/server.json" \
    || fail "cloud not disabled (docs/setup/MAC.md, step 3)"
log="$HOME/.ollama/logs/server.log"
if [ -f "$log" ]; then
    grep 'Ollama cloud disabled' "$log" | tail -1 | grep -q 'true' \
        && pass "running server reports cloud disabled" \
        || fail "running server doesn't report cloud disabled (quit and reopen Ollama)"
fi

echo
[ "$fails" -eq 0 ] && echo "All checks passed." || echo "$fails check(s) failed."
exit "$fails"
