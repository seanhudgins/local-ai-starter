# router
Model names, prices, the routing table (local → Claude Haiku → OpenRouter → Claude Opus, per task type from eval results) and routing aliases, read from here and never hard-coded (**v1-2**, **v1-3**). OpenRouter is a routing tier only for synthetic or redacted requests (or code from your own repos, under a per-repo key and a secret scan) and only where it's cheaper per task than Opus. Every client uses `auto` by default.

Prices work the same for every provider, OpenRouter included: from these files and LiteLLM's price map, checked at gateway setup and every LiteLLM upgrade, with OpenRouter's credit fee counted in $/task. See `docs/V1-SPEC.md` §Cloud tiers and OpenRouter.
