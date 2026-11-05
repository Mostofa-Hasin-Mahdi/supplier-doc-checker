"""Tests for LLM clients, FakeLLM error scenarios, and live Gemini extraction."""

import os

import pytest

from supplier_check.llm_client import (
    FakeLLMClient,
    GeminiClient,
    extract_quote_with_llm_or_fallback,
)
from supplier_check.models import FieldStatus
from supplier_check.verify import verify_and_ground_quote

SAMPLE_DOC = """
Padma Textile Mills Ltd
QUOTATION
 Quotation no.
QT-2026-901
Date
2026-10-21
Reference
PR-2026-114
Item
Description
Qty
Unit
Unit price (BDT)
Amount (BDT)
A
Cotton twill fabric, 280 gsm
12,000
metre
472.00
5,664,000.00
Subtotal
5,664,000.00
VAT 15%
849,600.00
Total
6,513,600.00
Supplier TIN: 101458013391 BIN: 000170141-0101
TERMS AND CONDITIONS
1. Payment. 10% advance payable with the purchase order. Balance payable within 45 days after delivery.
2. Delivery. Delivery within 24 days of receiving the purchase order.
3. Delay. Late delivery penalty: 1% of order value for each full week of delay.
4. Validity. This quotation is valid for 45 days from the date above.
"""


def test_fake_llm_valid_extraction() -> None:
    """Test standard valid proposed extraction through FakeLLMClient."""
    valid_canned = {
        "supplier_name": "Padma Textile Mills Ltd",
        "quotation_no": "QT-2026-901",
        "quote_date": "2026-10-21",
        "reference_pr": "PR-2026-114",
        "item_code": "A",
        "description": "Cotton twill fabric, 280 gsm",
        "quantity": "12,000",
        "unit": "metre",
        "unit_price": "472.00",
        "subtotal": "5,664,000.00",
        "vat_amount": "849,600.00",
        "vat_percent": "15%",
        "total": "6,513,600.00",
        "tin": "101458013391",
        "bin": "000170141-0101",
        "advance_text": "10% advance payable with the purchase order.",
        "payment_terms_text": "Balance payable within 45 days after delivery.",
        "delivery_terms_text": "Delivery within 24 days of receiving the purchase order.",
        "late_penalty_text": "Late delivery penalty: 1% of order value for each full week of delay.",
        "validity_text": "This quotation is valid for 45 days from the date above.",
    }
    client = FakeLLMClient(valid_canned)
    quote, extractor = extract_quote_with_llm_or_fallback(SAMPLE_DOC, client)
    assert extractor == "llm"
    assert quote.supplier_name.value == "Padma Textile Mills Ltd"

    # Verify and ground
    verified = verify_and_ground_quote(quote, SAMPLE_DOC)
    assert verified.supplier_name.grounded is True
    assert verified.late_penalty_specifies_order_value.value is True


def test_fake_llm_invalid_json_falls_back_to_regex() -> None:
    """When LLM returns invalid JSON or unparseable text, pipeline cleanly falls back."""
    client = FakeLLMClient("INVALID { JSON !!!")
    quote, extractor = extract_quote_with_llm_or_fallback(SAMPLE_DOC, client)
    assert extractor == "fallback"
    assert quote.supplier_name.value == "Padma Textile Mills Ltd"


def test_fake_llm_hallucinated_quote_flagged_uncertain() -> None:
    """When LLM returns a fabricated quote, grounding verifier flags status UNCERTAIN."""
    bad_canned = {
        "supplier_name": "Hallucinated Supplier Ltd",
        "unit_price": "999.00",
        "late_penalty_text": "Penalty 5%",
    }
    client = FakeLLMClient(bad_canned)
    quote, extractor = extract_quote_with_llm_or_fallback(SAMPLE_DOC, client)
    assert extractor == "llm"

    verified = verify_and_ground_quote(quote, SAMPLE_DOC)
    assert verified.supplier_name.status == FieldStatus.UNCERTAIN
    assert verified.supplier_name.grounded is False
    assert verified.unit_price.status == FieldStatus.UNCERTAIN
    assert verified.unit_price.grounded is False


def test_fake_llm_wrong_number_or_null_where_text_exists() -> None:
    """When LLM emits null where text exists or wrong number, pipeline flags UNCERTAIN."""
    canned_missing = {
        "supplier_name": None,
        "late_penalty_text": "1% of order value for each full week of delay",
    }
    client = FakeLLMClient(canned_missing)
    quote, extractor = extract_quote_with_llm_or_fallback(SAMPLE_DOC, client)
    assert extractor == "llm"
    assert quote.supplier_name.status == FieldStatus.UNCERTAIN


def test_find_enclosing_evidence_table_line_vs_terms_clause() -> None:
    """find_enclosing_evidence returns table line for table fields and full clause for Terms."""
    from supplier_check.llm_client import find_enclosing_evidence

    # Table field: unit_price should match line '472.00'
    q_table, sec_table = find_enclosing_evidence("472.00", SAMPLE_DOC, "unit_price")
    assert sec_table == "table"
    assert q_table == "472.00"

    # Terms field: advance_text should return the entire numbered Payment clause
    q_terms, sec_terms = find_enclosing_evidence("10% advance", SAMPLE_DOC, "advance_text")
    assert sec_terms == "terms"
    assert "1. Payment." in q_terms
    assert "Balance payable within 45 days" in q_terms


def test_find_enclosing_evidence_duplicate_value_logs_ambiguity() -> None:
    """When a value appears in multiple lines, first match in preferred section is returned and logged."""
    from supplier_check.llm_client import find_enclosing_evidence

    # '5,664,000.00' appears twice: once in item row, once in Subtotal row
    audit_log: list[str] = []
    quote, sec = find_enclosing_evidence("5,664,000.00", SAMPLE_DOC, "subtotal", audit_log)
    assert quote is not None
    assert sec == "table"
    assert any("matched 2 occurrences" in log for log in audit_log)


def test_find_enclosing_evidence_not_found_returns_none() -> None:
    """When a value cannot be found anywhere in document text, returns (None, None)."""
    from supplier_check.llm_client import find_enclosing_evidence

    quote, sec = find_enclosing_evidence("non_existent_token_999", SAMPLE_DOC, "quantity")
    assert quote is None
    assert sec is None


def test_hallucination_guard_demotes_unfound_raw_value_to_uncertain() -> None:
    """An LLM-proposed raw value that is not in the text triggers the hallucination guard."""
    bad_canned = {
        "supplier_name": "Padma Textile Mills Ltd",
        "unit_price": "999.00",  # Not in SAMPLE_DOC
        "quantity": "99,999",  # Not in SAMPLE_DOC
    }
    client = FakeLLMClient(bad_canned)
    quote, extractor = extract_quote_with_llm_or_fallback(SAMPLE_DOC, client)
    assert extractor == "llm"
    assert quote.unit_price.status == FieldStatus.UNCERTAIN
    assert quote.unit_price.value is None
    assert quote.unit_price.grounded is False
    assert quote.quantity.status == FieldStatus.UNCERTAIN
    assert quote.quantity.value is None
    assert quote.quantity.grounded is False


@pytest.mark.live
def test_live_gemini_client_smoke() -> None:
    """Live smoke test calling Google Gemini (requires GEMINI_API_KEY)."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("No GEMINI_API_KEY configured for live test")

    client = GeminiClient()
    result = client.extract(SAMPLE_DOC)
    assert isinstance(result, dict)
    assert "supplier_name" in result
