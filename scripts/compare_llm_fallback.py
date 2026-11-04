"""Run live Gemini extraction vs Fallback extractor across all 10 supplier packs."""

import os
import time
from pathlib import Path

import dotenv
import pypdf

from supplier_check.extract_fallback import extract_fallback_from_text
from supplier_check.llm_client import GeminiClient
from supplier_check.models import FieldEvidence
from supplier_check.reconcile import DECISION_FIELDS, values_match
from supplier_check.verify import verify_and_ground_quote

dotenv.load_dotenv()

DATA_DIR = Path("data")
OUTPUT_FILE = Path("outputs/extraction_llm_vs_fallback.md")


def read_pdf_text(pack_path: Path) -> str:
    reader = pypdf.PdfReader(pack_path)
    return "\n".join(page.extract_text() for page in reader.pages)


def are_values_equal(v1: object, v2: object) -> bool:
    return values_match(v1, v2)


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    run_live = bool(api_key and os.getenv("RUN_LIVE_LLM") == "1")

    client = None
    if run_live:
        print("Running live Gemini extraction vs Fallback on all 10 packs...")
        client = GeminiClient(api_key=api_key)
    else:
        print("Running in offline mode (LLM marked 'not run')...")

    pdf_files = sorted(DATA_DIR.glob("supplier-pack-*.pdf"))
    all_fields_to_compare = DECISION_FIELDS + ["line_item_count"]
    field_agreements: dict[str, int] = {f: 0 for f in all_fields_to_compare}
    total_packs = len(pdf_files)
    all_disagreements: list[str] = []

    SPECIAL_STATUS_FIELDS = [
        "tin",
        "bin",
        "subtotal",
        "vat_amount",
        "vat_percent",
        "payment_days",
        "late_penalty_percent_per_week",
    ]
    status_records: list[dict[str, str]] = []

    for pdf_path in pdf_files:
        pack_name = pdf_path.stem.replace("supplier-pack-", "Pack ")
        text = read_pdf_text(pdf_path)

        # 1. Fallback extractor
        fb_raw = extract_fallback_from_text(text)
        fb_quote = verify_and_ground_quote(fb_raw, text)

        # 2. Live LLM extractor (only if run_live is True)
        llm_quote = None
        if run_live and client is not None:
            try:
                from supplier_check.llm_client import map_flat_to_extracted_quote
                from supplier_check.llm_schema import FlatLLMQuote

                raw_dict = client.extract(text)
                flat = FlatLLMQuote.model_validate(raw_dict)
                llm_raw = map_flat_to_extracted_quote(flat, text)
                llm_quote = verify_and_ground_quote(llm_raw, text)
            except Exception as e:
                print(f"[{pack_name}] LLM extraction failed: {e}")
                llm_quote = None

        # Record statuses for special fields
        for field in SPECIAL_STATUS_FIELDS:
            fb_fe: FieldEvidence = getattr(fb_quote, field)
            llm_fe: FieldEvidence = getattr(llm_quote, field) if llm_quote else None
            llm_st = llm_fe.status.value if llm_fe else ("not run" if not run_live else "FAILED")
            status_records.append({
                "pack": pack_name,
                "field": field,
                "llm_status": llm_st,
                "fb_status": fb_fe.status.value,
            })

        # Compare decision fields
        for field in DECISION_FIELDS:
            fb_fe: FieldEvidence = getattr(fb_quote, field)
            llm_fe: FieldEvidence = getattr(llm_quote, field) if llm_quote else None

            llm_val = llm_fe.value if llm_fe else None
            fb_val = fb_fe.value

            agrees = llm_quote is not None and are_values_equal(llm_val, fb_val) and (llm_fe.status == fb_fe.status)
            if agrees:
                field_agreements[field] += 1
            else:
                src_line = fb_fe.evidence_quote or (llm_fe.evidence_quote if llm_fe else None) or "N/A"
                disagreement_desc = (
                    f"- **{pack_name}** `{field}`: "
                    f"LLM=`{llm_fe.status.value if llm_fe else ('not run' if not run_live else 'FAILED')}`({llm_val}) vs "
                    f"Fallback=`{fb_fe.status.value}`({fb_val}) | Source line: `{src_line}`"
                )
                all_disagreements.append(disagreement_desc)

        # Compare line_item_count
        fb_lic = fb_quote.line_item_count
        llm_lic = llm_quote.line_item_count if llm_quote else None
        if llm_quote is not None and fb_lic == llm_lic:
            field_agreements["line_item_count"] += 1
        else:
            all_disagreements.append(
                f"- **{pack_name}** `line_item_count`: LLM=({llm_lic if run_live else 'not run'}) vs Fallback=({fb_lic})"
            )

        print(f"Processed {pack_name} successfully.")
        if run_live:
            time.sleep(1)

    # Format Markdown Report
    model_name = client.model_name if (run_live and client) else "offline / not run"
    lines = [
        "# Extraction Comparison: LLM vs Fallback (10 Packs)\n",
        f"**Model:** `{model_name}`  ",
        f"**Total Packs Evaluated:** {total_packs}\n",
        "## Field Agreement Rate\n",
        "| Decision / Derived Field | Matches / Total | Agreement Rate |",
        "| :--- | :--- | :--- |",
    ]

    for field in all_fields_to_compare:
        matches = field_agreements[field]
        pct = (matches / total_packs) * 100
        lines.append(f"| `{field}` | {matches} / {total_packs} | {pct:.1f}% |")

    lines.append("\n## Special Fields Extraction Status (Per-Pack)\n")
    lines.append("| Pack | Field | LLM Status | Fallback Status | Status Match |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for r in status_records:
        if r["llm_status"] == "not run":
            match_str = "not run"
        else:
            match_str = "YES" if r["llm_status"] == r["fb_status"] else "**NO**"
        lines.append(f"| {r['pack']} | `{r['field']}` | `{r['llm_status']}` | `{r['fb_status']}` | {match_str} |")

    lines.append("\n## Disagreements Log\n")
    if all_disagreements:
        lines.extend(all_disagreements)
    else:
        lines.append("No disagreements found across all evaluated decision and derived fields.")

    content = "\n".join(lines) + "\n"
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    print(f"Comparison report saved to {OUTPUT_FILE}")
    print("\nSummary:")
    print(content)


if __name__ == "__main__":
    main()

