# Getting started from zero

Do these once, in order. Then continue with [`setup/PC.md`](setup/PC.md) and/or [`setup/MAC.md`](setup/MAC.md).
Allow an afternoon, plus download time.

## 1. What you need
| | Suggested minimum | Tested with |
|---|---|---|
| **PC** (home node) | Windows 11; GPU with 8 GB+ memory (NVIDIA GeForce/RTX, AMD Radeon or Intel Arc); 16 GB RAM; 100 GB free disk | NVIDIA RTX 4080 SUPER 16 GB, 32 GB RAM |
| **Mac** (optional) | Apple silicon (M1 or later) with 16 GB+ memory; Intel Macs work for small models on the CPU; 60 GB free disk | M5 Pro, 48 GB |
| **Phone** (optional) | iPhone or Android, to chat from anywhere | iPhone |

NVIDIA is the smoothest path on a PC. AMD and Intel GPUs work through Ollama too; the PC guide's GPU
table shows what changes. No dedicated GPU? Ollama runs on the CPU, but only small models are usable.

**Accounts:**
- **GitHub** (free): holds your private copy of this project. Turn on two-factor authentication.
- **Tailscale** (free personal plan): sign in with GitHub, Google, Microsoft or Apple. Make sure that account has two-factor on, because it's your tailnet's MFA.
- **Claude** Pro or Max: Claude Code needs a paid plan (the free plan doesn't include it).
- Later, in step v1-4: API keys for the cloud models you choose. Not needed now.

## 2. Terminal basics
- **Mac:** open **Terminal** (Cmd+Space, type "Terminal").
- **PC:** open **Terminal** from the Start menu. After step 4, use the **PowerShell 7** tab (`pwsh`).
  "As administrator" means right-click Terminal → **Run as administrator**.
- Paste one block at a time and wait for it to finish. `cd <folder>` moves into a folder.
- After installing tools, **close and reopen** the terminal so it finds them.

## 3. Folder layout (decide once)
Two kinds of folders: the **repo** (code and docs, small, synced with Git) and **data** (models and
databases, large, never in Git).

| What | PC default | Mac default |
|---|---|---|
| Repo | `C:\projects\local-ai` | `~/projects/local-ai` |
| Models | `D:\ai\ollama` | `~/.ollama/models` (Ollama's default) |
| Open WebUI data | `D:\ai\open-webui` | `~/ai/open-webui` |
| Hugging Face cache | `D:\ai\hf` | — |

Create them:
```powershell
# PC (PowerShell). No D: drive? Use C:\ai here, and change the paths listed below to match.
New-Item -ItemType Directory -Force C:\projects, D:\ai\ollama, D:\ai\open-webui, D:\ai\hf
```
```zsh
# Mac
mkdir -p ~/projects ~/ai/open-webui
```

**Already have a projects folder** (e.g. `~/Developer`, `D:\dev`)? Put the repo there; nothing depends
on the repo's location. **Data somewhere else?** Change these, keeping data **outside** the repo:

| File | Setting |
|---|---|
| `services/ollama/config.json` | `modelsDir` (and the `OLLAMA_MODELS` variable in `setup/PC.md` §3) |
| `services/open-webui/config.json` | `dataDir`, `venvDir` (PC) |
| `services/open-webui/config-mac.json` | `dataDir`, `venvDir` (Mac) |

## 4. Install tools
**Don't install Ollama yet.** The setup guides do that after Tailscale is locked down.

### PC
1. **GPU driver** (Device Manager → Display adapters shows which GPU you have):
   - **NVIDIA GeForce/RTX:** latest Game Ready or Studio driver from https://www.nvidia.com/drivers
     (or the NVIDIA App). Check in Terminal: `nvidia-smi` lists your GPU and its memory.
   - **AMD Radeon:** latest AMD Software: Adrenalin Edition from https://www.amd.com/support.
   - **Intel Arc / Iris Xe:** latest driver via the Intel Driver & Support Assistant, https://www.intel.com/content/www/us/en/support/detect.html (it detects your GPU).
2. **WSL2 + Ubuntu** (Terminal **as administrator**): `wsl --install`, then restart Windows. Ubuntu
   opens and asks you to create a Linux username and password. Check: `wsl -l -v` shows `VERSION 2`.
3. **Everything else** (normal Terminal):
   ```powershell
   winget install --id Microsoft.PowerShell -e     # PowerShell 7: the scripts need it
   winget install --id Git.Git -e                  # Git
   winget install --id GitHub.cli -e               # gh: GitHub from the terminal
   winget install --id astral-sh.uv -e             # uv: installs Python + Open WebUI
   winget install --id Gitleaks.Gitleaks -e        # blocks commits that contain secrets
   winget install --id Docker.DockerDesktop -e     # isolated first load of new models
   winget install --id Tailscale.Tailscale -e      # private network between your devices
   winget install --id Anthropic.ClaudeCode -e     # Claude Code (your coding agent)
   ```
4. **Docker Desktop:** open it once and accept the terms. Settings → General: **Use the WSL 2 based
   engine** on. Settings → Resources → WSL integration: **Ubuntu** on. Check: `docker version`.
5. Reopen the terminal (PowerShell 7), then sign in: `gh auth login`, then `claude` (opens a browser).

### Mac
1. **Homebrew** (installs everything else). Run this, then the **Next steps** commands it prints
   (they differ on Apple silicon and Intel Macs):
   ```zsh
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. **Tools:**
   ```zsh
   brew install git gh uv gitleaks                 # Git, GitHub CLI, uv, secret scanner
   brew install --cask tailscale-app lulu          # private network; per-app firewall
   curl -fsSL https://claude.ai/install.sh | bash  # Claude Code
   ```
   Open **Tailscale** and **LuLu** once each and allow what macOS asks for (LuLu needs a network
   extension). Docker isn't needed on the Mac.
3. Sign in: `gh auth login`, then `claude` (opens a browser).

## 5. Get your own private copy
1. On this repo's GitHub page, click **Use this template → Create a new repository** and choose
   **Private**. (Don't fork: a fork of a public repo is public.)
2. Clone it into your repo folder and turn on the secret-scanning hook, on each device.
   `<you>/<your-repo>` is your GitHub username and the name you gave the copy (shown on its page).
   ```powershell
   # PC (PowerShell)
   gh repo clone <you>/<your-repo> C:\projects\local-ai
   cd C:\projects\local-ai
   git config core.hooksPath .githooks
   ```
   ```zsh
   # Mac
   gh repo clone <you>/<your-repo> ~/projects/local-ai
   cd ~/projects/local-ai
   git config core.hooksPath .githooks
   ```
   The hook blocks any commit containing a secret, and blocks all commits if gitleaks is missing.
   **Test it** (in the repo folder): make a file containing `github_token = "ghp_` followed by 36
   random letters and digits and a closing `"`, then `git add` it and `git commit -m test`. The
   commit must be refused. Then delete the file and `git reset`.
3. **Make it yours:** two Tailscale values get filled in during the PC guide: your login in
   `services/tailscale/policy.hujson` (PC guide §2) and your PC's address in
   `services/tailscale/config.json` (PC guide §6). To edit a file, open it in VS Code or Notepad.
   After a change: `git commit -am "<what changed>"` and `git push`; on your other devices, `git pull`.
4. **Branches, briefly:** your coding agent works on a separate *branch* and pushes it to GitHub.
   You review it there and click **Merge pull request** to bring it into `main`. Then `git pull`.

## 6. Next
- **PC first:** [`setup/PC.md`](setup/PC.md) (Tailscale, then Ollama, then Open WebUI, then your Mac and phone).
- **Mac:** [`setup/MAC.md`](setup/MAC.md).
- **With Claude Code:** in the repo folder run `claude`, paste **Start any session** from
  [`../prompts/PROMPTS.md`](../prompts/PROMPTS.md), and go one step at a time.
