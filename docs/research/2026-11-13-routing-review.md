# Routing plan review: what's wrong, and what the evidence supports (2026-11-13)

## Question
The plan routed work local → big open model via OpenRouter → Claude, picking the tier with a hand-written
complexity score and escalating when a local answer failed validation. Does that hold up against current
prices, published routing research and Anthropic's own guidance?

## Findings
| Issue in the plan | Evidence | Consequence |
|---|---|---|
| The middle tier existed to be cheaper than Claude | Claude Haiku 5.5 lists at $0.10 / $0.50 per million input / output tokens (cache reads $0.01), below Nemotron 3 Ultra on OpenRouter (~$0.50 / $2.20) and close to gpt-oss-120b (~$0.04 / $0.18) | The price gap that justified a second provider in the live path has mostly closed; Claude is a range of tiers, not one expensive one |
| A hand-written complexity score picks the tier | LLMRouterBench (2026, 33 models, 10 routers): many routers, commercial ones included, don't reliably beat always using the best single model; model curation matters more than router design. LiteLLM's own cost-ladder benchmark: rule-based complexity routing added no measurable value | Route from measured per-task-type eval results instead; keep a score only as a fallback for task types with no data |
| Escalate when the local answer fails validation | Validation catches broken formats, not well-formed wrong answers | Escalate on the eval rule checks at run time; add a verifier for high-stakes types |
| The model reports its own confidence (0–1) | 2026 studies: small models' verbalized confidence is often poorly calibrated and varies by task; it can work only if it separates right from wrong on that task | Log it; use it only after evals show it discriminates on that task type |
| Try local, then escalate, for everything | A request that ends at the top tier pays every tier's call and wait; agent loops compound this | Pick up front for interactive work; cascade only for batch work |
| No test of the router itself | — | Replay the router over stored eval results against always-local, always-best and oracle baselines |
| A model can lower the complexity score | A model reading untrusted input can be talked into it | High-stakes flags are fixed in code and can't be lowered |
| Per-request privacy flags for OpenRouter | OpenRouter now enforces zero data retention at account and per-key (guardrail) level; since October 2026, "safety retention" endpoints are eligible unless ZDR-only is set | Enforce ZDR-only at the account and key, not just per request |

## Anthropic's published guidance
- **Compare cost per completed task, not per token**; a stronger model can finish in fewer steps. Default for
  most agent work: Opus 5.5 at medium effort. **Haiku 5.5 first for high-volume work whose output you can
  check.**
- **Escalate on failure:** a cheap pass first, then rerun only the failures with more effort or a bigger model.
  This needs a reliable check on each answer.
- **Effort is a second dial:** the same model at higher effort can be a cheaper escalation than a bigger model.
- **Advisor tool (agents):** a cheaper executor consults a stronger advisor mid-task and pays the advisor's rate
  only for short advice. Advice from current models is returned encrypted (readable only server-side, by the
  executor); older advisors such as `claude-opus-4-8` return plaintext.
- **Routing workflow:** classify, then send easy or common requests to a cheaper model and hard ones to a
  stronger one; start simple and add complexity only when evals show the need.

## Recommendation
- Tiers become **local → Haiku 5.5 → Opus 5.5** (effort raised before switching model where that's cheaper).
- **Checkable task types** (redaction, extraction, classification, JSON): cascade, escalating only when a rule
  check fails. **Judgment task types**: choose the tier up front from eval results.
- **Agents:** executor (Haiku or Sonnet) with an Opus 5.5 advisor. For a readable log, a **shadow advisor**
  (`claude-opus-4-8`, plaintext) gets the same conversation whenever the real advisor is consulted; its
  advice is logged as a labeled approximation and never shown to the executor. Extracting the encrypted
  advice through another model was rejected: it works around a deliberate safeguard.
- **OpenRouter** stays for testing other models (eval ceiling row, try before download, a second judge), not
  for live routing.
- **Would change our mind:** evals showing a big open model clearly beats Haiku 5.5 per dollar on a task type
  (it can then be added for that type, privacy rules permitting); a router that beats the best-single-model
  baseline in the replay.

## Where it landed
Adopted with one change: the owner kept a big open model via OpenRouter as a tier **between Haiku and Opus**,
used only for synthetic or redacted requests and only where its measured cost per task is lower than Opus's.
Final tiers: local → Haiku 5.5 → OpenRouter → Opus 5.5. Recorded in a private decision record and
`docs/V1-SPEC.md` (§Routing, the tier table, the v1-2/v1-3 steps); logging in a private decision record.

## Sources
- [LLMRouterBench (arXiv 2601.07206)](https://arxiv.org/abs/2601.07206)
- [Cascade routing (arXiv 2410.10347)](https://arxiv.org/abs/2410.10347)
- [Routing vs cascades review (Stanford)](https://web.stanford.edu/~shuhuiq/blog/review-routing-cascades.html)
- [LiteLLM Auto Routing](https://docs.litellm.ai/docs/proxy/auto_routing) and [its benchmark](https://docs.litellm.ai/docs/proxy/auto_routing_benchmark)
- [Confidence-based cascades for small models (arXiv 2604.19781)](https://arxiv.org/html/2604.19781)
- [COREA: calibration in small/large model collaboration (arXiv 2603.03752)](https://arxiv.org/pdf/2603.03752.pdf)
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing) · [Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
- [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)
- [Advisor tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool)
- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [OpenRouter: Zero Data Retention](https://openrouter.ai/blog/insights/zero-data-retention/) · [Guardrails](https://openrouter.ai/blog/announcements/guardrails/)
- [gpt-oss-120b on OpenRouter](https://openrouter.ai/models/openai/gpt-oss-120b) · [Nemotron 3 Ultra pricing](https://anotherwrapper.com/llm-pricing/nemotron-3-ultra-550b-a55b)
