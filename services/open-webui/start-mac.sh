#!/usr/bin/env bash
# Start Open WebUI on the Mac, for the Mac's own Ollama. Mac version of start.ps1:
#   bash services/open-webui/start-mac.sh
# Same pinned version and hash-locked uv.lock as your PC, same security settings. Localhost only:
# nothing on the Mac is shared over Tailscale. Paths come from config-mac.json. Ctrl+C stops it.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cfg="$here/config-mac.json"
get() { plutil -extract "$1" raw -o - "$cfg"; }   # plutil reads JSON natively
expand() { local p="$1"; echo "${p/#\~/$HOME}"; }

host="$(get host)"; port="$(get port)"; ollama_url="$(get ollamaUrl)"
data_dir="$(expand "$(get dataDir)")"; venv_dir="$(expand "$(get venvDir)")"

[ "$(uname)" = "Darwin" ] || { echo "Run this on the Mac. On your PC use start.ps1."; exit 1; }
if [ "$host" != "127.0.0.1" ]; then
    # The Mac's Open WebUI is for the Mac only (docs/setup/MAC.md).
    echo "config-mac.json host is '$host'. It must stay 127.0.0.1."; exit 1
fi
if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use. Is Open WebUI already running? Open http://$host:$port"; exit 1
fi

mkdir -p "$data_dir"

# Keep the (large) virtual environment outside the repo.
export UV_PROJECT_ENVIRONMENT="$venv_dir"

# Where Open WebUI keeps its database, uploads and secret key.
export DATA_DIR="$data_dir"

# Local Ollama only; no OpenAI-style providers until the LiteLLM gateway (v1-4).
export OLLAMA_BASE_URL="$ollama_url"
export ENABLE_OPENAI_API="False"

# No automatic model downloads (embedding, reranker, Whisper) and no update checks.
export OFFLINE_MODE="True"
export HF_HUB_OFFLINE="1"

# Nothing shared with the Open WebUI community site; opt out of analytics.
export ENABLE_COMMUNITY_SHARING="False"
export SCARF_NO_ANALYTICS="true"
export DO_NOT_TRACK="true"
export ANONYMIZED_TELEMETRY="false"

# The first account becomes admin and sign-up then closes. Anyone added later waits for approval.
export DEFAULT_USER_ROLE="pending"

# Run from the data folder: Open WebUI writes .webui_secret_key to the current directory,
# and it must never land in the repo.
cd "$data_dir"
echo "Open WebUI on http://$host:$port (data: $data_dir). Ctrl+C to stop."
exec uv run --project "$here" --locked --python 3.12 open-webui serve --host "$host" --port "$port"
