# Prompts to paste into Claude Code

Paste these into Claude Code (terminal, desktop app, or VS Code) from inside the `local-ai` folder.
Fill in the `[brackets]`. Every agent loads `AGENTS.md` (Claude Code via `CLAUDE.md`), so you don't need to repeat the rules.

---

## 0. Start any session (any device)
```
Read STATUS.md and docs/V1-SPEC.md. Run `hostname` and tell me which machine we're on.
Then tell me: the current step, the next action, and whether it can be done on this machine.
If it can't, tell me which machine to switch to and what I can usefully do here instead.
Ask me any questions before you start changing things.
```

## End any session (any device)
```
We're stopping here. Update STATUS.md (checklist boxes, "Current step", "Next action" with the
machine it needs, and a one-line session log entry). Commit on our working branch with a clear
message and push it. Then tell me in one line where to pick up and on which machine.
```

## Pick up on a different device
```
I'm switching from [Your PC / my Mac] to this machine. Pull the latest from GitHub,
read STATUS.md, and confirm what's next and whether this machine can do it.
```

---

## v1-0 Secure base (run on your PC)
```
Phase: v1-0 Secure base (see docs/V1-SPEC.md and the v1-0 checklist in STATUS.md).
Goal: I can chat with a local model from my Mac and phone over Tailscale, and nothing else
on your PC is reachable.
Current state: [e.g. "Claude Code installed, nothing else yet"]
Please walk me through it one checklist item at a time, in this order: driver check, WSL2, uv/Git,
gitleaks, Tailscale (MFA, deny-by-default ACL, device approval) BEFORE Ollama or Open WebUI.
For the Tailscale ACL, write the policy file for me and explain each rule.
Before each command, say whether it's PowerShell or WSL. After each item, give me a verify check
and wait for my result before moving on.
```

## Mac setup or new Mac model (run on the Mac)
```
Read docs/setup/MAC.md and STATUS.md. Run `hostname` to confirm we're on the Mac.
Then walk me through [the next unfinished step / adding the model <tag>] one step at a time.
Ask before any model pull, and tell me its size first. Every new model gets
verify-model.sh, then firstload-mac.sh, before I use it. After each step, give me
the verify check and wait for my result.
```

## v1-1 Model bake-off
```
Phase: v1-1 Bake-off.
Goal: evidence-based pick of a primary (~12–14B) and fast (~3–8B) local model for contact-center tasks.
Step 1: draft 20–30 synthetic eval items in evals/sets/ covering the 8 task types in V1-SPEC,
each with an answer key. Use fake names/DOBs/MRNs that clearly aren't real. Show me 3 before writing the rest.
Step 2: write one eval script (uv, pytest-tested) that runs rule checks first (valid JSON, required
fields, redaction regex) and calls a grader model only for judgment items.
Step 3: search for current open-weight candidates that fit 16 GB VRAM, list 3–5 with expected VRAM,
license, and tool-calling support, and wait for my OK before any model is pulled.
```

## v1-2 Model skill guides
```
Phase: v1-2 Skill guides.
Using evals/scores.json and logs/benchmarks.md, write skills/models/<model>/SKILL.md for
[primary model] and [fast model], using one consistent template (strengths, failure modes, prompt format, escalation rules, one worked example).
Every strength and weakness must cite eval results. Include one Handoff Packet that worked.
```

## v1-3 Claude → local (MCP)
```
Phase: v1-3 Claude → local.
Build: (1) a JSON schema + validator for the Handoff Packet in docs/V1-SPEC.md;
(2) a small MCP server exposing ask_local_model(task, input, output_schema) that calls the local
model and returns a response packet; (3) skills/delegate-to-local/SKILL.md saying when to delegate.
Rules: Python with uv; validate input and output; reject malformed packets; no secrets in code.
Before coding, ask me questions. After coding, write tests and show me how to connect the server
to Claude Code on my Mac over Tailscale.
```

## v1-4 Gateway + local → cloud
```
Phase: v1-4 Gateway.
Build: LiteLLM proxy on your PC in front of Ollama + Anthropic, Google, and OpenRouter.
- Pin LiteLLM by version and hash.
- A service launcher reads keys from Windows Credential Manager with keyring (names: localai/anthropic,
  localai/google, localai/openrouter) and passes them only to the LiteLLM process. Give me the
  commands to store each key myself; never ask me to paste a key into chat.
- Virtual keys with budgets for: open-webui, goose, cline, mcp-local.
- Routing aliases `auto` and `auto-coding`; a simple tier table for escalate_to_cloud.
- Per-call, daily, monthly caps; log escalations to logs/escalations.csv with no raw content.
Before coding, ask me what caps I want. After, show me how to point Open WebUI and goose at the gateway,
and a test that proves a call over the cap is refused.
```

## v1-5 Demo + benchmark
```
Phase: v1-5 Demo.
Build an end-to-end flow: synthetic transcript → local redaction + summary → Claude QA scoring
and coaching only on cases the local model marks low-confidence. Then a GPU benchmark report
(tokens/sec, watts from nvidia-smi, $/task at your electricity rates) in outputs/benchmarks/.
Make it something I can show in a 3-minute screen recording.
```

## v1-6 Simple automation
```
Phase: v1-6 Automation.
Build: (1) a once-per-day price refresh from LiteLLM's price map / OpenRouter's models API with a
refreshed_on check; (2) a fixed peak-hours rule that schedules batch jobs out of your utility's peak window (e.g. weekdays 5–8 p.m.)
using your PC's clock; (3) Cline in VS Code pointed at the gateway; (4) restic encrypted backups
to an external drive and an offsite bucket, plus a restore test. One item at a time, with verify checks.
```

---

## When something breaks (any step)
```
Phase: [v1-x]
Goal: [what should be working]
What I did: [steps]
Error or output: [paste — remove any keys first]
Machine: [Your PC / Mac] (setup paths: docs/setup/PC.md, docs/setup/MAC.md)
Explain what the error means in plain terms, then give me the fix and a verify check.
```
