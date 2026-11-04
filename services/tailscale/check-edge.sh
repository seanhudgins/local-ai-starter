#!/usr/bin/env bash
# v1-0 edge check. Run on an edge device (Mac) with Tailscale connected:
#   bash services/tailscale/check-edge.sh
# Passes when Open WebUI answers over HTTPS and every other your PC port is blocked.

set -u
here="$(cd "$(dirname "$0")" && pwd)"
host="$(sed -n 's/.*"homenodeHost": *"\([^"]*\)".*/\1/p' "$here/config.json")"
fails=0

# Without nc every port would look "blocked", which is a false pass.
command -v nc >/dev/null 2>&1 || { echo "FAIL  nc not found; can't test ports"; exit 1; }

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }

echo "Checking $host from $(hostname)"

# 1. Open WebUI over tailnet HTTPS (tailscale serve -> 127.0.0.1:8080 on your PC).
code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 "https://$host/health")"
[ "$code" = "200" ] && pass "https://$host answers (HTTP 200, valid cert)" \
                    || fail "https://$host returned '$code' (want 200). Is Open WebUI running on your PC?"

# 2. Everything else must be unreachable: Open WebUI's raw port, Ollama, SSH, RDP, SMB.
# macOS nc: -G is the connect timeout (-w there is an idle timeout, so a blocked port would wait
# ~75 s). Linux nc: -w is the connect timeout.
if [ "$(uname)" = "Darwin" ]; then nc_timeout="-G 5"; else nc_timeout="-w 5"; fi
for port in 8080 11434 22 3389 445; do
    if nc -z $nc_timeout "$host" "$port" 2>/dev/null; then
        fail "port $port is reachable (the policy should block it)"
    else
        pass "port $port blocked"
    fi
done

# 3. GitHub two-factor (Tailscale signs in with GitHub, so this is the tailnet MFA).
if command -v gh >/dev/null 2>&1; then
    if ! gh api user --jq .login >/dev/null 2>&1; then
        fail "can't read GitHub two-factor: gh isn't logged in (run: gh auth login)"
    else
        # GitHub only returns this field when the token has the read:user scope; otherwise it's empty.
        tfa="$(gh api user --jq .two_factor_authentication 2>/dev/null)"
        case "$tfa" in
            true)  pass "GitHub two-factor is on" ;;
            false) fail "GitHub two-factor is OFF. Turn it on: github.com/settings/security" ;;
            *)     fail "can't read GitHub two-factor: gh needs the read:user scope. Run: gh auth refresh -h github.com -s read:user" ;;
        esac
    fi
else
    echo "SKIP  GitHub two-factor: gh not installed. Check github.com/settings/security."
fi

echo "MANUAL  Tailscale admin > Settings > Device management > Device approval is on."
echo
[ "$fails" -eq 0 ] && echo "All automatic checks passed." || echo "$fails check(s) failed."
exit "$fails"
