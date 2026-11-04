# PC setup path: Your PC (home node)

**Role:** home node. Runs every service: Ollama, Open WebUI, and later the LiteLLM gateway, MCP
server, evals and scheduled jobs. Holds all provider API keys.
**Hardware (example):** Windows 11 Home, RTX 4080 SUPER (16 GB VRAM), 32 GB RAM.
**Shell:** PowerShell 7 by default. Say clearly when a step runs in WSL2 (Ubuntu) instead.
**Paths:** repo at `C:\projects\local-ai`; large data on `D:\ai`.

The Mac path is in [MAC.md](MAC.md). For the differences at a glance, see the table in [../SETUP.md](../SETUP.md).
These are the steps in order. Run each verify check before moving on.

---

## 1. Base
| Item | Check |
|---|---|
| NVIDIA driver | `nvidia-smi` shows 16 GB |
| WSL2 + Ubuntu | GPU visible inside WSL (`nvidia-smi` in Ubuntu) |
| uv, Git for Windows, PowerShell 7, gh, Claude Code | `uv --version`, `git --version`, `claude doctor` |
| gitleaks + pre-commit hook (`gitleaks git --pre-commit --staged`) | A fake key in a scratch repo is blocked |
| Docker Desktop (WSL2 backend) | Needed for the first-load check in step 4 |

## 2. Tailscale (home node)
1. Install, sign in with GitHub (two-factor on), turn on **device approval**.
2. Tag Your PC `tag:homenode` (admin console → Machines → Edit ACL tags).
3. Apply [`services/tailscale/policy.hujson`](../../services/tailscale/policy.hujson): your devices
   may reach Your PC on 443 (Open WebUI) and 4000 (gateway, v1-4) only.
4. Turn on HTTPS certificates, then publish Open WebUI tailnet-only with `tailscale serve` →
   `127.0.0.1:8080` (see `tailscale serve --help`). Open WebUI itself stays on 127.0.0.1.
5. Verify from the Mac: `bash services/tailscale/check-edge.sh`.

## 3. Ollama
1. Official installer from ollama.com; read it and verify its signature before running. Tested with 0.40.14. It
   auto-updates and starts at login, which is fine for v1; revisit pinning at v1-4.
2. User environment variables (set before first start):
   | Variable | Value | Why |
   |---|---|---|
   | `OLLAMA_NO_CLOUD` | `1` | Cloud features off |
   | `OLLAMA_MODELS` | `D:\ai\ollama` | Models off the system drive and out of the repo |
   | `OLLAMA_KEEP_ALIVE` | `1h` (optional) | Keeps a model loaded longer; holds ~12 GB VRAM |
3. Verify in `server.log`: listening on `127.0.0.1:11434` only, `Ollama cloud disabled: true`, CUDA on the 4080 SUPER.

## 4. Adding a model
**Memory rule:** model file + context (KV cache) + ~1.5 GB headroom < **16 GB VRAM**. GGUF tags.
Start contexts at 8K–16K.

**Safeguard check (before offering or updating any model).** Report these with
the size and capabilities, and say plainly what couldn't be verified:
- **License:** read the license layer on ollama.com (`ollama show --license <tag>` after a pull). Flag
  use restrictions or acceptable-use policies, terms the maker can change later, commercial or
  user-count limits, and attribution or naming rules. If there's no license layer, find it at the source.
- **Watermarking:** search "<model> watermark / SynthID". Open weights running locally usually carry
  none (sampling-time watermarks live in a provider's servers), but some research methods embed one
  in the weights, so check the model card.
- **Built-in behavior:** a hidden system prompt (`ollama show --system <tag>`), URLs in the template,
  or refusal tuning that would break contact-center tasks such as PII redaction.

1. **You approve** the exact tag and size.
2. Pull: `ollama pull <tag>`
3. Verify the files (WSL2, models on D:):
   ```bash
   bash services/ollama/verify-model.sh <tag> /mnt/d/ai/ollama
   ```
4. **Isolated first load** in a `--network none` container, with the GPU passed through and models
   mounted read-only:
   ```powershell
   pwsh -File services\ollama\firstload.ps1 -Model <tag>
   ```
   Pass = a sensible answer and `ollama ps` showing **100% GPU**. Only then use it on the host.

**Replacing an older version.** When a newer version arrives (e.g. `qwen3.6` → `qwen3.8`),
decide whether to delete the old one, and confirm before deleting:
- **Space:** how much it frees vs. free disk (`free space on D:`).
- **Keep it until the new one has proven itself:** it has passed the file check and first load, and the
  v1-1 eval if it's a primary or fast model. The old one is the rollback.
- **Nothing still uses it:** `router/` config, `skills/models/<model>/SKILL.md`, Open WebUI's default
  model, and the "Current models" table below.
- **Deleting:** `ollama rm <old-tag>`. Re-pulling the *same* tag replaces it in place, and Ollama cleans up
  the old files itself, so there's nothing to delete in that case.

## 5. Open WebUI
```powershell
pwsh -File services\open-webui\start.ps1
```
Binds 127.0.0.1:8080, Ollama only, offline mode, sign-ups closed after the first (admin) account.
See [`services/open-webui/README.md`](../../services/open-webui/README.md).

## 6. Secrets
Provider keys live in **Windows Credential Manager**, read with Python `keyring` by the v1-4
launcher and passed only to LiteLLM. You store them yourself.

## Example models (author's hardware; yours will differ)
| Tag | Size | First load (container) | Speed |
|---|---|---|---|
| `gpt-oss:20b` | 13 GB | Passed 2026-11-03: 100% GPU, 12 GB at 8K | 136 tok/s |
| `gemma4:12b` | 8 GB | Passed 2026-11-03: 100% GPU, ~8.7 GB | 147–160 tok/s |
