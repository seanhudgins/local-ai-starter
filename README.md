# local-ai starter

[![checks](https://github.com/seanhudgins/local-ai-starter/actions/workflows/checks.yml/badge.svg)](https://github.com/seanhudgins/local-ai-starter/actions/workflows/checks.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Run open-weight AI models on your own hardware, reach them privately from your other devices, and
hand work back and forth between local models and Claude. Built step by step with a coding agent
(Claude Code), with security checks at every step. Written for beginners; tested on one Windows PC
and one Mac.

**What you get (v1-0, secure base):**
- **Your PC** (NVIDIA, AMD or Intel GPU) runs [Ollama](https://ollama.com) and [Open WebUI](https://openwebui.com),
  reachable from your other devices over [Tailscale](https://tailscale.com) and nothing else.
- **Your Mac** (Apple silicon, or Intel for small models) can run its own models, with browser chat on the Mac only.
- Every new model: sha256-checked, then first loaded with **no network** (Docker on the PC, a macOS
  sandbox on the Mac), and chat models must pass a real **tool-call test**.
- Secrets never in files; gitleaks blocks commits that contain them.

**Example use case:** the evals and prompts use contact-center work (call summaries, intent
detection, PII redaction, QA scoring) with **synthetic** data. Swap in your own tasks.

Later steps (model bake-off, Claude ↔ local handoff, LiteLLM gateway with spend caps) are in
[`docs/V1-SPEC.md`](docs/V1-SPEC.md).

**How it's built and why:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (diagram, security layers, design decisions, measured speeds).

## Start
1. **New to this?** [`docs/GETTING-STARTED.md`](docs/GETTING-STARTED.md): accounts, terminal basics,
   folder layout, installing every tool (Docker, Tailscale, LuLu, …) and getting your own private copy.
2. Then follow [`docs/setup/PC.md`](docs/setup/PC.md) and/or [`docs/setup/MAC.md`](docs/setup/MAC.md)
   ([`docs/SETUP.md`](docs/SETUP.md) compares the two).
3. Track progress in [`STATUS.md`](STATUS.md). Rules for your coding agent are in [`AGENTS.md`](AGENTS.md).
4. With Claude Code, paste the prompts in [`prompts/PROMPTS.md`](prompts/PROMPTS.md) to go one step at a time.

## Make it yours
| File | Change |
|---|---|
| `services/tailscale/config.json` | `homenodeHost`: your PC's Tailscale name (`<your-pc>.<your-tailnet>.ts.net`) |
| `services/tailscale/policy.hujson` | `tests` → `src`: your Tailscale login (`<you>@github` or similar) |
| `services/ollama/config.json`, `services/open-webui/config.json` | Data paths on your PC (default `D:\ai\...`) |
| `services/open-webui/config-mac.json` | Data paths on your Mac (default `~/ai/...`) |

The docs use the author's hardware as the worked example (RTX 4080 SUPER 16 GB; M5 Pro 48 GB).
Size models for yours with the memory rules in each setup guide.

## Run it
**Mac** (from the repo folder)
```zsh
bash services/open-webui/start-mac.sh     # browser chat → http://127.0.0.1:8080 (Ctrl+C stops)
ollama run <model>                        # Terminal chat (/bye exits)
bash services/ollama/check-mac.sh         # safety check
```

**PC** (PowerShell 7, from the repo folder)
```powershell
pwsh -File services\open-webui\start.ps1                 # then https://<your-pc>.<your-tailnet>.ts.net
pwsh -File services\ollama\firstload.ps1 -Model <tag>    # first load of a new model
```

**Using tools** (local models calling functions): Open WebUI (model → Advanced Params → Function
Calling = Native), Cline or goose (provider Ollama, `http://127.0.0.1:11434`), or your own code via the
OpenAI-compatible API at `http://127.0.0.1:11434/v1`. Review any tool, extension or MCP server before
installing it.

## Ground rules
Synthetic data only. Models stay on localhost. Nothing is reachable from other devices until Tailscale
MFA, a deny-by-default policy and device approval are in place. You approve every model download.

## License
[MIT](LICENSE). Models you download have their own licenses; the setup guides show how to check them.
