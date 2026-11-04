"""Tests for quote reconciliation and parser cross-check."""

from decimal import Decimal
from pathlib import Path

import pypdf

from supplier_check.extract_fallback import extract_fallback_from_text
from supplier_check.models import FieldEvidence, FieldStatus
from supplier_check.reconcile import reconcile_quotes
from supplier_check.verify import verify_and_ground_quote

SAMPLE_PATH = Path("data/supplier-pack-01.pdf")


def get_sample_doc() -> str:
    reader = pypdf.PdfReader(SAMPLE_PATH)
    return "\n".join(page.extract_text() for page in reader.pages)


def test_cross_check_detects_wrong_normalised_number() -> None:
    """If evidence quote says 472.00 but extracted value says 500.00, cross-check sets UNCERTAIN."""
    text = get_sample_doc()
    quote = extract_fallback_from_text(text)
    # Manually tamper unit price value while keeping quote intact
    quote.unit_price = FieldEvidence[Decimal](
        status=FieldStatus.FOUND,
        value=Decimal("500.00"),
        evidence_quote="472.00",
        grounded=True,
    )
    verified = verify_and_ground_quote(quote, text)
    assert verified.unit_price.status == FieldStatus.UNCERTAIN
    assert "disagrees with extracted value" in (verified.unit_price.absence_note or "")


def test_reconciliation_agreement() -> None:
    """When both extractors agree, reconciled quote maintains values."""
    text = get_sample_doc()
    fallback_quote = extract_fallback_from_text(text)
    llm_quote = extract_fallback_from_text(text)

    reconciled, audit = reconcile_quotes(llm_quote, fallback_quote)
    assert reconciled.unit_price.value == Decimal("472.00")
    assert reconciled.unit_price.status == FieldStatus.FOUND
    assert any("Reconciling outputs" in log for log in audit)


def test_reconciliation_disagreement() -> None:
    """When extractors disagree on decision fields, the field is marked UNCERTAIN."""
    text = get_sample_doc()
    fallback_quote = extract_fallback_from_text(text)
    llm_quote = fallback_quote.model_copy(deep=True)

    # Introduce disagreement in delivery_days
    llm_quote.delivery_days = FieldEvidence[int](
        status=FieldStatus.FOUND,
        value=30,
        evidence_quote="within 30 days",
        grounded=True,
    )

    reconciled, audit = reconcile_quotes(llm_quote, fallback_quote)
    assert reconciled.delivery_days.status == FieldStatus.UNCERTAIN
    assert any("Disagreement on 'delivery_days'" in log for log in audit)


def test_reconciliation_llm_only() -> None:
    """When only LLM extractor succeeded, reconciliation returns it with audit note."""
    text = get_sample_doc()
    llm_quote = extract_fallback_from_text(text)
    reconciled, audit = reconcile_quotes(llm_quote, None)

    assert reconciled.supplier_name.value == "Padma Textile Mills Ltd"
    assert any("LLM extractor only" in log for log in audit)


def test_reconciliation_fallback_only() -> None:
    """When only fallback extractor succeeded, reconciliation returns it with audit note."""
    text = get_sample_doc()
    fb_quote = extract_fallback_from_text(text)
    reconciled, audit = reconcile_quotes(None, fb_quote)

    assert reconciled.supplier_name.value == "Padma Textile Mills Ltd"
    assert any("Fallback extractor only" in log for log in audit)


def test_values_match_normalized() -> None:
    """Verify values_match compares Decimals, ints, casefolded text IDs, and booleans accurately."""
    from supplier_check.reconcile import values_match

    assert values_match(Decimal("472.00"), Decimal("472")) is True
    assert values_match(Decimal("472.00"), "472") is True
    assert values_match("472", Decimal("472.00")) is True
    assert values_match(Decimal("12000.00"), Decimal("12000")) is True
    assert values_match(28, 28) is True
    assert values_match(28, 30) is False
    assert values_match("A", "a") is True
    assert values_match("PR-2026-114", "pr-2026-114") is True
    assert values_match("101458013391", "101458013391") is True
    assert values_match(True, True) is True
    assert values_match(False, False) is True
    assert values_match(True, False) is False
    assert values_match(None, None) is True
    assert values_match(None, Decimal("10")) is False


def test_reconciliation_derived_fields_and_line_item_count() -> None:
    """Reconciliation must compare derived boolean fields and line_item_count."""
    text = get_sample_doc()
    fb_quote = extract_fallback_from_text(text)
    llm_quote = fb_quote.model_copy(deep=True)

    # Derived field agreement
    reconciled, audit = reconcile_quotes(llm_quote, fb_quote)
    assert reconciled.late_penalty_clause_present.value is True
    assert reconciled.vat_shown_separately.value is True
    assert reconciled.line_item_count == 1

    # Disagreement on derived field
    llm_quote.late_penalty_clause_present = FieldEvidence[bool](
        status=FieldStatus.DERIVED,
        value=False,
        absence_note="No clause found by LLM",
        grounded=True,
    )
    reconciled_disagree, audit_disagree = reconcile_quotes(llm_quote, fb_quote)
    assert reconciled_disagree.late_penalty_clause_present.status == FieldStatus.UNCERTAIN
    assert any("Disagreement on 'late_penalty_clause_present'" in log for log in audit_disagree)

    # Disagreement on line_item_count
    llm_quote.line_item_count = 2
    reconciled_lic, audit_lic = reconcile_quotes(llm_quote, fb_quote)
    assert reconciled_lic.line_item_count is None
    assert any("Disagreement on 'line_item_count'" in log for log in audit_lic)


