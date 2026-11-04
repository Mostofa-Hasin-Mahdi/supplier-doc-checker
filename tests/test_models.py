"""Tests for data models and validation rules."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from supplier_check.models import (
    Decision,
    ExtractedQuote,
    FieldEvidence,
    FieldStatus,
    PurchaseRequestItem,
    RuleResult,
    Severity,
    Verdict,
)


def test_verdict_display_names() -> None:
    """Verify verdict display string mappings."""
    assert Verdict.APPROVE.display_name == "Approve"
    assert Verdict.REJECT.display_name == "Reject"
    assert Verdict.NEEDS_REVIEW.display_name == "Needs a person to check"

    decision = Decision(verdict=Verdict.NEEDS_REVIEW)
    assert decision.display_verdict == "Needs a person to check"


def test_field_evidence_status_found_valid() -> None:
    """Status FOUND requires non-empty value and evidence quote."""
    fe = FieldEvidence[str](
        status=FieldStatus.FOUND,
        value="Padma Textile Mills Ltd",
        evidence_quote="Padma Textile Mills Ltd",
        grounded=True,
    )
    assert fe.status == FieldStatus.FOUND
    assert fe.value == "Padma Textile Mills Ltd"
    assert fe.grounded is True


def test_field_evidence_status_found_falsy_values() -> None:
    """Status FOUND must accept falsy-but-valid values: Decimal('0') and False."""
    fe_decimal_zero = FieldEvidence[Decimal](
        status=FieldStatus.FOUND,
        value=Decimal("0"),
        evidence_quote="0% advance",
        grounded=True,
    )
    assert fe_decimal_zero.status == FieldStatus.FOUND
    assert fe_decimal_zero.value == Decimal("0")

    fe_bool_false = FieldEvidence[bool](
        status=FieldStatus.FOUND,
        value=False,
        evidence_quote="No late penalty clause mentioned",
        grounded=True,
    )
    assert fe_bool_false.status == FieldStatus.FOUND
    assert fe_bool_false.value is False


def test_field_evidence_status_found_none_rejected() -> None:
    """Status FOUND with None must raise ValidationError."""
    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=None,
            evidence_quote="Padma Textile Mills Ltd",
        )

    with pytest.raises(ValidationError):
        FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=None,
            evidence_quote="Some quote",
        )


def test_field_evidence_status_found_empty_string_rejected() -> None:
    """Status FOUND with empty string must raise ValidationError."""
    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="",
            evidence_quote="Padma Textile Mills Ltd",
        )

    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="   ",
            evidence_quote="Padma Textile Mills Ltd",
        )


def test_field_evidence_status_found_missing_quote_raises() -> None:
    """Status FOUND with missing or whitespace-only quote must raise ValidationError."""
    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="Padma Textile Mills Ltd",
            evidence_quote=None,
        )

    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="Padma Textile Mills Ltd",
            evidence_quote="   ",
        )


def test_field_evidence_status_absent() -> None:
    """Status ABSENT must have value None and can hold absence_note."""
    fe = FieldEvidence[str](
        status=FieldStatus.ABSENT,
        value=None,
        evidence_quote=None,
        absence_note="No TIN/BIN found in registration details",
        grounded=False,
    )
    assert fe.status == FieldStatus.ABSENT
    assert fe.value is None
    assert fe.absence_note == "No TIN/BIN found in registration details"

    # Value provided when ABSENT must raise ValidationError
    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.ABSENT,
            value="Some Value",
            evidence_quote=None,
        )


def test_field_evidence_status_uncertain() -> None:
    """Status UNCERTAIN may carry anything."""
    fe_none = FieldEvidence[Decimal](
        status=FieldStatus.UNCERTAIN,
        value=None,
        evidence_quote="within 30 to 90 days as agreed",
    )
    assert fe_none.value is None

    fe_val = FieldEvidence[Decimal](
        status=FieldStatus.UNCERTAIN,
        value=Decimal("10.0"),
        evidence_quote="maybe 10%",
    )
    assert fe_val.value == Decimal("10.0")


def test_extracted_quote_model_construction() -> None:
    """Test full ExtractedQuote construction with Decimal, int, and optional line_item_count."""
    # Test with line_item_count None (undetermined)
    quote_none_line = ExtractedQuote(
        supplier_name=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="Padma Textile Mills Ltd",
            evidence_quote="Padma Textile Mills Ltd",
        ),
        quotation_no=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="QT-2026-901",
            evidence_quote="QT-2026-901",
        ),
        quote_date=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="2026-10-21",
            evidence_quote="2026-10-21",
        ),
        reference_pr=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="PR-2026-114",
            evidence_quote="PR-2026-114",
        ),
        line_item_count=None,
        item_code=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="A",
            evidence_quote="A",
        ),
        description=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="Cotton twill fabric, 280 gsm",
            evidence_quote="Cotton twill fabric, 280 gsm",
        ),
        quantity=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("12000"),
            evidence_quote="12,000",
        ),
        unit=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="metre",
            evidence_quote="metre",
        ),
        unit_price=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("472.00"),
            evidence_quote="472.00",
        ),
        subtotal=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("5664000.00"),
            evidence_quote="5,664,000.00",
        ),
        vat_amount=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("849600.00"),
            evidence_quote="849,600.00",
        ),
        vat_percent=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("15.0"),
            evidence_quote="VAT 15%",
        ),
        vat_shown_separately=FieldEvidence[bool](
            status=FieldStatus.FOUND,
            value=True,
            evidence_quote="VAT 15%\n849,600.00",
        ),
        total=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("6513600.00"),
            evidence_quote="6,513,600.00",
        ),
        tin=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="101458013391",
            evidence_quote="Supplier TIN: 101458013391",
        ),
        bin=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="000170141-0101",
            evidence_quote="BIN: 000170141-0101",
        ),
        advance_percent=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("10.0"),
            evidence_quote="10% advance payable",
        ),
        payment_terms_text=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="Balance payable within 45 days after delivery",
            evidence_quote="Balance payable within 45 days after delivery",
        ),
        payment_days=FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=45,
            evidence_quote="within 45 days after delivery",
        ),
        delivery_terms_text=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="Delivery within 24 days of receiving the purchase order",
            evidence_quote="Delivery within 24 days of receiving the purchase order",
        ),
        delivery_days=FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=24,
            evidence_quote="within 24 days",
        ),
        late_penalty_percent_per_week=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("1.0"),
            evidence_quote="1% of order value for each full week of delay",
        ),
        late_penalty_clause_present=FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=True,
            evidence_quote="Late delivery penalty: 1% of order value",
        ),
        late_penalty_specifies_order_value=FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=True,
            evidence_quote="1% of order value",
        ),
        validity_days=FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=45,
            evidence_quote="valid for 45 days",
        ),
    )
    assert quote_none_line.line_item_count is None
    assert quote_none_line.unit_price.value == Decimal("472.00")
    assert quote_none_line.quantity.value == Decimal("12000")


def test_field_evidence_status_derived() -> None:
    """Status DERIVED accepts boolean value with evidence_quote or absence_note."""
    fe_with_quote = FieldEvidence[bool](
        status=FieldStatus.DERIVED,
        value=True,
        evidence_quote="Late delivery penalty: 1% of order value",
        grounded=True,
    )
    assert fe_with_quote.status == FieldStatus.DERIVED
    assert fe_with_quote.value is True

    fe_with_absence = FieldEvidence[bool](
        status=FieldStatus.DERIVED,
        value=False,
        evidence_quote=None,
        absence_note="No late delivery penalty clause found in terms",
        grounded=True,
    )
    assert fe_with_absence.status == FieldStatus.DERIVED
    assert fe_with_absence.value is False

    # DERIVED requires a boolean value
    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.DERIVED,
            value="not a bool",
            evidence_quote="some quote",
        )

    # DERIVED requires either evidence_quote or absence_note
    with pytest.raises(ValidationError):
        FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=True,
            evidence_quote=None,
            absence_note=None,
        )


def test_ordinary_field_found_without_quote_rejected() -> None:
    """Ordinary extracted fields (price, qty, tin, bin, days, pct) must strictly reject FOUND without quote."""
    # unit_price
    with pytest.raises(ValidationError):
        FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("472.00"),
            evidence_quote=None,
        )

    # quantity
    with pytest.raises(ValidationError):
        FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("12000"),
            evidence_quote="",
        )

    # tin
    with pytest.raises(ValidationError):
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="101458013391",
            evidence_quote=None,
        )

    # delivery_days
    with pytest.raises(ValidationError):
        FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=24,
            evidence_quote=None,
        )


def test_purchase_request_item() -> None:
    """Verify PurchaseRequestItem model."""
    pr_item = PurchaseRequestItem(
        pr_number="PR-2026-114",
        item_code="A",
        description="Cotton twill fabric, 280 gsm",
        unit="metre",
        quantity_requested=Decimal("12000"),
        max_unit_price=Decimal("480.00"),
    )
    assert pr_item.item_code == "A"
    assert pr_item.max_unit_price == Decimal("480.00")


def test_decision_and_rule_result() -> None:
    """Verify RuleResult and Decision structures."""
    rule = RuleResult(
        rule_id="RULE_REJ_01_PRICE_MAX",
        severity=Severity.REJECT,
        message="Price exceeds maximum by more than 3%",
        evidence_quote="229.00",
    )
    decision = Decision(
        verdict=Verdict.REJECT,
        triggered_rules=[rule],
        reasons=["Price exceeds maximum by more than 3% (quote: '229.00')"],
    )
    assert decision.verdict == Verdict.REJECT
    assert decision.display_verdict == "Reject"
    assert len(decision.triggered_rules) == 1
