# Training an auto-router, and skills per model per task type (2026-11-13)

## Question
How do people make automatic model routers accurate over time ("train" them), and does it make sense to keep
skills (prompt guides) per model per task type that improve with use?

## Options: how routers learn
| Approach | How it learns | Evidence | Fit for a single-user home lab |
|---|---|---|---|
| **Plain-language route policies** (Arch-Router, LangChain Open SWE) | Routes described in words; a small model matches requests to them | Arch-Router (1.5B) reports 93% routing accuracy, above large proprietary models in its tests; new routes need no retraining. LangChain's A/B: median cost -64%, no measurable quality change | Stage 1 now. Arch-Router is built on Qwen2.5 with its own license, so a local copy needs the model-origin rule and a license check; Haiku can do the matching instead |
| **kNN over past requests** | Embed each request; route like the most similar past requests with known outcomes | A tuned kNN router matched or beat complex learned routers, ran 13–14x faster, and degraded less under distribution shift (2.63 vs 6.67 points); weaker on rare requests with few neighbors | Best fit for low volume: eval items plus logged outcomes are the neighbors; local embeddings and SQLite |
| **Learning from preference data** (RouteLLM) | Matrix factorization on ~80K pairwise votes | 95% of GPT-4's quality with 14–26% of calls to it; adding golden-labeled data under 2% of the total helped | Not enough votes at home; the lesson that a little verified data matters carries over (the eval sets) |
| **Online learning (contextual bandits)** (OrcaRouter, PILOT, BaRP) | Warm start offline, then update from each answer's feedback (thumbs, retries, judge) | Active research 2025–26; retries work as implicit feedback; open gaps in multi-turn and budgets | Later: learns slowly at dozens of requests a day |
| **Large proprietary datasets** (Cursor's router) | Trained on hundreds of thousands of requests | Not published | Not feasible or needed |

## Options: skills per model per task type
- **For:** prompts optimized for one model often rely on model-specific heuristics that fail on others, and a
  model update can break a previously good prompt (2026 studies of GEPA- and DSPy-optimized prompts). So
  model-specific guidance can help, but it expires.
- **Against / unproven:** no controlled study found showing a hand-written per-model, per-task skill library
  improves small-model accuracy; practitioner advice is split between "small models need more structure" and
  "too-specific prompts are fragile".

## Recommendation
- **A data flywheel:** evals → skills → routing → audits → back to evals. Start with plain-language policies plus
  the eval table; add a kNN router once logged outcomes exist, and only if it beats the table in a replay and an
  A/B test; bandits later, if volume grows.
- **Skills earned, not assumed:** one base skill per task type shared by all models, plus a small per-model
  addition only where evals show a gap; each written on training items and kept only if it wins on held-out
  items; versioned, and re-tested when its model changes. The routing unit becomes "model + its skill", so a
  skill that lifts a cheap model over the bar moves that task type down a tier.
- **Would change our mind:** per-model additions that don't beat the base skill on held-out items (then base
  skills only); a kNN router that doesn't beat the table (then keep the table).

## Where it landed
A private decision record (the learning loop) and `docs/V1-SPEC.md` (v1-1 skill guides, v1-3 router).

## Sources
- [RouteLLM (arXiv 2406.18665)](https://arxiv.org/html/2406.18665v3) · [LMSYS blog](https://lmsys.org/blog/2024-07-01-routellm)
- [Arch-Router (arXiv 2506.16655)](https://arxiv.org/html/2506.16655v1) · [model card](https://huggingface.co/katanemo/Arch-Router-1.5B.gguf)
- [When simple kNN beats complex learned routers (arXiv 2505.12601)](https://arxiv.org/abs/2505.12601v1)
- [OrcaRouter](https://www.alphaxiv.org/abs/2605.30736.md) · [BaRP (arXiv 2510.07429)](https://arxiv.org/html/2510.07429v1) · [PILOT (arXiv 2508.21141)](https://arxiv.org/html/2508.21141v2) · [retries as feedback (arXiv 2602.02061)](https://arxiv.org/pdf/2602.02061)
- [LangChain: model router in the harness](https://www.langchain.com/blog/how-to-build-a-model-router-in-the-harness)
- [GEPA prompts and model-specific heuristics (arXiv 2603.28038)](https://arxiv.org/html/2603.28038) · [prompt transfer across models (EAMT 2026)](https://aclanthology.org/2026.eamt-1.8.pdf)
- [Agent skills and small models (arXiv 2602.16653)](https://arxiv.org/html/2602.16653v2) · [prompting local models](https://agent-zone.pages.dev/knowledge/agent-tooling/prompt-engineering-local-models)
