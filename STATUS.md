# local-ai: status

_Last updated: (date)_

Every agent reads this first and updates it at the end of every session. This file is how work
moves between devices: whatever machine you open next, it says where you left off.

## Current step
**v1-0 Secure base**: not started

## Next steps
- Machine: **Your PC**
- Start with the v1-0 prompt in `prompts/PROMPTS.md`, following `docs/setup/PC.md`.

## Last worked on
- (nothing yet)

## Open problems / decisions
- (none yet)

## v1 checklist
### v1-0 Secure base [Your PC]
- [ ] NVIDIA driver updated; `nvidia-smi` shows your GPU memory
- [ ] WSL2 + Ubuntu; GPU visible inside WSL
- [ ] uv, Git, PowerShell 7, gh
- [ ] Claude Code installed and logged in on Your PC and Your Mac
- [ ] Repo in a **private** Git repository, cloned on each device
- [ ] gitleaks pre-commit hook on each device
- [ ] Tailscale on Your PC, Your Mac, phone; MFA on; deny-by-default policy tested; device approval on
- [ ] Ollama installed, bound to 127.0.0.1; models pulled with your OK; first load passed with no network
- [ ] Open WebUI running; admin created; sign-ups off; reachable only over Tailscale
- [ ] Verified: chat from Mac + phone; `bash services/tailscale/check-edge.sh` passes

### Your Mac: local models (optional)
- [ ] Ollama app: cloud off, localhost only (`check-mac.sh` passes)
- [ ] Per-app firewall (e.g. LuLu) blocks Ollama except during approved downloads
- [ ] Each model: `modelcheck.py verify` + `firstload-mac.sh` pass (incl. tool call)
- [ ] Open WebUI on the Mac (`start-mac.sh`), admin created

### v1-1 Bake-off + skill guides [Your PC + Your Mac]
- [ ] Refactor checks into `services/ollama/modelcheck.py` (pytest); `ruff` + `pytest` in CI
- [ ] Eval set (20–30 synthetic items, JSONL with answer keys) in `evals/sets/`
- [ ] Eval runner: rule checks + grader, tool-call reliability, Ollama version + digest stamped, results in SQLite, pytest-tested
- [ ] Every installed model run on both machines; `evals/results.db`, `logs/benchmarks.md` (SQL), README results table
- [ ] Primary + fast model chosen per machine
- [ ] One `skills/models/<model>/SKILL.md` per chosen model

### v1-2 Gateway [Your PC]
- [ ] Keys stored in Credential Manager (you do this yourself)
- [ ] LiteLLM in Docker, pinned by digest; launcher passes keys via keyring
- [ ] Virtual keys + budgets per client; aliases; caps; provider-side limits set
- [ ] Open WebUI, goose, Cline → gateway; a call over the cap is refused

### v1-3 Handoff both ways
- [ ] Handoff Packet schema + validator
- [ ] `ask_local_model` MCP server (endpoint URL from config)
- [ ] `escalate_to_cloud` + `logs/escalations.db` (SQLite)
- [ ] `delegate-to-local` skill
- [ ] Verified from Your Mac over Tailscale

### v1-4 Demo + ops [Your PC]
- [ ] Recorded end-to-end demo with a UI (TypeScript or Gradio); GPU benchmark report
- [ ] Open WebUI + LiteLLM start at boot; PC power policy
- [ ] Backup of Open WebUI data, evals, skills + restore test

## Session log
<!-- newest first: date · machine · what changed · verified? -->
