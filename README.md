# Supplier Document Checker (`supplier-check`)

[![CI](https://github.com/Mostofa-Hasin-Mahdi/supplier-doc-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/Mostofa-Hasin-Mahdi/supplier-doc-checker/actions/workflows/ci.yml)

Automated supplier-document verification pipeline for garment manufacturing procurement packs. Evaluates supplier quotations against purchase requests (PRs) and company procurement policies, delivering deterministic verdicts: `APPROVE`, `REJECT`, or `NEEDS_REVIEW`.

## Project Principles & Architecture

- **Fixed Linear LangGraph Pipeline**: `ingest` -> `extract` -> `verify` -> `compare` -> `rules` -> `decide` -> (conditional) `human_review` -> `report`.
- **Strict Separation of Concerns**: The LLM returns only raw value text; deterministic code locates the verbatim evidence line in the PDF text; every value is re-parsed by deterministic parsers; and a second rule-based extractor cross-checks it.
- **Deterministic Python Decisions**: All comparisons, arithmetic checks, tolerance thresholds, and rule evaluations are executed in plain, deterministic Python with `Decimal` arithmetic.
- **"Never Guess" Policy**: Missing, ambiguous, corrupted, or unverifiable fields escalate directly to human review (`NEEDS_REVIEW`). Unknown layouts produce `UNCERTAIN` fields and route to a person.
- **Evidence-Backed Decisions**: Every decision reason cites exact verbatim quotes from the document text. Absence rules cite terms context without inventing or mutating quotes.
- **External Configuration**: All thresholds and rules reside in [`config/rules.yaml`](config/rules.yaml).

## Text Extraction & Dual Extractor Strategy

- **PDF Text Extraction**: Uses `pypdf` exclusively to extract plain text from supplier pack PDFs.
- **Dual Extractor Modes** (`EXTRACTOR=auto|fallback|llm|both`, default `auto`):
  - When `GEMINI_API_KEY` is set: Both extractors run (Gemini and the deterministic regex/layout fallback) and are reconciled. Any disagreement on a decision-relevant field is marked `UNCERTAIN` and escalates to a human reviewer.
  - Without API key: Runs the fallback extractor only; the audit report clearly displays `fallback only (no key)`.
  - LLM resilience: Catches transient errors (e.g. 503 high demand), retries once, falls back smoothly to regex, and logs `fallback only (LLM failed)`.

## Installation

```bash
# Clone the repository
git clone https://github.com/Mostofa-Hasin-Mahdi/supplier-doc-checker.git
cd supplier-doc-checker

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install editable package with dev & test dependencies
pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` to configure optional Gemini API credentials:
```bash
cp .env.example .env
```

```ini
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
EXTRACTOR=auto
```

## CLI Usage

The CLI (`supplier-check` or `python -m supplier_check.cli`) provides commands for verifying packs and handling human reviews:

```bash
# Verify a single pack (accepts custom --pr, --rules, --mode, --interactive, --json)
supplier-check check data/supplier-pack-01.pdf

# Output single pack result as JSON
supplier-check check data/supplier-pack-01.pdf --json

# Verify all packs in directory without blocking (queues packs needing review)
supplier-check check-all data/ --pr data/purchase-request.csv --rules config/rules.yaml

# List queued reviews
supplier-check review

# Resume a paused pack (prompts interactively for decision and reviewer notes)
supplier-check review <thread_id>
```

In batch runs, packs requiring human attention show `Pending Review` in the **Final Verdict** column. The original `system_verdict` and the reviewer's `final_verdict` are always preserved side-by-side.

## Try Your Own Quote

You can run any supplier quotation PDF through `check`:

```bash
# Check custom PDF quotation with custom purchase request and rules
supplier-check check path/to/your-quote.pdf --pr path/to/purchase-request.csv --rules config/rules.yaml

# Get clean structured JSON output
supplier-check check path/to/your-quote.pdf --json
```

### What to Expect:
- **Same document layout**: If your quotation follows the layout of the sample packs (table headers for item, quantity, unit price, and standard numbered terms clauses), the deterministic fallback extracts fields cleanly.
- **Different / unseen document layout**: The rule-based fallback was built specifically for the 10 sample document structures. On unseen layouts, fields that do not match expected layout anchors are safely marked `UNCERTAIN`. Under the "Never Guess" policy, this immediately escalates to `Needs a person to check` with reasons listing the exact fields that could not be verified, never giving a false `Approve` or `Reject`.
- **With Gemini enabled (`GEMINI_API_KEY`)**: Gemini can flexibly read various layouts; however, whenever Gemini and the fallback disagree on any decision-critical field, that field is deemed `UNCERTAIN` and routes safely to human review.

## Results

Evaluation across the 10 provided supplier quotation packs against `tests/golden/expected.json` (from `outputs/eval_report.md` and `outputs/results.md`):

| Pack | Supplier | Unit Price (BDT) | Requested Max | System Verdict | Final Verdict | Extractor | Primary Rationale / Triggered Rules |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **01** | Padma Textile Mills Ltd | 472.00 | 480.00 | **Approve** | **Approve** | `gemini+fallback (agreed)` | All checks passed (Price, Qty, Terms, TIN/BIN, Math accurate) |
| **02** | Jamuna Trims and Accessories | 36.00 | 38.00 | **Approve** | **Approve** | `gemini+fallback (agreed)` | All checks passed (Price, Qty, Terms, TIN/BIN, Math accurate) |
| **03** | Karnaphuli Yarn Traders | 229.00 | 210.00 | **Reject** | **Reject** | `gemini+fallback (agreed)` | **RULE_REJ_01_PRICE_MAX**: 229.00 is 9.05% above max 210.00 (limit 3.0%) *(quote: "229.00")* |
| **04** | Surma Packaging Industries | 6.65 | 6.50 | **Needs a person** | **Pending Review** | `gemini+fallback (agreed)` | **RULE_REV_01_PRICE_TOLERANCE**: 6.65 is 2.31% above max 6.50 (within 3.0% tolerance) *(quote: "6.65")* |
| **05** | Meghna Carton Works | 92.00 | 95.00 | **Reject** | **Reject** | `gemini+fallback (agreed)` | **RULE_REJ_02_ADVANCE_MAX**: Advance payment requested is 40%, exceeding maximum allowed 20.0% *(quote: "1. Payment. 40% advance...")* |
| **06** | Teesta Fabrics Ltd | 465.00 | 480.00 | **Reject** | **Reject** | `gemini+fallback (agreed)` | **RULE_REJ_03_NO_PENALTY**: No late-delivery penalty clause found. Terms clauses present: Payment, Delivery, Validity, Quality, Disputes |
| **07** | Rupsha Zipper Factory | 35.00 | 38.00 | **Needs a person** | **Pending Review** | `gemini+fallback (agreed)` | **RULE_REV_02_QTY_TOLERANCE**: 16500 is 17.50% below requested 20000 (tolerance 5.0%) *(quote: "16,500")* |
| **08** | Bhairab Thread and Co | 205.00 | 210.00 | **Reject** | **Reject** | `gemini+fallback (agreed)` | **RULE_REJ_05_TAX_ID**: Supplier TIN and BIN registration is missing *(quote: "Supplier registration details available on request.")*<br>**RULE_REV_10_PENALTY_AMBIGUOUS**: Penalty clause does not explicitly state calculation base as 'order value' *(quote: "3. Delay. Late delivery penalty of 0.5% per week of delay.")* |
| **09** | Dhaleshwari Poly Pack | 6.40 | 6.50 | **Needs a person** | **Pending Review** | `gemini+fallback (agreed)` | **RULE_REV_03_PAYMENT_TERMS**: Payment terms days are unclear, range specified, or missing *(quote: "1. Payment. 5% advance... 30 to 90 days...")*<br>**RULE_REV_06_MATH_SUBTOTAL**: Subtotal 322000.00 does not equal Qty x Price (320000.00) within tolerance 1.0 *(quote: "Subtotal 322,000.00")* |
| **10** | Kushiyara Box Industries | 94.00 | 95.00 | **Reject** | **Reject** | `gemini+fallback (agreed)` | **RULE_REJ_06_DELIVERY_MAX**: Delivery promised in 60 days, exceeding maximum allowed 45 days *(quote: "2. Delivery. Delivery within 60 days of PO.")*<br>**RULE_REV_05_VAT_PRESENTATION**: VAT is not shown separately at 15% (e.g. VAT included or missing breakdown) *(quote: "Total (all taxes included) 282,000.00")* |

- **Evaluation Accuracy**: **10/10 (100.0%)** verdicts matching expected golden dataset.

## Live Run

Running all 10 packs through the live graph with Gemini enabled (`outputs/results_live.md`, `outputs/extraction_llm_vs_fallback_live.md`, `outputs/live_run_status.md`):
- **10 of 10 packs** ran with `gemini+fallback (agreed)`.
- **0 decision field disagreements** between Gemini and the deterministic fallback.
- **10/10 verdicts** matched the expected golden outcomes.
- Transient Google free-tier `503 UNAVAILABLE` errors occurred during bursts and were seamlessly recovered on the single automated retry without degrading the pipeline.

## How to Change a Rule

All business thresholds and rule toggles are externalized in [`config/rules.yaml`](config/rules.yaml). No Python code changes are required to adjust policies:

```yaml
# Procurement Rule Thresholds and Configuration
# Note: Keep all policy limits, thresholds, and comparison margins here.
# Do not hardcode these in source logic.

rules:
  # Price tolerance thresholds in percentage
  price_tolerance_pct: 3.0  # Unit price <= 3% over max is REVIEW; > 3% is REJECT

  # Quantity tolerance threshold in percentage
  quantity_tolerance_pct: 5.0  # Quantity differing by > 5% is REVIEW

  # Advance payment limit in percentage
  max_advance_pct: 20.0  # Advance > 20% is REJECT

  # Delivery day limits
  max_delivery_days: 45      # Delivery > 45 days is REJECT
  review_delivery_days_min: 31  # Delivery 31 to 45 days is REVIEW
  review_delivery_days_max: 45

  # Payment terms day limits
  min_payment_days: 30  # Payment terms outside 30 to 60 days is REVIEW
  max_payment_days: 60

  # Penalty clause rules
  min_penalty_pct_per_week: 0.5  # Penalty must be >= 0.5% per week of delay
  penalty_base_unstated_policy: review  # alternatives: accept, review

  # Statutory Tax Registration Policy
  tin_bin_policy: reject_if_either_missing  # alternatives: reject_if_both_missing, review_if_one_missing

  # VAT rules
  required_vat_percent: 15.0

  # Quotation validity
  min_validity_days: 30  # Validity < 30 days is REVIEW

  # Arithmetic rounding tolerance (in currency units, e.g. BDT)
  math_tolerance: 1.00

  # Currency and item consistency
  strict_currency_match: true
```

To adjust the advance payment threshold from 20% to 15%, simply edit line 13: change `max_advance_pct: 20.0` to `max_advance_pct: 15.0`.

## Assumptions

1. **TIN / BIN Registration**: Company procurement policy states "TIN or BIN is missing." Configured by default as `reject_if_either_missing` (`RULE_REJ_05_TAX_ID`), rejecting quotations lacking statutory tax IDs.
2. **Penalty Base Specification**: Late penalty clauses must explicitly specify "order value" as the calculation base. Clauses stating only "0.5% per week of delay" (e.g. Pack 08) trigger `RULE_REV_10_PENALTY_AMBIGUOUS` (`NEEDS_REVIEW`).
3. **VAT Presentation vs Arithmetic**: VAT presentation is verified independently from arithmetic. If a quote presents a "VAT-inclusive" price without breaking out VAT at 15% (e.g. Pack 10), it triggers `RULE_REV_05_VAT_PRESENTATION` (`NEEDS_REVIEW`).
4. **Absent Subtotal Handling**: When a document omits a separate subtotal line (Pack 10), the arithmetic checker checks `Total = Quantity × Unit Price` directly rather than failing on missing subtotal.
5. **VAT-Inclusive Prices**: A unit price marked "VAT included" is not strictly like-for-like with the PR maximum unit price (which is ex-VAT), requiring buyer review.

## Limitations

- **Fallback Tuned to 10 Layouts**: The regex/layout fallback parser is specifically tuned to the patterns of the 10 provided sample packs. It does not generalize to arbitrary PDF formats; unseen layouts safely produce `UNCERTAIN` fields and route to human review.
- **Scanned PDFs & OCR**: Text extraction uses `pypdf`. Image-only or scanned PDFs without embedded text layers cannot be extracted (produce empty text) and immediately route to `NEEDS_REVIEW`.
- **Multi-Item Quotes**: The comparison node is designed for single-item procurement quotes. Quotes with multiple items or undetermined line item structures trigger `RULE_REV_12_ITEM_MATCH` for human triage.
- **Free-Tier Gemini Limits**: Free-tier Gemini endpoints encounter periodic rate limits and transient 503 spikes. While retries recover most spikes, high concurrency requires paid tier provisioning.
- **Sample Set Scope**: 10 sample packs represent a focused dataset; 100% accuracy on 10 packs demonstrates deterministic compliance on known samples but does not represent generalized performance across industry layouts.
- **Test Coverage**: Overall codebase coverage is 74%, and `cli.py` is exercised primarily through subprocess tests rather than direct in-process mock tests.

## Testing & Quality Assurance

- **Test Suite**: 106 passing offline tests.
- **14 Mutation Tests**: Verifying deterministic rule sensitivity to targeted document mutations.
- **Boundary & Never-Guess Tests**: Verifying exact limits (29 vs 30 days, 20% vs 20.1% advance) and ensuring garbled, missing, or hallucinated data never pass.
- **Cross-Process Resume**: Verifies that SQLite checkpointer state persists and resumes across separate processes.
- **CI**: Enforced via GitHub Actions running Ruff linter (`ruff check .`), formatter check (`ruff format --check .`), pytest (`pytest -m "not live"`), and automated evaluation report generation.

```bash
# Run tests
pytest -m "not live"

# Run linter & formatter checks
ruff check .
ruff format --check .

# Run evaluation against golden expected dataset
python scripts/evaluate.py
```

## How It Was Built

Implemented with **Antigravity** (an AI coding agent) via structured, staged prompts, with every phase's architecture, code implementation, test suites, and documentation reviewed and verified at each step by the engineer.
