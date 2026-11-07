# Glossary (plain English)

Terms used in this project, in the sense we use them. Add a term the first time a doc uses it.

| Term | Meaning here |
|---|---|
| **Model** | The trained AI file (weights) that produces answers, e.g. `gemma4:12b`. |
| **Open-weight model** | A model whose files you can download and run yourself. |
| **Runtime** | The program that runs a model on your hardware. Here: Ollama. |
| **Context window** | How much text a model can consider at once, in tokens. We start at 8K–16K. |
| **Token** | A chunk of text (about ¾ of a word) that models read and write; also how cloud APIs bill. |
| **VRAM** | The graphics card's memory. Model + context + headroom must fit in it. |
| **Quantization** | Shrinking a model's numbers so it fits and runs faster, at some cost to quality. |
| **Harness / agent** | An app that wraps a model and gives it tools and steps to follow (e.g. goose, Cline, Claude Code). |
| **Tool call** | A model asking to run a function (look up a balance, search a KB) instead of only writing text. |
| **MCP** | Model Context Protocol: a standard way for AI tools to call outside tools and data. |
| **Gateway** | One front door for every model, local or cloud. Here: LiteLLM. Holds keys, budgets, logs. |
| **Virtual key** | A key the gateway gives each app, with its own budget, instead of sharing a provider key. |
| **Escalation / routing** | Sending a task to a bigger or paid model when the local one isn't good enough. |
| **Tier** | One step on the routing ladder: local → big open model (OpenRouter) → Claude. |
| **Embedding** | A list of numbers that represents a text's meaning, so similar texts can be found. |
| **RAG** | Retrieval-augmented generation: the model looks things up in a knowledge base before answering. |
| **Eval** | A fixed set of test tasks with answer keys, run the same way on every model to compare them. |
| **Rule check** | An automatic pass/fail test on an answer (right label, valid JSON, no leaked phone number). |
| **Judge model** | A strong model that scores answers that need judgment, using a rubric. |
| **PII** | Personally identifiable information (names, phone numbers, card numbers). Only synthetic here. |
| **Synthetic data** | Made-up data shaped like the real thing, safe to share and test with. |
| **Tailscale / tailnet** | A private network between your own devices; nothing is exposed to the internet. |
| **Sandbox** | A locked-down space where a program can't reach the network or your files. |
| **Hook** | A small script a tool runs automatically at a set moment (before a commit, before Claude finishes a reply). |
| **Machine inbox** | `ops/inbox.json`: one machine leaves allow-listed checks for the other, which runs them after `git pull`. |
| **ICM** | Interpretable Context Methodology: organizing AI work as folders, each step with its own instructions. |
| **Lockfile** | A file pinning exact dependency versions and hashes, so installs are repeatable and tamper-evident. |
