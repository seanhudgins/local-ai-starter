# V1 Spec — Local AI on Your PC

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
| **v1-0** Secure base | **[Your PC]** + each device for Tailscale | Phase 0 setup (driver, WSL2, uv, Git, Claude Code, project folder + git, gitleaks pre-commit). **Tailscale first**: MFA, deny-by-default ACL (edge → only gateway/Open WebUI ports on Your PC; no device-to-device), device approval or Tailnet Lock. Then Ollama (127.0.0.1 only) + Open WebUI; create admin immediately, sign-ups off | You chat with a local model from your Mac and phone over Tailscale; a port scan from the Mac shows Ollama's 11434 is **not** reachable |
| **v1-1** Bake-off | **[Your PC]** for runs; code anywhere | 20–30 item synthetic contact-center eval set (summary/disposition, intent, PII redaction, JSON extraction, 5-pt QA, escalation risk, follow-up draft, "local or escalate?"). One eval script with rule checks first, grader model only for judgment items. Test 3–5 candidates that fit 16 GB; record accuracy, tokens/sec, VRAM, tool-calling reliability | `evals/scores.json` + `logs/benchmarks.md`; a **primary** (~12–14B) and **fast** (~3–8B) model picked |
| **v1-2** Model skill guides | Anywhere | One `skills/models/<model>/SKILL.md` per chosen model, using the template in `docs/plan` §9b, filled from v1-1 evidence | Each guide has measured strengths, failure modes, prompt format, escalation rules, and one example packet that worked |
| **v1-3** Claude → local | Code anywhere; run **[Your PC]** | Small MCP server exposing `ask_local_model(task, input, output_schema)` using the Handoff Packet (§6). Validator that rejects malformed packets. `skills/delegate-to-local/SKILL.md` | Claude Code on the Mac (over Tailscale) delegates a redaction task, gets valid JSON back; a malformed packet is rejected |
| **v1-4** Gateway + local → cloud | **[Your PC]** | LiteLLM proxy in front of Ollama + the 3 providers. Keys read from Credential Manager by a service launcher (keyring) and passed only to LiteLLM. Per-client virtual keys with budgets (Open WebUI, goose, Cline, MCP server). Routing aliases (`auto`, `auto-coding`). `escalate_to_cloud` with a simple tier table; costs from LiteLLM's built-in price map. Per-call/daily/monthly caps; log every escalation to `logs/escalations.csv` (no raw content). Provider-side spend limits set in each console | Open WebUI and goose both go through the gateway; a call over the per-call cap is refused; spend shows per virtual key |
| **v1-5** Demo + benchmark | **[Your PC]** | End-to-end: synthetic transcript → local redaction + summary → Claude QA/coaching on hard cases. GPU benchmark report (tokens/sec, watts, $/task) | Recorded demo + `outputs/benchmarks/` report |
| **v1-6** Simple automation | **[Your PC]** | Daily price refresh from LiteLLM price map / OpenRouter models API (once per day, `refreshed_on` check). Fixed peak-hours rule (e.g. weekday 5–8 p.m. = peak) for batch scheduling. Cline in VS Code pointed at the gateway. restic encrypted backups to HDD + offsite, password in password manager | A second refresh the same day does nothing; a batch job submitted at 4:30 p.m. weekday is scheduled for 8 p.m.; a restore test succeeds |

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

## Binding security rules (from the plan review)
- Keys: Windows Credential Manager → keyring → LiteLLM process only. Never env vars, `.env`, files, logs. gitleaks pre-commit.
- Model servers on localhost; gateway is the only entry; each client its own virtual key + budget.
- Tailscale ACL + MFA + device approval **before** exposing anything. Open WebUI admin created immediately; sign-ups off.
- Synthetic data only; work repos/data refused by every lane.
- Every model download needs your approval; files verified against their sha256; first load/eval in an isolated, no-network environment with models read-only (**PC:** `--network none` container; **Mac:** macOS sandbox, since Docker there has no GPU or MLX). GGUF/safetensors only (MLX models are safetensors).
- Pin LiteLLM by hash; review any MCP server, Open WebUI function, or plugin before installing.
- No AI path to PDU outlets, UniFi admin, or Home Assistant admin.
- Backups: restic, encrypted, HDD + offsite; quarterly restore test.

## Later (don't build in v1)
Model Selection Score with measured competency → Home Assistant Green → Context Vault → daily open-source scout (recommend-only) → coding router zones + subscription value report → full utility-rate engine → home-helper mode → device registry + phone run-local mode → exploration/replay/challenger statistics → agent groups C–E → NAS → AI node.

