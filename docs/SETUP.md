# Setup and daily rhythm

The plan's rules, scope and security guardrails travel with the code in `AGENTS.md`. Claude Code loads it through `CLAUDE.md`, and Codex, Cline and goose can read it directly.

## What's in here
| Path | What it's for |
|---|---|
| `AGENTS.md` | Standing instructions for every agent: who you are, v1 scope, machine rules, security rules, where data lives |
| `CLAUDE.md` | One line, `@AGENTS.md`, so Claude Code loads the same rules |
| `STATUS.md` | Current step, next steps (with the machine they need), the v1 checklist, and the session log. This is what lets you switch devices mid-build |
| `docs/V1-SPEC.md` | The condensed build spec: 7 v1 steps, Handoff Packet, security rules |
| `docs/setup/PC.md`, `docs/setup/MAC.md` | Step-by-step setup for each OS. The differences are summarized below |
| `prompts/PROMPTS.md` | Copy-paste prompts, including one kickoff per v1 step |
| `.claude/settings.json` | Blocks Claude Code from reading `.env`/secrets, force-pushing, or pushing to `main`. |
| `evals/`, `skills/`, `router/`, `services/`, `logs/`, `outputs/` | Empty until the v1 step that fills them (each has a README) |

Large data lives outside the repo: `D:\ai` on Your PC, `~/.ollama` on the Mac. See *Where things live* in `AGENTS.md`.

## How "any device" works
Keep your copy of the repo in a **private** Git repository. `STATUS.md` and git push/pull carry state between devices.

- **Your PC** does anything that installs or runs services (Ollama, Open WebUI, LiteLLM, MCP server, evals).
- **Your Mac** is fine for writing code, tests, skill guides and docs, and for testing Your PC's services over Tailscale. It can also run local models of its own, under the same security rules.
- Agents check `hostname` before install steps.

## One-time setup: pick your path
Each machine has its own setup path, because Windows and macOS differ in more than shell syntax.

- **Your PC (Windows PC, home node):** [docs/setup/PC.md](setup/PC.md)
- **Mac (macOS, edge device + local models):** [docs/setup/MAC.md](setup/MAC.md)

### What differs between the two
| Topic | PC: Your PC | Mac: Mac |
|---|---|---|
| Role | Home node: every service, all API keys | Edge device, plus local models for offline/travel/coding |
| Shell | PowerShell 7 (`.ps1`); WSL2 when needed | zsh; repo scripts run as `bash <script>` |
| Install tools | Official installers / winget | Homebrew |
| GPU | NVIDIA RTX 4080 SUPER, 16 GB VRAM, CUDA | Apple M5 Pro, 48 GB shared memory, ~37 GB usable by the GPU, Metal |
| Model format | GGUF | `-mlx` tags preferred (MLX engine); GGUF also works |
| Memory rule | file + context + 1.5 GB < 16 GB | file + context + 6 GB < ~30 GB |
| Model store | `D:\ai\ollama` | `~/.ollama/models` |
| Cloud off | User env var `OLLAMA_NO_CLOUD=1` | `~/.ollama/server.json` → `disable_ollama_cloud` |
| Installer check | Script signature | App signed by Ollama + notarized by Apple (`check-mac.sh`) |
| Settings check | `server.log` | `bash services/ollama/check-mac.sh` |
| Model file check | `verify-model.sh` in WSL2 | `bash services/ollama/verify-model.sh <tag>` |
| **Isolated first load** | Docker `--network none` + GPU (`firstload.ps1`) | macOS sandbox, no network + GPU (`firstload-mac.sh`). Docker can't: no Apple GPU or MLX in its Linux VM |
| Everyday outbound control | None yet | LuLu per-app firewall (recommended) |
| Open WebUI | `start.ps1`; 127.0.0.1:8080, published to the tailnet on 443 | `start-mac.sh`; 127.0.0.1:8080, this Mac only, for the Mac's own models |
| Tailscale | Tagged `homenode`; `tailscale serve` publishes Open WebUI on 443 | Client only; verify with `check-edge.sh` |
| Secrets | Windows Credential Manager | macOS Keychain (edge key only) |
| gitleaks | Pre-commit hook (`docs/setup/PC.md` §1) | Pre-commit hook (`docs/setup/MAC.md` §2) |
| Line endings | `.ps1` CRLF | `.sh`, `.sb` LF (`.gitattributes`) |

## Your rhythm
1. On whatever device you're at: `git pull`, start your agent (e.g. `claude`) and paste **Start any session** from `prompts/PROMPTS.md`.
2. Work one checklist item at a time, and run each verify check yourself.
3. Before you walk away, paste **End any session**: it updates `STATUS.md`, commits and pushes your branch.
4. On the next device, `git pull` and start again.

## Things only you should do
- Store API keys. The agent gives you the `keyring`/Credential Manager command, and you paste the key into your own terminal, never into chat.
- Approve every model download (on either machine).
- Set provider-side spend limits in each provider's console.
- Merge branches into `main` after reviewing.
