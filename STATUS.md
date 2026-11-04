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
- [ ] Each model: `verify-model.sh` + `firstload-mac.sh` pass (incl. tool call)
- [ ] Open WebUI on the Mac (`start-mac.sh`), admin created

### v1-1 Bake-off
- [ ] Eval set (20–30 synthetic items) in `evals/sets/`
- [ ] Eval script with rule checks + grader
- [ ] 3–5 candidates tested; results in `evals/scores.json`, `logs/benchmarks.md`
- [ ] Primary + fast models chosen

### v1-2 Model skill guides
- [ ] One `skills/models/<model>/SKILL.md` per chosen model

### v1-3 Claude → local
- [ ] Handoff Packet schema + validator
- [ ] `ask_local_model` MCP server
- [ ] `delegate-to-local` skill
- [ ] Verified from Your Mac over Tailscale

### v1-4 Gateway + local → cloud
- [ ] Keys stored in Credential Manager (you do this yourself)
- [ ] LiteLLM pinned; launcher reads keys via keyring
- [ ] Virtual keys + budgets per client; routing aliases
- [ ] `escalate_to_cloud` + caps + `logs/escalations.csv`
- [ ] Provider-side spend limits set

### v1-5 Demo + benchmark
- [ ] End-to-end contact-center demo
- [ ] GPU benchmark report

### v1-6 Simple automation
- [ ] Daily price refresh (once/day)
- [ ] Peak-hours rule for batch jobs
- [ ] Cline → gateway
- [ ] restic backups (external drive + offsite) + restore test

## Session log
<!-- newest first: date · machine · what changed · verified? -->
