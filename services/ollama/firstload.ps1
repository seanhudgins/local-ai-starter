# First load of a newly pulled model in a no-network container (V1-SPEC security rule).
# Usage (PowerShell 7, Docker Desktop running):
#   pwsh -File services\ollama\firstload.ps1 -Model gemma4:12b            # NVIDIA GPU
#   pwsh -File services\ollama\firstload.ps1 -Model gemma4:12b -NoGpu     # AMD Radeon / Intel GPU
# Docker Desktop passes only NVIDIA GPUs into containers, so on AMD or Intel GPUs the container runs
# on the CPU. That's fine: this is an isolation test, not a speed test. Check the GPU on the host after.
#
# How it works: Ollama runs in a container with --network none (loopback only). A second, throwaway
# container joins that container's network namespace (--network container:<name>) and runs
# modelcheck.py `check` against 127.0.0.1:11434: safeguards, synthetic prompt, tool call, where it runs.
# Neither container can reach anything outside. Exit code = modelcheck's exit code (failed checks).

param(
    [Parameter(Mandatory)] [string] $Model,
    [int] $Context = 8192,
    [int] $StartTimeout = 60,
    [switch] $NoGpu
)

$ErrorActionPreference = "Stop"
$cfg = Get-Content (Join-Path $PSScriptRoot "config.json") -Raw | ConvertFrom-Json
if ($cfg.checkImage -notmatch "@sha256:[0-9a-f]{64}$") { throw "checkImage in config.json must be pinned by digest" }
$name = "ollama-firstload"
$expect = if ($NoGpu) { "cpu" } else { "gpu" }

docker rm -f $name 2>$null | Out-Null
# --network none: the model never gets network access. Models are mounted read-only.
$gpuArgs = if ($NoGpu) { @() } else { @("--gpus", "all") }
docker run -d --name $name --network none @gpuArgs `
    -v "$($cfg.modelsDir):/models:ro" -e OLLAMA_MODELS=/models -e OLLAMA_NOPRUNE=1 `
    -e OLLAMA_CONTEXT_LENGTH=$Context "ollama/ollama:$($cfg.imageVersion)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Couldn't start the Ollama container" }

$code = 1
try {
    if ((docker inspect $name --format "{{.HostConfig.NetworkMode}}") -ne "none") { throw "Container has network access" }

    # Wait until the server answers (it has no network, so ask it from inside).
    $deadline = (Get-Date).AddSeconds($StartTimeout)
    while ($true) {
        docker exec $name ollama list 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        if ((docker inspect $name --format "{{.State.Running}}") -ne "true") {
            docker logs --tail 20 $name; throw "Ollama container stopped while starting"
        }
        if ((Get-Date) -gt $deadline) {
            docker logs --tail 20 $name; throw "Ollama didn't start within $StartTimeout s"
        }
        Start-Sleep 1
    }
    "PASS  Ollama up in a no-network container"

    # The checks: a second container in the first one's network namespace (loopback only), the
    # script mounted read-only, Python image pinned by digest in config.json.
    docker run --rm --network "container:$name" --read-only --cap-drop ALL --security-opt no-new-privileges `
        -v "${PSScriptRoot}:/check:ro" $cfg.checkImage `
        python -I -u /check/modelcheck.py check $Model --url http://127.0.0.1:11434 --expect $expect
    $code = $LASTEXITCODE
    if ($NoGpu) { "Next: check where it runs on the host (docs/setup/PC.md, Adding a model, step 5)." }
} finally {
    docker rm -f $name | Out-Null
}
exit $code
