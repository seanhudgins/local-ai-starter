#!/usr/bin/env bash
# Check Ollama's safety settings on the Mac (docs/setup/MAC.md). Loads and downloads no model; run any time.
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

# 4. LuLu blocks Ollama's outbound traffic (docs/setup/MAC.md, section 6). Ask the running server to
#    pull a random tag that can't exist: it fails at the manifest lookup, so nothing is ever
#    downloaded. A connection error = blocked; "file does not exist" = it reached the registry.
probe="localai-lulu-probe-$RANDOM$RANDOM:none-$(date +%s)"
reply="$(curl -s -m 30 http://127.0.0.1:11434/api/pull -d "{\"model\":\"$probe\",\"stream\":false}")"
if [ -z "$reply" ]; then
    fail "no reply from Ollama to the outbound probe (is the app running?)"
elif echo "$reply" | grep -q '"status":"success"'; then
    fail "probe tag $probe pulled?! Remove it (ollama rm $probe) and check the registry"
elif echo "$reply" | grep -qiE 'file does not exist|manifest unknown|not found'; then
    fail "Ollama reached its registry (LuLu rule for Ollama left on Allow?)"
elif echo "$reply" | grep -qiE 'dial tcp|connect:|no such host|network is unreachable|i/o timeout|connection refused'; then
    if curl -s -m 5 -o /dev/null https://registry.ollama.ai/v2/; then
        pass "Ollama can't reach its registry; this Mac can (LuLu is blocking Ollama)"
    else
        echo "INFO  Ollama can't reach its registry, but this Mac looks offline too; LuLu not proven"
    fi
else
    fail "unexpected reply to the outbound probe: $(echo "$reply" | cut -c1-160)"
fi

echo
[ "$fails" -eq 0 ] && echo "All checks passed." || echo "$fails check(s) failed."
exit "$fails"
