# router
Model names, prices, the three-tier table (local → OpenRouter → Claude) and routing aliases, read from here and never hard-coded (**v1-2**, **v1-3**).

Prices work the same for every provider, OpenRouter included: from these files and LiteLLM's price map, checked at gateway setup and every LiteLLM upgrade, with OpenRouter's credit fee counted in $/task. See `docs/V1-SPEC.md` §Cloud tiers and OpenRouter.
