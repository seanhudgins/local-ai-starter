# Start Open WebUI on your PC (v1-0). PowerShell 7: pwsh -File services\open-webui\start.ps1
# Paths come from config.json so nothing machine-specific is hard-coded here.
# Security settings below follow docs/V1-SPEC.md; change them only on purpose.

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$cfg  = Get-Content (Join-Path $here "config.json") -Raw | ConvertFrom-Json

if ($cfg.host -ne "127.0.0.1") {
    # Exposing beyond localhost waits for the Tailscale ACL, MFA and device approval (V1-SPEC).
    throw "config.json host is '$($cfg.host)'. Keep 127.0.0.1 until Tailscale is set up."
}

New-Item -ItemType Directory -Force -Path $cfg.dataDir | Out-Null

# Keep the (large) virtual environment on D:, outside the repo.
$env:UV_PROJECT_ENVIRONMENT = $cfg.venvDir

# Where Open WebUI keeps its database, uploads and secret key.
$env:DATA_DIR = $cfg.dataDir

# Local Ollama only; no OpenAI-style providers until the LiteLLM gateway (v1-4).
$env:OLLAMA_BASE_URL   = $cfg.ollamaUrl
$env:ENABLE_OPENAI_API = "False"

# No automatic model downloads (embedding, reranker, Whisper) and no update checks.
$env:OFFLINE_MODE   = "True"
$env:HF_HUB_OFFLINE = "1"

# Nothing shared with the Open WebUI community site; opt out of analytics.
$env:ENABLE_COMMUNITY_SHARING = "False"
$env:SCARF_NO_ANALYTICS       = "true"
$env:DO_NOT_TRACK             = "true"
$env:ANONYMIZED_TELEMETRY     = "false"

# The first account becomes admin and sign-up then closes. Anyone added later waits for approval.
$env:DEFAULT_USER_ROLE = "pending"

# Run from the data folder: pip installs write .webui_secret_key to the current directory,
# and it must never land in the repo.
Push-Location $cfg.dataDir
try {
    uv run --project $here --locked --python 3.12 open-webui serve --host $cfg.host --port $cfg.port
} finally {
    Pop-Location
}
