# American open-weight alternatives to the Chinese models (2026-11-07)

## Question
Where the build uses a Chinese model, what is the best American open-weight alternative, sized for
each machine? The evals decide, by the model-origin rule (`docs/V1-SPEC.md` v1-2): if the Chinese
model wins, keep it plus the closest American alternative; if the American one wins or ties, keep
only the American one.

## Where Chinese models are used
| Slot | Current | Maker |
|---|---|---|
| Mac primary (all-rounder) | `qwen3.6:27b-mlx` | Alibaba (China) |
| OpenRouter tier / ceiling run | DeepSeek V4 Pro | DeepSeek (China) |

Not Chinese: `gemma4:26b-mlx`, `gemma4:12b`, `embeddinggemma-2` (Google), `gpt-oss:20b` (OpenAI),
`north-mini-code-1.0` (Cohere, Canada). Your PC has no Chinese model.

## Options by machine

**Mac (M5 Pro, 48 GB; rule: file + context + ~6 GB < ~30 GB)**
| Option | Maker, license | Size | Fit | Notes |
|---|---|---|---|---|
| **`gemma4:31b-mlx`** (pick) | Google, Apache 2.0 | 19 GB | ~28 GB at 16K: fits, not much spare | Dense, same class as qwen3.6 27B; `tools`, `thinking`, `vision` listed |
| `muse-glimmer:30b-mlx` (second) | Meta, Apache 2.0 + usage policy | 19 GB | Same | Agent-focused (Aug 2026); read the usage policy in the safeguard check |
| `nemotron-3-nano:30b-a3b-mlx` | NVIDIA, own license (verify) | 18 GB | Fits; ~3B active, fast | A fast-tier option, not a primary |

**Your PC (16 GB VRAM; rule: file + context + ~1.5 GB < 16 GB)**: nothing to replace. The 30B-class
models above (18–19 GB) don't fit and would spill to the CPU. American models that fit: `gemma4:12b`
(running), `phi4:14b` (Microsoft, 9.1 GB), `granite4.2:8b` (IBM), `gpt-oss:20b` (14 GB, running, tight).

**OpenRouter (cloud; prices per million tokens in / out, public list today)**
| Option | Maker | Price | Notes |
|---|---|---|---|
| DeepSeek V4 Pro (current) | DeepSeek | $0.65 / $1.29 | |
| **`gpt-oss-120b`** | OpenAI | $0.02 / $0.07 | Big sibling of the local `gpt-oss:20b`; cheapest |
| **Nemotron 3 Ultra 550B** | NVIDIA | $0.60 / $2.40 | Strongest US open model listed; best ceiling row |
| Nemotron 3 Super 120B | NVIDIA | $0.07 / $0.40 | 1M context |
| Muse Spark Open | Meta | $1.25 / $4.25 | Open weights since 2026-10-15 under the Muse Model License: up to $20M revenue, "Built with Muse Spark Open" shown in the UI. Fine for an eval row; a license review before any product use |
| Muse Glimmer 30B | Meta | $0.30 / $1.20 | Same size as the local models, so it adds no ceiling; test it locally instead |

## Recommendation
- **Mac:** pull `gemma4:31b-mlx`, run the 27-item eval next to qwen3.6. Muse Glimmer next if it falls short.
- **Your PC:** no change.
- **Ceiling run (v1-2):** DeepSeek V4 Pro + `gpt-oss-120b` + Nemotron 3 Ultra; Muse Spark Open optional.
- **Would change our mind:** eval results (accuracy, speed, stuck items); a license term that blocks
  sharing the project; a US lab releasing a 20–30B model with better measured results.

## Where it landed
`docs/V1-SPEC.md` (v1-2 ceiling run), `docs/setup/MAC.md` (current models, after first load).

Sources:
- [Ollama: gemma4 tags](https://ollama.com/library/gemma4/tags)
- [Gemma 4 release: four open models, Apache 2.0](https://vibecodehq.pages.dev/blog/gemma-4-google-deepmind-open-model-apache-2)
- [Ollama: muse-glimmer tags](https://ollama.com/library/muse-glimmer/tags)
- [Meta releases Muse Glimmer](https://aiweekly.co/node/9642)
- [Ollama: nemotron-3-nano tags](https://ollama.com/library/nemotron-3-nano/tags)
- [NVIDIA Nemotron 3 guide](https://toolhalla.ai/blog/nvidia-nemotron-3-complete-guide-2026)
- [OpenAI: Introducing gpt-oss](https://openai.com/index/introducing-gpt-oss/)
- [Meta makes Muse Spark available as an open-weight model](https://itdaily.com/news/innovation/meta-muse-spark-open-weigh/)
- [The Batch: Meta releases Wonder, opens Spark](https://www.deeplearning.ai/the-batch/meta-releases-wonder-opens-spark/)
- [Cohere North Mini Code 1.0 guide](https://codersera.com/blog/cohere-north-mini-code-guide-2026/)
- [OpenRouter public model list](https://openrouter.ai/api/v1/models)
