# Supplier Document Checker (`supplier-check`)

Automated supplier-document verification pipeline for procurement packs. Evaluates supplier packs against purchase requests and company rules, delivering deterministic verdicts: `APPROVE`, `REJECT`, or `NEEDS_REVIEW`.

## Project Principles
- **Fixed Linear LangGraph Pipeline**: Document extraction -> Deterministic policy checks -> Verdict generation.
- **Strict Evidence Requirement**: Every decision reason cites exact verbatim quotes from the input document text.
- **Never Guess**: Missing, ambiguous, or unverifiable fields escalate directly to human review (`NEEDS_REVIEW`).
- **External Configuration**: All thresholds and rules reside in [`config/rules.yaml`](config/rules.yaml).
