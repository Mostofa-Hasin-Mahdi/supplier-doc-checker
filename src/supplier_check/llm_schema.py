"""Flat extraction schema and prompt for the LLM.

All extracted fields are simple nullable strings of the shortest literal text span
verbatim from the document, or null if absent. No quotes, no numbers, no booleans,
and no nested schemas.
"""

from pydantic import BaseModel, ConfigDict, Field


class FlatLLMQuote(BaseModel):
    """Flat raw string extraction from supplier quote document."""

    model_config = ConfigDict(extra="ignore")

    supplier_name: str | None = Field(default=None, description="Supplier name literal text")
    quotation_no: str | None = Field(default=None, description="Quotation number literal text")
    quote_date: str | None = Field(
        default=None, description="Quotation date literal text (e.g. 2026-10-21)"
    )
    reference_pr: str | None = Field(
        default=None, description="Reference PR number literal text (e.g. PR-2026-114)"
    )
    item_code: str | None = Field(default=None, description="Quotation item code (e.g. A, B, C)")
    description: str | None = Field(default=None, description="Quotation item description")
    quantity: str | None = Field(default=None, description="Quoted quantity text (e.g. 12,000)")
    unit: str | None = Field(default=None, description="Unit of measure text (e.g. metre, piece)")
    unit_price: str | None = Field(default=None, description="Unit price text (e.g. 472.00)")
    subtotal: str | None = Field(
        default=None, description="Subtotal amount text if present, or null if no subtotal row"
    )
    vat_amount: str | None = Field(
        default=None, description="VAT amount text if shown separately, or null"
    )
    vat_percent: str | None = Field(
        default=None, description="VAT rate text if shown separately (e.g. 15%), or null"
    )
    total: str | None = Field(
        default=None, description="Grand total amount text (e.g. 6,513,600.00)"
    )
    tin: str | None = Field(
        default=None, description="TIN text if present, or null if missing/available on request"
    )
    bin: str | None = Field(
        default=None, description="BIN text if present, or null if missing/available on request"
    )
    advance_text: str | None = Field(
        default=None, description="Advance payment terms clause/text if present, or null"
    )
    payment_terms_text: str | None = Field(
        default=None, description="Payment schedule terms clause/text if present, or null"
    )
    delivery_terms_text: str | None = Field(
        default=None, description="Delivery schedule terms clause/text if present, or null"
    )
    late_penalty_text: str | None = Field(
        default=None,
        description="Late delivery penalty clause text if present, or null if no clause",
    )
    validity_text: str | None = Field(
        default=None, description="Quotation validity period text if present, or null"
    )


EXTRACTION_PROMPT = """You are an automated quotation document extractor for procurement verification.
Extract the literal text values for the requested fields from the supplier quotation document below.

CRITICAL EXTRACTION RULES:
1. Extract ONLY the shortest literal text span verbatim from the document for each field (e.g. '12,000' for quantity, '472.00' for unit_price, 'metre' for unit, 'A' for item_code).
2. Do NOT include table borders, column headers, or surrounding text.
3. Return null for any field not explicitly present in the document.
4. For TIN or BIN, if the document states 'available on request' or omits registration details, return null for tin and bin.
5. For late_penalty_text, return null if no late delivery penalty clause exists.
6. For subtotal, vat_amount, and vat_percent, return null if VAT is not shown separately or no subtotal row exists.
7. NEVER calculate, extrapolate, guess, or normalise values (e.g. do not convert '4 weeks' into '28', do not calculate math totals, do not emit booleans).
8. Return a single valid JSON object matching the requested schema.

DOCUMENT TEXT:
{document_text}
"""
