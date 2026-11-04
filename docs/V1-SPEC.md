# V1 Spec — Local AI on your PC

This is what Claude Code builds. Everything not listed here is **Later**.

## Goals v1 must deliver
1. Local open-weight models with skills and a harness, usable from your devices.
2. Two-way handoff: Claude → local (`ask_local_model` MCP tool) and local → cloud (`escalate_to_cloud` via the gateway).
3. A skill guide per chosen open-weight model.
4. Cost-aware, secure, and mostly automated.

## Decisions already made (don't re-ask)
- Use hardware you already own first; keep cloud spend small and capped.
- v1 devices: **Your PC** (home node, NVIDIA GPU) + **Your Mac** (edge device that can also run its own local models), plus a phone/tablet via browser.
- Cloud API keys to start: **Anthropic, Google (Gemini), OpenRouter** (OpenRouter for DeepSeek/Mistral/etc., synthetic or redacted data only).
- Stack: Ollama → **LiteLLM** gateway → clients (**Open WebUI** for phone/tablet/browser, **goose** on laptop, **Claude Code + Cline** for coding). VS Code optional.
- Electricity: batch jobs auto-scheduled out of your utility's peak window with a notice; ask only when a big job is started interactively during peak.
- **Mac local models:** the Mac may run Ollama for offline/travel use, bigger models and coding, under the same security rules (`docs/setup/MAC.md`). Your PC stays the only home for the gateway, MCP server, evals and provider keys.

