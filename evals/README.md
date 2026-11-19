# evals
`sets/contact-center.jsonl`: synthetic contact-center items (JSONL, with answer keys), 10 per task type.
`sets/my-work.jsonl`: 32 everyday knowledge-work tasks, 8 each of coding help (`code-`), docs and planning
(`docs-`), slide outlines (`slides-`) and research synthesis with citations (`research-`). Fictional data;
every item has rule checks and a judge rubric. Items may carry their own `system` line (what the model sees)
and `judge_subject` (how the judge's instructions name the work); contact-center items use the defaults.
Pick a set with `--set` (default `contact-center`); `judge`, `report` and `compare` reload the set a run used.

`run.py` runs them against local models and writes every result, stamped with the Ollama version and model
digest, to `results.db` (SQLite). Rule checks score every item; items with a rubric are also graded by Claude.

```zsh
uv run evals/run.py run --models gemma4:31b-mlx --note "why this run"
uv run evals/run.py run --set my-work --models gemma4:31b-mlx --note "my-work baseline"
uv run evals/run.py judge --run RUN_ID --max-usd 1 --limit 5   # measure cost on a small batch first
uv run evals/run.py judge --run RUN_ID --max-usd 5              # then grade the rest under a cap
uv run evals/run.py report --run RUN_ID
uv run --with datasette datasette evals/results.db               # browse every run in the browser
```

The judge's model, effort and prices are in `router/judge.json`; its key comes from the OS keychain only.
Each judge call's tokens and cost go to the `judge_calls` table. Runs judged in chat before 2026-11-09 are
marked `judge = 'chat'` and were for direction only.
