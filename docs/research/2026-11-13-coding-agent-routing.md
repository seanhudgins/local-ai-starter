# How people route coding agents across models (2026-11-13)

## Question
The routing engine should pick models automatically for coding agents too: you ask or give a task and it
works in the background. What designs are people using, and which ones have hard data behind them?

## Options (what's out there)
| Pattern | Who uses it | Evidence | Mid-conversation switching |
|---|---|---|---|
| **Role split: a strong model plans, a cheaper one edits or executes** | Aider architect/editor mode; Claude Code `opusplan` (Opus in plan mode, Sonnet to execute); Roo Code and Kilo Code (a model per mode: architect, code, debug); claude-code-router (routes by request kind: background, think, long context, default); Claude Code subagents on a smaller model | Aider: a reasoning model as architect with Sonnet as editor set a polyglot-benchmark record at 14x less cost than the previous best; but o1 + Sonnet did no better than o1 alone. The most popular pattern in practice | Switches by role, not by difficulty |
| **Route once per task, from the first message** | LangChain Open SWE; Cursor Router (a per-request classifier, July 2026) | **The strongest hard data found:** an A/B test of 973 threads, routed vs always the top model: median cost per thread down **64%** ($0.94 vs $2.61), mean down 42%, merged-PR rate 29.2% vs 27.3% (p=0.49, no measurable quality change). Routed mix: 34% fast, 56% balanced, 10% top. A fast-only arm was stopped within a day over quality complaints. The classifier reads only the first human message, with plain-language criteria per tier | No; mid-thread re-routing is listed as future work |
| **Route per user turn, cache-aware** | Augment Prism | Internal benchmark: 20–30% cheaper per task at equal or better quality; Terminal Bench 2.0 about 17% cheaper for one pair but *slightly more expensive* for another; SWE-Bench Pro 7–12% cheaper at 0.7–2.3 points lower. Planner overhead ~0.03% of cost, ~2.6 s | At each new user turn; **sticky across the agent's tool calls within a turn**; switches only when the expected gain beats the cost of losing the prompt cache |
| **Advisor: a cheaper executor consults a stronger model at hard moments** | Anthropic advisor tool; Claude Code `/advisor` | Anthropic: Sonnet with an Opus advisor scored **+2.7 points** on SWE-bench Multilingual at **11.9% lower cost** per agentic task than Sonnet alone | No switch; the executor asks and continues |
| **Cascade: a cheap model explores first, escalate once if it looks likely to fail** | SWE-Router (2026 paper); "scrouting" (a small scout model, then a frontier model fixes) | SWE-Router: a learned predictor after 1–4 cheap turns beat prompt-only routers (+12 points route-AUC) on SWE-bench Verified but not on a second test set. On escalation the strong model **restarts from the original task**, because continuing "has been seen to bias" it toward the cheap model's mistakes. Scrouting: reported best-single-model solves at ~0.18x cost (blog report, unverified) | At most one escalation, as a restart; never back down |

## What the evidence agrees on
- **Route at natural boundaries, not mid-step.** Every production system routes per task or per user turn and
  stays put across the agent's tool calls within it. Switching models throws away the prompt cache (the next
  call costs roughly 10x a cache hit); between user turns that cache has often expired anyway.
- **A cheap model that grinds costs more.** More turns and retries re-pay the input tokens each time (Augment:
  "a 'cheaper' model isn't cheaper if it grinds for twice as many turns"). Measure cost per *completed* task and
  turns per task, not price per token.
- **Gains depend on the task mix.** Big savings where many tasks are easy (LangChain's 64%); little or none on
  uniformly hard work, where "always use the strongest model" is the right policy.
- **Self-prediction is weak.** A model's own guess of how a task will go correlated at most 0.39 with reality in
  one study, and token use for the same task varied up to 30x between runs. Route on observed signals, not on
  the model's opinion of itself.
- **Prove it with an A/B test**, routed vs always-one-model, on real outcomes (tests pass, changes merged).

## Recommendation
1. **Per task, at the start (v1-2):** classify the first message with plain-language criteria per tier, the
   LangChain design with the strongest data. Plus **role split** (planning, main work, exploration) through
   role aliases, the most widely used pattern.
2. **Per user turn after that (v1-3):** re-route only at each new user message, sticky across tool calls within
   the turn, switching only when the gain beats losing the cache.
3. **Advisor for hard moments (v1-3):** a `consult_advisor` tool the working model calls itself.
4. **Backstop:** on hard failures within a turn, escalate once and **restart that turn** on the stronger model
   from the user's request, not continue from the cheap model's attempts. No stepping back down mid-turn.
5. **A/B test** routed vs always-Haiku and always-Opus before trusting it.
- **Would change our mind:** an A/B where routing doesn't beat always-one-model on our own mix (then use one
  model per role and stop there); evidence that a learned predictor (SWE-Router style) pays for itself.

## Where it landed
A private decision record and `docs/V1-SPEC.md` (§Routing, v1-2/v1-3).

## Sources
- [Aider: architect/editor](https://aider.chat/2024/09/26/architect.html) · [R1 + Sonnet](https://aider.chat/2025/01/24/r1-sonnet.html)
- [Claude Code model configuration](https://code.claude.com/docs/en/model-config)
- [claude-code-router guide (morphllm)](https://www.morphllm.com/claude-code-router)
- [Roo Code modes](https://docs.roocode.com/basic-usage/using-modes) · [Kilo Auto Model](https://docs.kilo.ai/docs/code-with-ai/agents/auto-model)
- [Cursor Router changelog](https://cursor.com/changelog/router) · [Cursor Router per-request decisions](https://startdebugging.net/2026/07/cursor-router-makes-auto-a-per-request-model-decision/)
- [LangChain: build a model router in the harness](https://www.langchain.com/blog/how-to-build-a-model-router-in-the-harness)
- [Augment Prism](https://www.augmentcode.com/blog/augment-prism-model-routing-to-reduce-cost-and-maintain-quality)
- [The advisor strategy (Anthropic)](https://claude.com/blog/the-advisor-strategy)
- [SWE-Router (arXiv 2607.00053)](https://arxiv.org/abs/2607.00053)
- [Scrouting and routing for Codex CLI (blog)](https://codex.danielvaughan.com/2026/08/07/scrouting-cost-aware-model-routing-repository-scouting-codex-cli-sol-terra-luna-task-routing/)
- [Not Diamond Code](https://www.notdiamond.ai/blog/not-diamond-code-intelligent-model-routing-for-coding-agents)
- [Unblocked: when cheaper models cost more](https://getunblocked.com/blog/model-routing-coding-agents/index.md)
