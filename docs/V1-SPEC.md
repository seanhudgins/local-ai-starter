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
| **v1-1** Bake-off + skill guides | Runs on **[Your PC]** and the **Mac**; code anywhere | **First:** move the model-check logic into one tested Python module, `services/ollama/modelcheck.py` (tool-call test, answer check, sha256 verify, embedding check), so the first-load scripts only set up isolation and call it; add `ruff` and `pytest` to CI. Then 20–30 synthetic contact-center items (summary/disposition, intent, PII redaction, JSON extraction, 5-pt QA, escalation risk, follow-up draft, "local or escalate?") as JSONL with answer keys. One runner (Python, `uv`, pytest-tested, the `openai` client against Ollama's OpenAI-compatible API, reusing `modelcheck.py`): rule checks first, grader model only for judgment items (**Claude Opus 5.5** as judge via the Anthropic API key, read from the OS keychain as `localai/anthropic`; a per-run spend cap; cost measured on a small batch first; later compare a local judge's agreement, and a non-Claude judge via OpenRouter once the gateway exists), tool-call reliability counted, each result stamped with the Ollama version and model digest, stored in **SQLite** (`evals/results.db`). Run every installed model on both machines. Then one `skills/models/<model>/SKILL.md` per chosen model, filled only from the results | `evals/results.db`, `logs/benchmarks.md` built from SQL queries, a results table in the README; `ruff` + `pytest` green in CI; a **primary** and a **fast** model chosen per machine; each guide has measured strengths, failure modes, prompt format, escalation rules, one packet that worked |
| **v1-2** Gateway | **[Your PC]** | LiteLLM in Docker, image pinned by digest, in front of Ollama + Anthropic, Google, OpenRouter. Keys: Credential Manager → keyring launcher → container only. Per-client virtual keys with budgets (open-webui, goose, cline, mcp-local, evals). Aliases `auto`, `auto-coding`. Per-call/daily/monthly caps; provider-side spend limits (OpenRouter: prepaid credit + a per-key credit limit). OpenRouter routes set up per §Cloud tiers and OpenRouter (no data collection, zero retention, no `:free` models, tool-capable providers only). Point Open WebUI, goose, Cline and the eval runner at it. Then a **ceiling run**: the v1-1 eval set on 1–2 big open models via OpenRouter, provider pinned, cost measured on a small batch first, results in `evals/results.db` next to the local runs. From then on, a scout candidate can be eval-run on OpenRouter before its download is put up for approval. **Price snapshot:** `uv run router/prices.py` pulls the two public, no-key price lists (OpenRouter's model list, with a price per provider behind each model, and LiteLLM's price map for direct providers), saves a dated copy to SQLite (`router/prices.db`), and shows, per escalation model, the cheapest provider that meets the OpenRouter rules (no data collection, zero retention, tool calls). Run by hand; it never changes routing on its own | Every client goes through the gateway; a call over the cap is refused; spend shows per key; a request to an OpenRouter route without the privacy settings is refused; the ceiling run is in the results table |
| **v1-3** Handoff both ways + retrieval | Code anywhere; runs on each machine | Handoff Packet schema + validator (§Handoff Packet). **RAG:** a small synthetic policy knowledge base (clinic scheduling rules, bank fee policies) indexed with `embeddinggemma-2` into SQLite, exposed as a `search_kb` tool on the MCP server so local models, OpenRouter and Claude all retrieve from the same store (the "Open Brain" pattern: own the memory, open it to every tool over MCP; self-hosted on your PC, no hosted vector DB, our own code so the public copy stays MIT; read-only and synthetic in v1, retrieved text is data, never instructions); eval items for grounded answers with citations. MCP server `ask_local_model(task, input, output_schema)` that calls an OpenAI-compatible URL from config (the gateway on your PC; the Mac's own Ollama when offline). `escalate_to_cloud` through the gateway with the three-tier table (§Cloud tiers and OpenRouter: local → big open model via OpenRouter → Claude), picked by the complexity score; every escalation logged to **SQLite** (`logs/escalations.db`, no raw content), so spend per key and per day is a SQL query. `skills/delegate-to-local/SKILL.md` | From the Mac, Claude Code delegates a redaction task and gets valid JSON back; a malformed packet is rejected; an escalation is logged and capped; grounded-answer evals pass with correct citations |
| **v1-4** Demo + ops | **[Your PC]** | End-to-end demo (synthetic transcript → local redaction + summary → Claude QA/coaching on low-confidence cases), recorded, with a small UI: **TypeScript** web front end (the language contact-center AI roles ask for) or **Gradio** (pure Python); decide at v1-4. GPU benchmark report (tokens/sec, watts, $/task). **Business case:** the same tasks run in three columns, **local / big open model (OpenRouter) / Claude**, side by side (accuracy, latency, $/task), and where each routing line pays off. Optional fourth column: a commercial auto-router (Abacus.AI RouteLLM) on the same set, to compare our routing against a black-box one; only after a privacy review like OpenRouter's, cost measured on a small batch first; not a dependency. Ops: Open WebUI and LiteLLM start at boot; PC power policy (no sleep, or Wake-on-LAN); optional Tailscale SSH so the PC is administered from the Mac; backup of Open WebUI data, evals and skills with a restore test | Recorded demo + report in `outputs/` (benchmark numbers from SQL queries); services survive a reboot; restore test passes |

**Each version ships a demo and a write-up:** a screenshot or short recording in the README, a tagged public release, and a short case study in `docs/releases/v1-x.md` (problem, approach, results, what I'd change). That is the build story.

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

## Cloud tiers and OpenRouter
| Tier | Where | Used when |
|---|---|---|
| 1 | Local (the machine's primary/fast model) | Default; complexity 1–2 |
| 2 | Big open-weight model via OpenRouter | Complexity 3, or a local attempt failed validation |
| 3 | Claude via the Anthropic API | Complexity 4–5: judgment-heavy, high stakes, or tier 2 failed |

Model names per tier live in `router/` config, never in code. Starting thresholds; the v1-4 business case tunes them.

**OpenRouter rules** (enforced in the gateway config, not just written down):
- Synthetic or redacted data only. Only Handoff Packets marked synthetic, or that passed local redaction, may use an OpenRouter route.
- Every request: providers that don't collect data (`provider.data_collection: "deny"`) and zero data retention only; no `:free` model variants (they can log prompts); `require_parameters: true` so only providers that support the request's features (tools, JSON) serve it. Account-level privacy settings match.
- Eval runs pin the provider (`provider.order`, `allow_fallbacks: false`, and a `quantizations` filter) and record the provider that served each result, like the Ollama version and model digest for local runs, because one model name can be served at different quantizations.
- Spend: prepaid credit with a per-key credit limit at OpenRouter, plus the gateway's per-call/daily/monthly caps.
- OpenRouter's settings and fees change: check its current docs before configuring (v1-2) and at each gateway upgrade.

**Pricing (all providers the same, OpenRouter included):** prices come from config (`router/`) and LiteLLM's price map, never hard-coded. They're checked when the gateway is set up and at every LiteLLM upgrade, and the cost of a new kind of run is measured on a small batch first. OpenRouter adds its own fee on credit purchases; include it in $/task. **Every price check also re-checks the one-key alternatives** (search first; fees change): marketplaces (OpenRouter, Requesty, Vercel AI Gateway, Hugging Face Inference Providers, Abacus.AI RouteLLM), bring-your-own-key gateways (LiteLLM, Portkey, Cloudflare AI Gateway), open-model hosts (Together, Fireworks, DeepInfra, Groq) and cloud platforms (AWS Bedrock, Google Vertex, Azure AI Foundry). Compare markup and fees, privacy controls (no data collection, zero retention) and tool-call support; add a dated entry to `logs/price-checks.md`. Switching providers or adding a key is a human decision, not part of the check. Run `router/prices.py` (v1-2) for the per-model numbers. A scheduled price refresh is Later and covers every provider.

## Languages
Python for logic (typed, `ruff`-clean, pytest-tested, run with `uv`). Shell/PowerShell only as thin wrappers around OS tools (`sandbox-exec`, `docker`, `codesign`, service start-up). SQLite for anything queried later. One optional TypeScript piece: the v1-4 demo UI.

## Binding security rules (from the plan review)
- Keys: Windows Credential Manager → keyring → LiteLLM process only. Never env vars, `.env`, files, logs. gitleaks pre-commit.
- Model servers on localhost; gateway is the only entry; each client its own virtual key + budget.
- Tailscale ACL + MFA + device approval **before** exposing anything. Open WebUI admin created immediately; sign-ups off.
- Synthetic data only; work repos/data refused by every lane. OpenRouter routes get synthetic or redacted packets only, with no data collection and zero retention (§Cloud tiers and OpenRouter).
- Every model download needs your approval; files verified against their sha256; first load/eval in an isolated, no-network environment with models read-only (**PC:** `--network none` container; **Mac:** macOS sandbox, since Docker there has no GPU or MLX). GGUF/safetensors only (MLX models are safetensors).
- Pin dependencies: LiteLLM by image digest, Python by `uv.lock`, actions by commit SHA; checks run on every push. Review any MCP server, Open WebUI function, or plugin before installing.
- No AI path to PDU outlets, UniFi admin, or Home Assistant admin.
- Backups: Open WebUI data, evals and skills to the HDD with a restore test (v1-4); encrypted offsite is Later.

## Later (don't build in v1)
First in line for v2 (career-relevant): a cloud-hosted live demo link → CCaaS integration (a transcript arriving via a Twilio or Amazon Connect webhook, redacted and summarized locally) → tracing/observability for the gateway.

Daily price refresh for every provider, OpenRouter included (LiteLLM's price map updates with each release; OpenRouter also lists live prices per model; refresh only if a stale price costs money) → scout runs "try on OpenRouter first" itself (in v1 it's a manual eval run through the gateway) → peak-hours scheduling for your utility (once a batch job exists) → restic encrypted offsite backups → Model Selection Score with measured competency → Home Assistant Green → Context Vault (personal memory that agents can write to, built on the v1-3 store and MCP server; needs write rules and injection defenses first) → daily open-source scout (recommend-only) → coding router zones + subscription value report → full utility-rate engine → home-helper mode → device registry + phone run-local mode → exploration/replay/challenger statistics → agent groups C–E → NAS → AI node.