## Build order
| Step | Machine | What | Done when |
|---|---|---|---|
| **v1-0** Secure base | **[Your PC]** + each device | Done 2026-11-04. Tailscale (MFA, deny-by-default policy, device approval), Ollama on 127.0.0.1, Open WebUI published tailnet-only; Mac runs its own models behind a per-app firewall; every model hash-checked, first-loaded with no network, tool-call tested | Chat from Mac and phone over Tailscale; `check-edge.sh` shows only 443 open |
| **v1-1** Bake-off + skill guides | Runs on **[Your PC]** and the **Mac**; code anywhere | **First:** move the model-check logic into one tested Python module, `services/ollama/modelcheck.py` (tool-call test, answer check, sha256 verify, embedding check), so the first-load scripts only set up isolation and call it; add `ruff` and `pytest` to CI. Then 20–30 synthetic contact-center items (summary/disposition, intent, PII redaction, JSON extraction, 5-pt QA, escalation risk, follow-up draft, "local or escalate?") as JSONL with answer keys. One runner (Python, `uv`, pytest-tested, the `openai` client against Ollama's OpenAI-compatible API, reusing `modelcheck.py`): rule checks first, grader model only for judgment items, tool-call reliability counted, each result stamped with the Ollama version and model digest, stored in **SQLite** (`evals/results.db`). Run every installed model on both machines. Then one `skills/models/<model>/SKILL.md` per chosen model, filled only from the results | `evals/results.db`, `logs/benchmarks.md` built from SQL queries, a results table in the README; `ruff` + `pytest` green in CI; a **primary** and a **fast** model chosen per machine; each guide has measured strengths, failure modes, prompt format, escalation rules, one packet that worked |
| **v1-2** Gateway | **[Your PC]** | LiteLLM in Docker, image pinned by digest, in front of Ollama + Anthropic, Google, OpenRouter. Keys: Credential Manager → keyring launcher → container only. Per-client virtual keys with budgets (open-webui, goose, cline, mcp-local). Aliases `auto`, `auto-coding`. Per-call/daily/monthly caps; provider-side spend limits. Point Open WebUI, goose and Cline at it | Every client goes through the gateway; a call over the cap is refused; spend shows per key |
| **v1-3** Handoff both ways | Code anywhere; runs on each machine | Handoff Packet schema + validator (§Handoff Packet). MCP server `ask_local_model(task, input, output_schema)` that calls an OpenAI-compatible URL from config (the gateway on your PC; the Mac's own Ollama when offline). `escalate_to_cloud` through the gateway with the simple tier table; every escalation logged to **SQLite** (`logs/escalations.db`, no raw content), so spend per key and per day is a SQL query. `skills/delegate-to-local/SKILL.md` | From the Mac, Claude Code delegates a redaction task and gets valid JSON back; a malformed packet is rejected; an escalation is logged and capped |
| **v1-4** Demo + ops | **[Your PC]** | End-to-end demo (synthetic transcript → local redaction + summary → Claude QA/coaching on low-confidence cases), recorded, with a small UI: **TypeScript** web front end (the language contact-center AI roles ask for) or **Gradio** (pure Python); decide at v1-4. GPU benchmark report (tokens/sec, watts, $/task). Ops: Open WebUI and LiteLLM start at boot; PC power policy (no sleep, or Wake-on-LAN); optional Tailscale SSH so the PC is administered from the Mac; backup of Open WebUI data, evals and skills with a restore test | Recorded demo + report in `outputs/` (benchmark numbers from SQL queries); services survive a reboot; restore test passes |

**Each version ships a demo:** a screenshot or short recording in the README, and a tagged public release. That is the build story.

**Rule:** a step starts only when the previous one works end to end.

## Handoff Packet (shared contract, both directions)
```json
{
  "packet_version": "1.0",
  "task_id": "uuid",
  "from_agent": "local:<model> | claude",
  "to_agent": "claude | local:<model>",
  "task_type": "summarize | classify | extract | redact | reason | draft | review",
  "goal": "One sentence describing the outcome wanted",
  "input": "The content to work on",
  "context": "Only the background the receiver needs",
  "constraints": ["e.g. max 120 words", "no PHI in output"],
  "output_schema": { "type": "object", "properties": {} },
  "attempted": "What the sender already tried and why it failed (escalations only)",
  "confidence_required": "low | medium | high"
}
```
Response adds: `status` (done / partial / failed), `output`, `confidence` (0–1), `notes`.
Routing fields (complexity score, selected model, estimated cost, etc.) are added in v1-4 only as far as the simple tier table needs; the full routing block is Later.

## Complexity score (computed in code, 1–5)
Start at 1; +1 each: reason/review/code task · multi-step · ambiguous or judgment-heavy · high stakes (customer-facing, compliance) · local attempt already failed validation. A model may *propose* a score; code decides, and a model's score can only lower or match it, never raise it.

## Languages
Python for logic (typed, `ruff`-clean, pytest-tested, run with `uv`). Shell/PowerShell only as thin wrappers around OS tools (`sandbox-exec`, `docker`, `codesign`, service start-up). SQLite for anything queried later. One optional TypeScript piece: the v1-4 demo UI.

## Binding security rules (from the plan review)
- Keys: Windows Credential Manager → keyring → LiteLLM process only. Never env vars, `.env`, files, logs. gitleaks pre-commit.
- Model servers on localhost; gateway is the only entry; each client its own virtual key + budget.
- Tailscale ACL + MFA + device approval **before** exposing anything. Open WebUI admin created immediately; sign-ups off.
- Synthetic data only; work repos/data refused by every lane.
- Every model download needs your approval; files verified against their sha256; first load/eval in an isolated, no-network environment with models read-only (**PC:** `--network none` container; **Mac:** macOS sandbox, since Docker there has no GPU or MLX). GGUF/safetensors only (MLX models are safetensors).
- Pin dependencies: LiteLLM by image digest, Python by `uv.lock`, actions by commit SHA; checks run on every push. Review any MCP server, Open WebUI function, or plugin before installing.
- No AI path to PDU outlets, UniFi admin, or Home Assistant admin.
- Backups: Open WebUI data, evals and skills to the HDD with a restore test (v1-4); encrypted offsite is Later.

## Later (don't build in v1)
Daily price refresh (LiteLLM's price map updates with each release; refresh only if a stale price costs money) → peak-hours scheduling for your utility (once a batch job exists) → restic encrypted offsite backups → Model Selection Score with measured competency → Home Assistant Green → Context Vault → daily open-source scout (recommend-only) → coding router zones + subscription value report → full utility-rate engine → home-helper mode → device registry + phone run-local mode → exploration/replay/challenger statistics → agent groups C–E → NAS → AI node.

