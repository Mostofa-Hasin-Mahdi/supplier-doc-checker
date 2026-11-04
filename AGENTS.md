# AGENTS.md

## Standing Rules for Every Future Task

- **Goal**: A supplier-document checker for a take-home assignment. The pipeline produces one of three verdicts per supplier pack: `APPROVE`, `REJECT`, or `NEEDS_REVIEW` (Needs a person to check).
- **Architecture Rule**: A **FIXED, linear LangGraph pipeline**. NO free-running or autonomous agent loops.
  - The LLM is used **ONLY** to extract structured fields from document text.
  - **ALL decisions** (e.g., price/quantity comparisons, policy rules, final verdict evaluation) are implemented in **plain, deterministic Python**.
- **"Never Guess" Policy**: Any missing, ambiguous, corrupted, or unverifiable field strictly forces the verdict to `NEEDS_REVIEW` ("Needs a person to check"). No hallucinated or assumed values are permitted.
- **Evidence-Backed Decisions**: Every decision reason must include the **exact supporting quote** verbatim from the document text.
- **Sample Data Only**: Use only the provided fictional sample files. Never introduce real or sensitive data.
- **Externalized Configuration**: Keep all rule thresholds, limits, and tolerance parameters centralized in `config/rules.yaml`. Never hardcode thresholds or business rule constants in source code logic.
- **Code Quality & Standards**:
  - Full type hints everywhere (`typing` / Python standard typing).
  - Small, modular, pure functions wherever possible.
  - Test suite using `pytest`.
  - Linting, formatting, and static code quality enforced via `ruff`.
- **Security & Secrets**: Never commit API keys or sensitive credentials. Manage all environment variables via `.env` (kept in `.gitignore`) and provide variable templates in `.env.example`.
- **Task Completion Protocol**: After completing each task or iterative change:
  1. Run unit tests (`pytest`).
  2. Run linter checks (`ruff check .`).
  3. Provide a clear summary of what changed.
