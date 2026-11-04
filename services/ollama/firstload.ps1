# First load of a newly pulled model in a no-network container (V1-SPEC security rule).
# Usage (PowerShell 7, Docker Desktop running):
#   pwsh -File services\ollama\firstload.ps1 -Model gemma4:12b            # NVIDIA GPU
#   pwsh -File services\ollama\firstload.ps1 -Model gemma4:12b -NoGpu     # AMD Radeon / Intel GPU
# Docker Desktop passes only NVIDIA GPUs into containers, so on AMD or Intel GPUs the container runs
# on the CPU. That's fine: this is an isolation test, not a speed test. The GPU is checked on the host.
# Pass = a sensible answer, and with an NVIDIA GPU `ollama ps` showing 100% GPU. Then run
# `uv run services\ollama\modelcheck.py check <tag>` on the host. Only then use the model.

param(
    [Parameter(Mandatory)] [string] $Model,
    [int] $Context = 8192,
    [switch] $NoGpu
)

$ErrorActionPreference = "Stop"
$cfg = Get-Content (Join-Path $PSScriptRoot "config.json") -Raw | ConvertFrom-Json
$name = "ollama-firstload"

docker rm -f $name 2>$null | Out-Null
# --network none: the model never gets network access. Models are mounted read-only.
$gpuArgs = if ($NoGpu) { @() } else { @("--gpus", "all") }
docker run -d --name $name --network none @gpuArgs `
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
    if ($NoGpu) {
        "--- ollama ps (CPU-only container; expect 100% CPU here, check the GPU on the host afterwards):"
        docker exec $name ollama ps
    } else {
        "--- ollama ps (want 100% GPU):"
        docker exec $name ollama ps
        "--- GPU memory in use:"
        nvidia-smi --query-gpu=memory.used --format=csv,noheader
    }
} finally {
    docker rm -f $name | Out-Null
}
