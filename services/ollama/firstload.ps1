# First load of a newly pulled model in a no-network container (V1-SPEC security rule).
# Usage (PowerShell 7, Docker Desktop running):
#   pwsh -File services\ollama\firstload.ps1 -Model gemma4:12b
# Pass = a sensible answer and `ollama ps` showing 100% GPU. Only then use the model on the host.

param(
    [Parameter(Mandatory)] [string] $Model,
    [int] $Context = 8192
)

$ErrorActionPreference = "Stop"
$cfg = Get-Content (Join-Path $PSScriptRoot "config.json") -Raw | ConvertFrom-Json
$name = "ollama-firstload"

docker rm -f $name 2>$null | Out-Null
# --network none: the model never gets network access. Models are mounted read-only.
docker run -d --name $name --network none --gpus all `
    -v "$($cfg.modelsDir):/models:ro" -e OLLAMA_MODELS=/models -e OLLAMA_NOPRUNE=1 `
    -e OLLAMA_CONTEXT_LENGTH=$Context "ollama/ollama:$($cfg.imageVersion)" | Out-Null

try {
    Start-Sleep 5
    if ((docker inspect $name --format "{{.HostConfig.NetworkMode}}") -ne "none") { throw "Container has network access" }

    # Synthetic contact-center prompt; the first run includes the cold load from disk.
    $prompt = "Classify the intent of this synthetic customer message as one word (billing, outage, cancel, other): My bill doubled this month and nobody told me why."
    docker exec $name ollama run $Model --hidethinking $prompt | Out-Null
    "--- warm run:"
    docker exec $name ollama run $Model --hidethinking --verbose $prompt 2>&1 |
        Select-String "^(billing|outage|cancel|other)|eval rate" | ForEach-Object { $_.Line.Trim() }
    "--- ollama ps (want 100% GPU):"
    docker exec $name ollama ps
    "--- GPU memory in use:"
    nvidia-smi --query-gpu=memory.used --format=csv,noheader
} finally {
    docker rm -f $name | Out-Null
}
