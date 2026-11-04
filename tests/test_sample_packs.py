"""Integration tests running the fallback extractor on all 10 sample PDF packs."""

from decimal import Decimal
from pathlib import Path

import pypdf

from supplier_check.extract_fallback import extract_fallback_from_text
from supplier_check.models import FieldStatus
from supplier_check.verify import verify_and_ground_quote

DATA_DIR = Path("data")


def read_pdf_text(pack_num: int) -> str:
    """Extract plain text from sample PDF pack."""
    pdf_path = DATA_DIR / f"supplier-pack-{pack_num:02d}.pdf"
    assert pdf_path.exists(), f"File {pdf_path} does not exist"
    reader = pypdf.PdfReader(pdf_path)
    return "\n".join(page.extract_text() for page in reader.pages)


def test_fallback_extractor_pack_01() -> None:
    """Pack 01: Padma Textile Mills Ltd."""
    text = read_pdf_text(1)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Padma Textile Mills Ltd"
    assert verified.unit_price.value == Decimal("472.00")
    assert verified.quantity.value == Decimal("12000")
    assert verified.tin.value == "101458013391"
    assert verified.bin.value == "000170141-0101"
    assert verified.advance_percent.value == Decimal("10.0")
    assert verified.delivery_days.value == 24
    assert verified.late_penalty_clause_present.value is True
    # Penalty base STATED (order value)
    assert verified.late_penalty_specifies_order_value.value is True


def test_fallback_extractor_pack_02() -> None:
    """Pack 02: Jamuna Trims and Accessories."""
    text = read_pdf_text(2)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Jamuna Trims and Accessories"
    assert verified.unit_price.value == Decimal("36.00")
    assert verified.quantity.value == Decimal("20000")
    assert verified.advance_percent.value == Decimal("0.0")
    assert verified.late_penalty_clause_present.value is True
    # Penalty base STATED (order value)
    assert verified.late_penalty_specifies_order_value.value is True


def test_fallback_extractor_pack_03() -> None:
    """Pack 03: Karnaphuli Yarn Traders - Price 229."""
    text = read_pdf_text(3)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Karnaphuli Yarn Traders"
    assert verified.unit_price.value == Decimal("229.00")
    assert verified.quantity.value == Decimal("800")
    # Penalty base STATED (order value)
    assert verified.late_penalty_specifies_order_value.value is True


def test_fallback_extractor_pack_04() -> None:
    """Pack 04: Surma Packaging - Price 6.65."""
    text = read_pdf_text(4)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Surma Packaging Industries"
    assert verified.unit_price.value == Decimal("6.65")
    assert verified.quantity.value == Decimal("50000")


def test_fallback_extractor_pack_05() -> None:
    """Pack 05: Meghna Carton Works - Advance 40%."""
    text = read_pdf_text(5)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Meghna Carton Works"
    assert verified.advance_percent.value == Decimal("40.0")


def test_fallback_extractor_pack_06() -> None:
    """Pack 06: Teesta Fabrics - No penalty clause."""
    text = read_pdf_text(6)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Teesta Fabrics Ltd"
    # Clause is absent (not present)
    assert verified.late_penalty_clause_present.value is False
    assert verified.late_penalty_percent_per_week.status == FieldStatus.ABSENT


def test_fallback_extractor_pack_07() -> None:
    """Pack 07: Rupsha Zipper Factory - Quantity 16,500."""
    text = read_pdf_text(7)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Rupsha Zipper Factory"
    assert verified.quantity.value == Decimal("16500")


def test_fallback_extractor_pack_08() -> None:
    """Pack 08: Bhairab Thread - TIN/BIN absent, penalty base unstated."""
    text = read_pdf_text(8)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Bhairab Thread and Co"
    # Registration details available on request => TIN & BIN ABSENT
    assert verified.tin.status == FieldStatus.ABSENT
    assert verified.bin.status == FieldStatus.ABSENT
    assert verified.late_penalty_clause_present.value is True
    # Penalty base UNSTATED ("0.5% per week of delay")
    assert verified.late_penalty_specifies_order_value.value is False


def test_fallback_extractor_pack_09() -> None:
    """Pack 09: Dhaleshwari Poly Pack - Subtotal 322,000 & payment unclear."""
    text = read_pdf_text(9)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Dhaleshwari Poly Pack"
    assert verified.subtotal.value == Decimal("322000.00")
    # Payment within 30 to 90 days => payment_days status UNCERTAIN
    assert verified.payment_days.status == FieldStatus.UNCERTAIN
    assert verified.payment_days.value is None
    # Delivery within 4 weeks => 28 days
    assert verified.delivery_days.value == 28


def test_fallback_extractor_pack_10() -> None:
    """Pack 10: Kushiyara Box - Delivery 60 days, VAT not shown separately, no subtotal."""
    text = read_pdf_text(10)
    quote = extract_fallback_from_text(text)
    verified = verify_and_ground_quote(quote, text)

    assert verified.supplier_name.value == "Kushiyara Box Industries"
    assert verified.delivery_days.value == 60
    assert verified.subtotal.status == FieldStatus.ABSENT
    assert verified.vat_shown_separately.value is False
