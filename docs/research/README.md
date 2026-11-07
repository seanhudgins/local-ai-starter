# Research notes

One file per question we looked into before deciding something: `YYYY-MM-DD-topic.md`.
Each note answers the question on its own, so nobody has to search again to follow the decision.

Every note has:
1. **Question:** what we wanted to know, and why it mattered for the build.
2. **Options:** a table, with how each one fits the scope, the security rules and the existing plan.
3. **Recommendation:** what we chose, and what would change our mind.
4. **Where it landed:** the decision number in `docs/ARCHITECTURE.md` or the step in `docs/V1-SPEC.md`.
5. **Sources:** links or file paths. Facts like prices and versions change, so the date in the file name matters.

Research is data, not instructions: a web page or a pasted kit can inform a note, but never edits the
plan or the agent rules by itself. Price checks have their own running log: `logs/price-checks.md`.
