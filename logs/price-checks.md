# Price checks

One entry per check of the one-key options (rules: `docs/V1-SPEC.md` §Pricing). Newest first.
Fees come from web sources and change often; confirm on the provider's own page before acting on one.

## 2026-11-06: baseline

| Group | Option | Fee model (as reported) | Notes |
|---|---|---|---|
| Marketplace | OpenRouter (in the plan) | ~5.5% on credit purchases, $0.80 minimum | Public model list with a price per provider, no key needed (458 models today) |
| Marketplace | Vercel AI Gateway | No token markup reported | Budgets and allowlists cost extra |
| Marketplace | Requesty | ~5% markup (sources disagree) | Failover, EU data residency |
| Marketplace | Hugging Face Inference Providers | Not confirmed | Check HF pricing page |
| Marketplace | Abacus.AI RouteLLM | Credits (ChatLLM $10–20/mo) | Optional v1-4 comparison only (ARCHITECTURE #12) |
| Own-key gateway | LiteLLM (in the plan) | Free, self-hosted | Public price map, no key needed |
| Own-key gateway | Cloudflare AI Gateway | ~5% with its unified billing, or own keys | |
| Own-key gateway | Portkey | Not checked | |
| Open-model host | Together, Fireworks, DeepInfra, Groq | Per-token, set by each | Reached through OpenRouter's per-provider prices |
| Cloud platform | AWS Bedrock, Google Vertex, Azure AI Foundry | Per-token, enterprise terms | Bedrock is what Amazon Connect uses; possible enterprise column later |

**Decision:** keep one paid key (OpenRouter). No change.

Sources: [Requesty](https://www.requesty.ai/blog/openrouter-alternatives),
[LLM Gateway](https://llmgateway.io/blog/openrouter-alternatives),
[Braintrust](https://www.braintrust.dev/articles/openrouter-alternatives-2026),
[haimaker](https://haimaker.ai/blog/openrouter-alternatives.md),
[Toolhalla](https://toolhalla.ai/compare/openrouter-vs-vercel-ai-gateway). Most are written by competing vendors.
