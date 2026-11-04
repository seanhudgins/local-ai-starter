# PC setup path: your PC (home node)

**Role:** home node. Runs every service: Ollama, Open WebUI, and later the LiteLLM gateway, MCP
server, evals and scheduled jobs. Holds all provider API keys.
**Hardware (example):** Windows 11 Home, RTX 4080 SUPER (16 GB VRAM), 32 GB RAM.
**Shell:** PowerShell 7 (`pwsh`) by default, in the repo folder. Steps marked **WSL** run in Ubuntu:
type `wsl` in PowerShell to open it, then `cd /mnt/c/<path-to-repo>` (`C:\` is `/mnt/c/` in WSL).
**Paths:** repo at `C:\projects\local-ai`; large data on `D:\ai`.

New machine? Do [`../GETTING-STARTED.md`](../GETTING-STARTED.md) first (accounts, folders, tools).
The Mac path is in [MAC.md](MAC.md); [../SETUP.md](../SETUP.md) compares the two. Run each verify
check before moving on.

---

## 1. Base
| Item | Check (PowerShell) |
|---|---|
| GPU driver (see the GPU table below) | NVIDIA: `nvidia-smi` lists your GPU and its memory |
| WSL2 + Ubuntu | `wsl -l -v` shows `VERSION 2`. NVIDIA only: `wsl nvidia-smi` lists the GPU too |
| uv, Git, PowerShell 7, gh, Claude Code | `uv --version`, `git --version`, `gh --version`, `claude doctor` |
| gitleaks + hook: `git config core.hooksPath .githooks` | The commit test in `../GETTING-STARTED.md` §5 is refused |
| Docker Desktop (WSL2 backend) | `docker version`. Needed for the first-load check in §4 |

**Which GPU do you have?** Ollama picks the engine itself; the first-load check differs.

| GPU | Ollama uses | Driver | First load (§4) |
|---|---|---|---|
| **NVIDIA GeForce / RTX** (GTX 750 Ti or newer) | CUDA | NVIDIA driver 550 or newer | `firstload.ps1 -Model <tag>` (GPU inside the container) |
| **AMD Radeon RX 7600–7900, Radeon PRO W7500–W7900** | ROCm | AMD Adrenalin driver with ROCm 7 / HIP 7 support | `firstload.ps1 -Model <tag> -NoGpu` |
| **Other AMD Radeon; Intel Arc or Iris Xe** | Vulkan (on by default; most Windows drivers include it) | Latest AMD or Intel graphics driver | `firstload.ps1 -Model <tag> -NoGpu` |

Docker Desktop passes only NVIDIA GPUs into containers, so on AMD and Intel the isolated first load
runs on the CPU. It's an isolation test, not a speed test; `toolcheck.ps1` then shows GPU use on the
host. Integrated GPUs (Iris Xe, Radeon in Ryzen chips) share system RAM: count that as their memory.

## 2. Tailscale (home node)
1. Sign in to the Tailscale app on the PC. Use an account with two-factor on.
2. Admin console (https://login.tailscale.com/admin) → **Settings → Device management → Device
   approval**: on. New devices then wait for your OK.
3. **Policy first:** in [`services/tailscale/policy.hujson`](../../services/tailscale/policy.hujson),
   set `tests` → `src` to your login exactly as admin console → **Users** shows it (e.g. `jane@github`).
   Then admin console → **Access controls**, replace everything with the file's contents, **Save**.
   Your devices may then reach your PC on 443 (Open WebUI) and 4000 (gateway, v1-4) only.
4. **Then tag the PC:** admin console → **Machines** → your PC → `…` → **Edit ACL tags** →
   `tag:homenode`. (The tag only exists once the policy is saved.)
5. Admin console → **DNS**: turn on **MagicDNS** and **HTTPS Certificates** (needed in §5).

## 3. Ollama
1. **Variables first** (before Ollama starts for the first time). Change the path if your data
   folder differs:
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_NO_CLOUD", "1", "User")            # cloud off
   [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\ai\ollama", "User")   # models off C: and out of the repo
   # Optional: keep a model loaded for an hour instead of 5 minutes (holds its VRAM meanwhile)
   # [Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "1h", "User")
   ```
2. **Install:** `winget install --id Ollama.Ollama -e` (winget checks the installer's hash). Or download
   `OllamaSetup.exe` from https://ollama.com/download and check it first:
   `Get-AuthenticodeSignature .\OllamaSetup.exe` must show `Valid`. Tested with 0.40.14. Ollama
   auto-updates and starts at login; fine for v1, revisit pinning at v1-4.
3. If Ollama was already running, quit it (tray icon → Quit) and start it again so it reads the variables.
4. **Verify:**
   ```powershell
   Get-NetTCPConnection -LocalPort 11434 -State Listen | Select-Object LocalAddress   # 127.0.0.1 only
   Select-String "$env:LOCALAPPDATA\Ollama\server.log" -Pattern "cloud disabled|inference compute" | Select-Object -Last 2
   ```
   Want: `127.0.0.1`, `Ollama cloud disabled: true`, and your GPU in the `inference compute` line
   (`CUDA`, `ROCm` or `Vulkan`). On the example PC: CUDA on the 4080 SUPER.

## 4. Adding a model
**Memory rule:** model file + context (KV cache) + ~1.5 GB headroom < **your GPU memory** (16 GB on
the example PC). GGUF tags. Start contexts at 8K–16K.

**Safeguard check (before offering or updating any model).** Report these with
the size and capabilities, and say plainly what couldn't be verified:
- **License:** read the license layer on ollama.com (`ollama show --license <tag>` after a pull). Flag
  use restrictions or acceptable-use policies, terms the maker can change later, commercial or
  user-count limits, and attribution or naming rules. If there's no license layer, find it at the source.
- **Watermarking:** search "<model> watermark / SynthID". Open weights running locally usually carry
  none (sampling-time watermarks live in a provider's servers), but some research methods embed one
  in the weights, so check the model card.
- **Built-in behavior:** a hidden system prompt (`ollama show --system <tag>`), URLs in the template,
  or refusal tuning that would break the tasks you use it for (e.g. PII redaction).

1. **You approve** the exact tag and size.
2. Pull: `ollama pull <tag>`
3. Verify the files (**WSL**, models on D:):
   ```bash
   bash services/ollama/verify-model.sh <tag> /mnt/d/ai/ollama
   ```
4. **Isolated first load** in a `--network none` container, models mounted read-only (add `-NoGpu`
   for AMD or Intel GPUs, see §1):
   ```powershell
   pwsh -File services\ollama\firstload.ps1 -Model <tag>
   ```
   Pass = a sensible answer, and on NVIDIA `ollama ps` showing **100% GPU**.
5. **Tool-call check** on the host (tools are required for chat models):
   ```powershell
   pwsh -File services\ollama\toolcheck.ps1 -Model <tag>
   ```
   Pass = `PASS calls the tool with the right argument`. It also shows how much runs on the GPU.
   Only then use the model.

**Replacing an older version.** When a newer version arrives (e.g. `qwen3.6` → `qwen3.8`),
decide whether to delete the old one, and confirm before deleting:
- **Space:** how much it frees vs. free disk (`Get-PSDrive D`).
- **Keep it until the new one has proven itself:** it has passed the file check, first load and tool
  check, and the v1-1 eval if it's a primary or fast model. The old one is the rollback.
- **Nothing still uses it:** `router/` config, `skills/models/<model>/SKILL.md`, Open WebUI's default
  model, and the "Current models" table below.
- **Deleting:** `ollama rm <old-tag>`. Re-pulling the *same* tag replaces it in place, and Ollama cleans up
  the old files itself, so there's nothing to delete in that case.

## 5. Open WebUI
Pull at least one model first (§4), so there's something to chat with.
1. **Install once** (downloads ~2 GB of hash-checked packages):
   ```powershell
   $env:UV_PROJECT_ENVIRONMENT = "D:\ai\open-webui\venv"; uv sync --project services\open-webui --locked --python 3.12
   ```
2. **Start** (leave the window open; Ctrl+C stops it):
   ```powershell
   pwsh -File services\open-webui\start.ps1
   ```
3. Open http://127.0.0.1:8080 on the PC and **create the admin account straight away**. The first
   account becomes admin; anyone after that waits for approval.
4. **Publish it to your tailnet only** (HTTPS on 443, from §2.5). Open WebUI itself stays on 127.0.0.1:
   ```powershell
   tailscale serve --bg 8080
   ```
   `tailscale serve status` shows the address, e.g. `https://<your-pc>.<your-tailnet>.ts.net`.
See [`services/open-webui/README.md`](../../services/open-webui/README.md).

## 6. Reach it from your Mac and phone
1. **Mac:** put the PC's address from §5.4 in `services/tailscale/config.json` (`homenodeHost`), then
   `git commit -am "Tailscale host"` and `git push`. On the Mac: `git pull`, then
   `bash services/tailscale/check-edge.sh`. Pass = HTTPS answers and every other port is blocked.
2. **Phone:** install **Tailscale** (App Store / Google Play), sign in with the same account, approve
   the phone in the admin console (device approval), then open the address from §5.4 in the
   browser. Tip: **Share → Add to Home Screen** for an app-like icon.

## 7. Secrets
Provider keys live in **Windows Credential Manager**, read with Python `keyring` by the v1-4
launcher and passed only to LiteLLM. You store them yourself.

## Example models (author's hardware; yours will differ)
| Tag | Size | First load (container) | Speed |
|---|---|---|---|
| `gpt-oss:20b` | 13 GB | Passed 2026-11-03: 100% GPU, 12 GB at 8K | 136 tok/s |
| `gemma4:12b` | 8 GB | Passed 2026-11-03: 100% GPU, ~8.7 GB | 147–160 tok/s |
