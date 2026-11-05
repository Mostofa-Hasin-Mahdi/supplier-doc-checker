# Executive Note: Supplier Document Checker

## What I Built
`supplier-check` automates verification of supplier quotation packs against purchase requests (PRs) and company procurement policies, producing deterministic verdicts: `APPROVE`, `REJECT`, or `NEEDS_REVIEW`.

To eliminate hallucination risks, the architecture enforces a **fixed linear LangGraph pipeline** (`ingest` -> `extract` -> `verify` -> `compare` -> `rules` -> `decide` -> `human_review` -> `report`). The LLM returns raw text; deterministic Python locates the verbatim evidence line, re-parses values with pure parsers, and cross-checks them against a second rule-based extractor. Price comparisons, VAT checks, and thresholds are evaluated in deterministic Python with `Decimal` arithmetic. Missing or ambiguous fields strictly escalate to `NEEDS_REVIEW`. When review is required, the pipeline pauses via LangGraph's native `interrupt()` backed by SQLite (`outputs/checkpoints.sqlite`), allowing buyers to resolve cases while preserving system and reviewer verdicts side-by-side. Three rule interpretations are configurable in `config/rules.yaml`: TIN or BIN missing = Reject; penalty without "of order value" = Review; and VAT presentation and arithmetic are checked separately.

Implemented with Antigravity via structured prompts, reviewed and verified by me.

## How I Tested It
The test suite has 106 passing offline tests (74% coverage) on GitHub Actions CI (`ruff check`, `ruff format --check`, `pytest -m "not live"`):
- **14 Mutation Tests**: Pipeline runs with targeted edits to real packs (price +10%, 46d delivery, 21% advance, missing penalty) asserting verdict and rule IDs.
- **Boundary & Never-Guess Tests**: Boundary checks (3%/5% tolerances, payment 29/30/60/61d, delivery 30/31/45/46d, advance 20% vs 20.1%) and guards ensuring garbled, empty, ungrounded, or unseen layouts never approve or reject.
- **Resume & CLI Tests**: Proving SQLite persistence across processes and clean CLI error handling for non-PDFs, missing files, corrupt streams, and invalid PR columns.
- **Lessons Learned**: In early drafts, paused packs briefly surfaced as "Unknown / All checks passed" because reporting ran after interrupt; generating reports prior to interrupt resolved this and is guarded by tests.

## Results
- **Golden Evaluation**: `scripts/evaluate.py` scored **10/10 (100.0%)** verdict accuracy across the 10 packs (2 Approve, 5 Reject, 3 Needs Review).
- **Live Run**: Running all 10 packs with Gemini and fallback active (`outputs/results_live.md`, `outputs/extraction_llm_vs_fallback_live.md`) achieved 10/10 verdicts, `gemini+fallback (agreed)` across all 10, and 0 field disagreements. Free-tier 503 bursts were recovered on a single retry.

## What Does Not Work Well
- **Unseen Layouts**: Fallback is tuned to the 10 sample layouts; unseen formats yield `UNCERTAIN` fields and route to review.
- **No OCR**: Text extraction uses `pypdf`; scans yield empty text and route to review.
- **Single-Item Scope**: Multi-item quotes cannot be matched item-by-item and route to review.

## What I Would Do Next
1. Add OCR for scanned PDFs.
2. Extend schema and matching for multi-line items.
3. Build a web review UI.
