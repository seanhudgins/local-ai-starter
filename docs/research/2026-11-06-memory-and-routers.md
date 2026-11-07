# Open Brain and Abacus.AI: what could they add? (2026-11-06)

## Question
Two outside ideas came up: **Open Brain** (a personal AI memory you own) and **Abacus.AI** (a paid
hub for many models). Would either make the build better?

## Options

| Option | What it is | Fit |
|---|---|---|
| **Open Brain** (Nate B. Jones; community forks) | Postgres + pgvector for search by meaning, opened to any AI tool through an MCP server; usually hosted on Supabase | Strong fit for the v1-3 retrieval step: one store that local models, OpenRouter and Claude all search. Hosting it in the cloud breaks "models stay on localhost"; the main repo's license (FSL-1.1-MIT) isn't plain MIT |
| **Abacus.AI ChatLLM** | One app for many models, about $10–20 a month in credits | Overlaps Open WebUI plus a Claude plan |
| **Abacus.AI RouteLLM** | An API that picks a model per request | Overlaps the LiteLLM gateway and the OpenRouter tier; its routing is a black box |
| **Abacus.AI DeepAgent** | Autonomous agent that builds apps and opens PRs | Overlaps Claude Code |

## Recommendation
- **Open Brain: adopt the pattern, not the service.** Build our own: SQLite + local embeddings on the
  home PC, `search_kb` on the MCP server, read-only and synthetic in v1. Agent-written personal memory
  stays Later (it needs write rules and defenses against injected instructions first).
- **Abacus.AI: not a dependency.** RouteLLM may appear as an optional comparison column in the v1-4
  business case ("our router vs a commercial auto-router"), after a privacy review.
- **Would change our mind:** a self-hosted Open Brain release under a plain open-source license
  (reuse instead of rebuild); Abacus publishing privacy controls equal to OpenRouter's and a routing
  method we can inspect.

## Where it landed
`docs/ARCHITECTURE.md` decisions 11 and 12; `docs/V1-SPEC.md` v1-3 (retrieval), v1-4 (business case), Later (Context Vault).

Sources:
- [Nate's Newsletter: "Every AI you use forgets you"](https://natesnewsletter.substack.com/p/every-ai-you-use-forgets-you-heres)
- [Open Brain summary](https://summaries-5ws.pages.dev/summaries/2026-03-02-ai-news-strategy-daily-you-dont-need-saas-the-010-system-that-replaced-my-ai-workflow-45-min-no-code-build)
- [MindStudio: What is OpenBrain](https://www.mindstudio.ai/blog/what-is-openbrain-personal-ai-memory-database)
- [OB1 repo mirror (license)](https://gh.ali360.cloudns.ch/dfrysinger/OB1)
- [Self-hosted Open Brain fork](https://srnichols.github.io/OpenBrain)
- [eesel.ai: Abacus AI review](https://eesel.ai/blog/abacus-ai)
- [Abacus.AI blog: pricing 2026](https://blog.abacus.ai/abacus-ai-review-chatllm-deepagent-pricing-2026)
- [KDnuggets: ChatLLM review](https://www.kdnuggets.com/2026/06/abacus/abacus-ai-chatllm-review)
