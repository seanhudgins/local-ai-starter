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
`modelcheck.py verify`, then firstload-mac.sh, before I use it. After each step, give me
the verify check and wait for my result.
```

## v1-1 Bake-off + skill guides
```
Phase: v1-1 Bake-off + skill guides (docs/V1-SPEC.md).
Goal: evidence-based primary and fast model per machine, and a skill guide for each.
Step 0: move the model-check logic (tool-call test, answer check, sha256 verify, embedding check) into
services/ollama/modelcheck.py with pytest tests, make the first-load scripts call it, and add ruff +
pytest to CI.
Step 1: draft 20–30 synthetic eval items as JSONL in evals/sets/ covering the 8 task types in V1-SPEC,
each with an answer key. Fake names/DOBs/MRNs only. Show me 3 before writing the rest.
Step 2: one eval runner (Python, uv, pytest-tested, openai client against the OpenAI-compatible API,
reusing modelcheck.py): rule checks first (valid JSON, required fields, redaction regex), a grader
model only for judgment items, a tool-call reliability score; stamp the Ollama version and model
digest on every result and store results in SQLite (evals/results.db).
Step 3: run every installed model on this machine; tell me which machine to switch to for the rest.
Write logs/benchmarks.md from SQL queries and a results table for the README.
Step 4: for each chosen model, write skills/models/<model>/SKILL.md from the results only.
```

## v1-2 Gateway
```
Phase: v1-2 Gateway.
Build: LiteLLM in Docker (image pinned by digest) on your PC, in front of Ollama + Anthropic,
Google and OpenRouter.
- A launcher reads keys from Windows Credential Manager with keyring (names: localai/anthropic,
  localai/google, localai/openrouter) and passes them only to the container. Give me the commands to
  store each key myself; never ask me to paste a key into chat.
- Virtual keys with budgets for: open-webui, goose, cline, mcp-local. Aliases `auto`, `auto-coding`.
- Per-call, daily, monthly caps.
Before coding, ask me what caps I want. After, point Open WebUI, goose and Cline at the gateway and
show me a test that proves a call over the cap is refused.
```

## v1-3 Handoff both ways
```
Phase: v1-3 Handoff both ways.
Build: (1) a JSON schema + validator for the Handoff Packet in docs/V1-SPEC.md; (2) an MCP server
exposing ask_local_model(task, input, output_schema) that calls an OpenAI-compatible endpoint URL
from config (gateway on your PC, local Ollama on the Mac) and returns a response packet;
(3) escalate_to_cloud through the gateway with the simple tier table, logging to
SQLite (logs/escalations.db) with no raw content; (4) skills/delegate-to-local/SKILL.md.
Rules: Python with uv; validate input and output; reject malformed packets; no secrets in code.
Before coding, ask me questions. After, write tests and show me how to connect the server to Claude
Code on my Mac.
```

## v1-4 Demo + ops
```
Phase: v1-4 Demo + ops.
(1) An end-to-end flow I can record in 3 minutes, with a small UI (ask me: TypeScript web front end or Gradio): synthetic transcript → local redaction + summary →
Claude QA scoring and coaching only on low-confidence cases. (2) A GPU benchmark report (tokens/sec,
watts from nvidia-smi, $/task at my electricity rate) in outputs/benchmarks/. (3) Ops: Open WebUI and
LiteLLM start at boot, a power policy for your PC, and a backup of Open WebUI data, evals and skills
with a restore test. One item at a time, with verify checks.
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
