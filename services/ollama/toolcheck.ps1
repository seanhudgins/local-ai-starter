# Tool-call check for a model on the host Ollama, after its first load passed (V1-SPEC: tools required).
#   pwsh -File services\ollama\toolcheck.ps1 -Model gemma4:12b
# Gives the model a synthetic get_account_balance tool. Pass only if it calls it with ACCT-1042.
# Also prints where the model runs (GPU or CPU), which matters for AMD and Intel GPUs.

param(
    [Parameter(Mandatory)] [string] $Model,
    [string] $Url = "http://127.0.0.1:11434"
)

$ErrorActionPreference = "Stop"
$body = @{
    model    = $Model
    stream   = $false
    messages = @(@{ role = "user"; content = "What is the current balance on synthetic account ACCT-1042?" })
    tools    = @(@{
        type     = "function"
        function = @{
            name        = "get_account_balance"
            description = "Look up the current balance of a customer account by its ID."
            parameters  = @{
                type       = "object"
                properties = @{ account_id = @{ type = "string"; description = "Account ID, e.g. ACCT-0001" } }
                required   = @("account_id")
            }
        }
    })
} | ConvertTo-Json -Depth 10

$resp = Invoke-RestMethod -Uri "$Url/api/chat" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 300
$call = $resp.message.tool_calls | Select-Object -First 1
$name = $call.function.name
$callArgs = $call.function.arguments
if ($callArgs -is [string]) { $callArgs = $callArgs | ConvertFrom-Json }
"called: $name $($callArgs.account_id)"

$ps = Invoke-RestMethod -Uri "$Url/api/ps"
$m = $ps.models | Where-Object { $_.name -eq $Model -or $_.model -eq $Model } | Select-Object -First 1
if ($m) {
    $gpuPct = if ($m.size -gt 0) { [math]::Round(100 * $m.size_vram / $m.size) } else { 0 }
    "runs on: $gpuPct% GPU (rest on CPU)"
}

if ($name -eq "get_account_balance" -and $callArgs.account_id -eq "ACCT-1042") {
    "PASS  calls the tool with the right argument"
} else {
    "FAIL  expected get_account_balance(ACCT-1042)"
    exit 1
}
