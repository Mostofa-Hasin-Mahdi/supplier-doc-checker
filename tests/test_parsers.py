"""Tests for deterministic parsers and grounding verifier."""

from decimal import Decimal

from supplier_check.models import ExtractedQuote, FieldEvidence, FieldStatus
from supplier_check.parsers import (
    parse_advance,
    parse_days,
    parse_money,
    parse_payment_days,
    parse_percent,
    parse_tin_bin,
)
from supplier_check.verify import is_grounded_in_text, verify_and_ground_quote


def test_parse_money() -> None:
    """Test parsing currency numbers across formats."""
    assert parse_money("472.00") == Decimal("472.00")
    assert parse_money("5,664,000.00") == Decimal("5664000.00")
    assert parse_money("BDT 183,200.00") == Decimal("183200.00")
    assert parse_money("6.65") == Decimal("6.65")
    assert parse_money("not a number") is None
    assert parse_money(None) is None


def test_parse_percent() -> None:
    """Test parsing percentages."""
    assert parse_percent("15%") == Decimal("15.0")
    assert parse_percent("0.5%") == Decimal("0.5")
    assert parse_percent("1% of order value") == Decimal("1.0")
    assert parse_percent("0.75% of the order value per week") == Decimal("0.75")
    assert parse_percent("no percent here") is None


def test_parse_days_all_sample_phrases() -> None:
    """Test parse_days with phrases found in all 10 packs."""
    assert parse_days("Delivery within 24 days of receiving the purchase order.") == 24
    assert parse_days("within 21 days from the date of PO.") == 21
    assert parse_days("Delivery within 4 weeks of PO.") == 28
    assert parse_days("Delivery within 60 days of PO.") == 60
    assert parse_days("2 months") == 60
    assert parse_days("valid for 45 days from the date above") == 45
    assert parse_days("valid for 30 days") == 30
    assert parse_days("invalid days text") is None


def test_parse_payment_days() -> None:
    """Test payment days parsing and ambiguous range handling."""
    assert parse_payment_days("Full payment within 30 days of delivery.") == 30
    assert parse_payment_days("Balance payable within 45 days after delivery") == 45
    assert parse_payment_days("Balance within 60 days of delivery.") == 60

    # Ambiguous ranges must return None
    assert parse_payment_days("Payment within 30 to 90 days as agreed by both parties.") is None
    assert parse_payment_days("Payment 30-90 days") is None


def test_parse_advance() -> None:
    """Test advance payment terms parsing."""
    # 0 advance
    val, uncertain = parse_advance("No advance payment required. Full payment within 30 days.")
    assert val == Decimal("0.0")
    assert not uncertain

    # Stated percentage
    val, uncertain = parse_advance("10% advance payable with the purchase order.")
    assert val == Decimal("10.0")
    assert not uncertain

    # Duplicate percentages collapse
    msg = "40% advance payable with the purchase order. 40% advance with the purchase order"
    val, uncertain = parse_advance(msg)
    assert val == Decimal("40.0")
    assert not uncertain

    # Conflicting percentages trigger uncertain
    val, uncertain = parse_advance("10% advance payable initially, then 20% advance required.")
    assert val is None
    assert uncertain

    # Missing text triggers uncertain
    val, uncertain = parse_advance(None)
    assert val is None
    assert uncertain


def test_parse_tin_bin() -> None:
    """Test TIN and BIN parsing."""
    # Normal case
    tin, bin_no, malformed = parse_tin_bin("Supplier TIN: 101458013391 BIN: 000170141-0101")
    assert tin == "101458013391"
    assert bin_no == "000170141-0101"
    assert not malformed

    # Available on request
    tin, bin_no, malformed = parse_tin_bin("Supplier registration details available on request.")
    assert tin is None
    assert bin_no is None
    assert not malformed

    # Malformed TIN
    tin, bin_no, malformed = parse_tin_bin("TIN: 123 BIN: 000170141-0101")
    assert malformed


def test_grounding_substring_check() -> None:
    """Test whitespace-normalised grounding check."""
    doc = """
    Padma Textile Mills Ltd
    Quotation no. QT-2026-901
    1. Payment. 10% advance payable with the purchase order.
    """
    assert is_grounded_in_text("Padma Textile Mills Ltd", doc)
    assert is_grounded_in_text("10% advance payable with the purchase order.", doc)
    # Different whitespace collapses
    assert is_grounded_in_text("Quotation\nno.\nQT-2026-901", doc)
    # Hallucinated text
    assert not is_grounded_in_text("Random non-existent supplier", doc)


def test_verify_demotes_ungrounded_quote() -> None:
    """Grounding verifier must demote ungrounded quote to UNCERTAIN and set grounded=False."""
    doc = "Some official text without the quote."
    quote = ExtractedQuote(
        supplier_name=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="Padma Textile Mills Ltd",
            evidence_quote="Padma Textile Mills Ltd",
        ),
        quotation_no=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="QT-999",
            evidence_quote="QT-999",
        ),
        quote_date=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="2026-10-21",
            evidence_quote="2026-10-21",
        ),
        reference_pr=FieldEvidence[str](
            status=FieldStatus.FOUND, value="PR-1", evidence_quote="PR-1"
        ),
        line_item_count=1,
        item_code=FieldEvidence[str](status=FieldStatus.FOUND, value="A", evidence_quote="A"),
        description=FieldEvidence[str](
            status=FieldStatus.FOUND, value="Desc", evidence_quote="Desc"
        ),
        quantity=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("10"),
            evidence_quote="10",
        ),
        unit=FieldEvidence[str](status=FieldStatus.FOUND, value="metre", evidence_quote="metre"),
        unit_price=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("10"),
            evidence_quote="10",
        ),
        subtotal=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("100"),
            evidence_quote="100",
        ),
        vat_amount=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("15"),
            evidence_quote="15",
        ),
        vat_percent=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("15"),
            evidence_quote="15%",
        ),
        vat_shown_separately=FieldEvidence[bool](
            status=FieldStatus.FOUND,
            value=True,
            evidence_quote="VAT 15%",
        ),
        total=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("115"),
            evidence_quote="115",
        ),
        tin=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="123456789",
            evidence_quote="TIN: 123456789",
        ),
        bin=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="123456789",
            evidence_quote="BIN: 123456789",
        ),
        advance_percent=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("0"),
            evidence_quote="0%",
        ),
        payment_terms_text=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="30 days",
            evidence_quote="30 days",
        ),
        payment_days=FieldEvidence[int](
            status=FieldStatus.FOUND, value=30, evidence_quote="30 days"
        ),
        delivery_terms_text=FieldEvidence[str](
            status=FieldStatus.FOUND,
            value="20 days",
            evidence_quote="20 days",
        ),
        delivery_days=FieldEvidence[int](
            status=FieldStatus.FOUND, value=20, evidence_quote="20 days"
        ),
        late_penalty_percent_per_week=FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal("1"),
            evidence_quote="1%",
        ),
        late_penalty_clause_present=FieldEvidence[bool](
            status=FieldStatus.FOUND,
            value=True,
            evidence_quote="1%",
        ),
        late_penalty_specifies_order_value=FieldEvidence[bool](
            status=FieldStatus.FOUND,
            value=True,
            evidence_quote="1%",
        ),
        validity_days=FieldEvidence[int](
            status=FieldStatus.FOUND, value=30, evidence_quote="30 days"
        ),
    )

    verified = verify_and_ground_quote(quote, doc)
    assert verified.supplier_name.status == FieldStatus.UNCERTAIN
    assert verified.supplier_name.grounded is False
