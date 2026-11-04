"""Dump extraction results of the fallback extractor across all 10 supplier packs."""

from pathlib import Path

import pypdf

from supplier_check.extract_fallback import extract_fallback_from_text
from supplier_check.models import ExtractedQuote, FieldEvidence
from supplier_check.verify import verify_and_ground_quote

DATA_DIR = Path("data")
OUTPUT_FILE = Path("outputs/extraction_fallback.md")


def read_pdf_text(pack_path: Path) -> str:
    reader = pypdf.PdfReader(pack_path)
    return "\n".join(page.extract_text() for page in reader.pages)


def format_field(fe: FieldEvidence) -> str:
    val_str = str(fe.value) if fe.value is not None else "None"
    return f"{fe.status.value}:{val_str}"


def main() -> None:
    pdf_files = sorted(DATA_DIR.glob("supplier-pack-*.pdf"))
    if not pdf_files:
        print("No supplier-pack-*.pdf files found in data/")
        return

    # Collect fields to display
    field_names = [
        "supplier_name",
        "item_code",
        "quantity",
        "unit_price",
        "subtotal",
        "vat_amount",
        "vat_percent",
        "vat_shown_separately",
        "total",
        "tin",
        "bin",
        "advance_percent",
        "payment_days",
        "delivery_days",
        "late_penalty_percent_per_week",
        "late_penalty_clause_present",
        "late_penalty_specifies_order_value",
        "validity_days",
    ]

    header_cols = ["Pack"] + field_names
    table_lines = [
        "# Fallback Extractor Dump (All 10 Packs)\n",
        "| " + " | ".join(header_cols) + " |",
        "| " + " | ".join(["---"] * len(header_cols)) + " |",
    ]

    for pdf_path in pdf_files:
        pack_name = pdf_path.stem.replace("supplier-pack-", "Pack ")
        text = read_pdf_text(pdf_path)
        raw_quote = extract_fallback_from_text(text)
        verified: ExtractedQuote = verify_and_ground_quote(raw_quote, text)

        row_vals = [pack_name]
        for fname in field_names:
            fe = getattr(verified, fname)
            row_vals.append(format_field(fe))
        table_lines.append("| " + " | ".join(row_vals) + " |")

    content = "\n".join(table_lines) + "\n"
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    print(f"Dumped fallback extraction table to {OUTPUT_FILE}")
    print(content)


if __name__ == "__main__":
    main()
