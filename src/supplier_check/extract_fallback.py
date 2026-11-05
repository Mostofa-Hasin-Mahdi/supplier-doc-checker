"""Deterministic fallback extractor using regex and document table pattern recognition.

Used when the LLM errors, returns invalid JSON after retry, or is unavailable (no API key).
"""

import logging
import re
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

logger = logging.getLogger(__name__)


def extract_fallback_from_text(document_text: str) -> ExtractedQuote:
    """Extract structured quotation fields from text deterministically using regex/layout rules."""
    logger.info("Extracting quotation using deterministic fallback extractor")

    lines = [line.strip() for line in document_text.splitlines() if line.strip()]

    # 1. Supplier Name: First non-empty line of the document
    supplier_name = lines[0] if lines else None
    fe_supplier = (
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=supplier_name,
            evidence_quote=supplier_name,
        )
        if supplier_name
        else FieldEvidence[str](status=FieldStatus.UNCERTAIN)
    )

    # 2. Quotation Number
    m_qt = re.search(r"Quotation\s+no\.?\s*\n?\s*([A-Za-z0-9\-]+)", document_text, re.IGNORECASE)
    if m_qt:
        fe_qt = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=m_qt.group(1).strip(),
            evidence_quote=m_qt.group(0).strip(),
        )
    else:
        fe_qt = FieldEvidence[str](status=FieldStatus.UNCERTAIN)

    # 3. Date
    m_date = re.search(r"\bDate\s*\n?\s*(\d{4}-\d{2}-\d{2})", document_text, re.IGNORECASE)
    if m_date:
        fe_date = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=m_date.group(1).strip(),
            evidence_quote=m_date.group(0).strip(),
        )
    else:
        fe_date = FieldEvidence[str](status=FieldStatus.UNCERTAIN)

    # 4. Reference PR
    m_pr = re.search(r"\bReference\s*\n?\s*([A-Za-z0-9\-]+)", document_text, re.IGNORECASE)
    if m_pr:
        fe_pr = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=m_pr.group(1).strip(),
            evidence_quote=m_pr.group(0).strip(),
        )
    else:
        fe_pr = FieldEvidence[str](status=FieldStatus.UNCERTAIN)

    # 5. Table rows & Line Item details
    # Look for item row: Item Code (A-Z) followed by Description, Qty, Unit, Price, Amount
    m_item = re.search(
        r"\b([A-Z])\s*\n\s*(.+?)\s*\n\s*([\d,]+)\s*\n\s*([a-zA-Z]+)\s*\n\s*([\d,]+\.\d{2})"
        r"\s*\n\s*([\d,]+\.\d{2})",
        document_text,
    )
    if m_item:
        item_code = m_item.group(1).strip()
        description = m_item.group(2).strip()
        raw_qty = m_item.group(3).strip()
        unit = m_item.group(4).strip()
        raw_price = m_item.group(5).strip()

        fe_item_code = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=item_code,
            evidence_quote=item_code,
        )
        fe_desc = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=description,
            evidence_quote=description,
        )
        fe_qty = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=parse_money(raw_qty),
            evidence_quote=raw_qty,
        )
        fe_unit = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=unit,
            evidence_quote=unit,
        )
        fe_price = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=parse_money(raw_price),
            evidence_quote=raw_price,
        )
        line_item_count: int | None = 1
    else:
        fe_item_code = FieldEvidence[str](status=FieldStatus.UNCERTAIN)
        fe_desc = FieldEvidence[str](status=FieldStatus.UNCERTAIN)
        fe_qty = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN)
        fe_unit = FieldEvidence[str](status=FieldStatus.UNCERTAIN)
        fe_price = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN)
        line_item_count = None

    # 6. Subtotal
    m_sub = re.search(r"Subtotal\s*\n?\s*([\d,]+\.\d{2})", document_text, re.IGNORECASE)
    if m_sub:
        fe_subtotal = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=parse_money(m_sub.group(1)),
            evidence_quote=m_sub.group(0).strip(),
        )
    else:
        # Pack 10 has no Subtotal row
        fe_subtotal = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            absence_note="No subtotal row found in quotation table",
        )

    # 7. VAT
    m_vat = re.search(r"VAT\s*(\d+)%?\s*\n?\s*([\d,]+\.\d{2})", document_text, re.IGNORECASE)
    has_tax_included = (
        "vat included" in document_text.lower() or "all taxes included" in document_text.lower()
    )

    if m_vat and not has_tax_included:
        fe_vat_percent = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=Decimal(m_vat.group(1)),
            evidence_quote=f"VAT {m_vat.group(1)}%",
        )
        fe_vat_amount = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=parse_money(m_vat.group(2)),
            evidence_quote=m_vat.group(2).strip(),
        )
        fe_vat_shown = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=True,
            evidence_quote=m_vat.group(0).strip(),
        )
    else:
        fe_vat_percent = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            absence_note="VAT not shown separately at 15%",
        )
        fe_vat_amount = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            absence_note="VAT not shown separately at 15%",
        )
        m_vat_inc = re.search(
            r"Unit price \(.*VAT included.*\)|Total \(all taxes included\)",
            document_text,
            re.IGNORECASE,
        )
        fe_vat_shown = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=False,
            evidence_quote=m_vat_inc.group(0).strip() if m_vat_inc else None,
            absence_note="VAT included / all taxes included without separate 15% breakdown",
        )

    # 8. Total
    m_tot = re.search(
        r"\bTotal(?:\s*\([^\)]*\))?\s*\n?\s*([\d,]+\.\d{2})",
        document_text,
    )
    if m_tot:
        fe_total = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=parse_money(m_tot.group(1)),
            evidence_quote=m_tot.group(0).strip(),
        )
    else:
        fe_total = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN)

    # 9. TIN & BIN
    tin_val, bin_val, is_malformed = parse_tin_bin(document_text)
    m_reg = re.search(
        r"(?:Supplier\s+)?(?:TIN:[^\n]+|Supplier registration details[^\n]+)",
        document_text,
        re.IGNORECASE,
    )
    reg_quote = m_reg.group(0).strip() if m_reg else None

    if tin_val:
        fe_tin = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=tin_val,
            evidence_quote=reg_quote,
        )
    elif is_malformed:
        fe_tin = FieldEvidence[str](status=FieldStatus.UNCERTAIN, evidence_quote=reg_quote)
    else:
        fe_tin = FieldEvidence[str](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=reg_quote,
            absence_note="TIN registration missing or available on request",
        )

    if bin_val:
        fe_bin = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=bin_val,
            evidence_quote=reg_quote,
        )
    elif is_malformed:
        fe_bin = FieldEvidence[str](status=FieldStatus.UNCERTAIN, evidence_quote=reg_quote)
    else:
        fe_bin = FieldEvidence[str](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=reg_quote,
            absence_note="BIN registration missing or available on request",
        )

    # 10. Terms and Conditions Section: from 'TERMS AND CONDITIONS' up to signatory
    m_terms = re.search(
        r"TERMS AND CONDITIONS\s*\n(.+?)(?=\n\s*For\s+[A-Z]|\Z)",
        document_text,
        re.DOTALL | re.IGNORECASE,
    )
    terms_block = m_terms.group(1).strip() if m_terms else document_text

    # 11. Payment Terms & Advance
    m_pay = re.search(
        r"(?:^|\n)\s*(1\.\s*Payment\.\s*[^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
        terms_block,
        re.IGNORECASE,
    )
    if not m_pay:
        m_pay = re.search(
            r"\bPayment\.\s*([^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
            terms_block,
            re.IGNORECASE,
        )
    pay_quote = m_pay.group(1).strip() if m_pay and m_pay.lastindex else (m_pay.group(0).strip() if m_pay else terms_block)
    pay_text = re.sub(r"^(?:1\.\s*)?Payment\.\s*", "", pay_quote, flags=re.IGNORECASE).strip() if m_pay else None

    adv_val, adv_uncertain = parse_advance(pay_text)
    if not adv_uncertain and adv_val is not None:
        fe_adv = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=adv_val,
            evidence_quote=pay_quote,
        )
    else:
        fe_adv = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN, evidence_quote=pay_quote)

    fe_pay_terms = FieldEvidence[str](
        status=FieldStatus.FOUND if pay_text else FieldStatus.UNCERTAIN,
        value=pay_text or "Payment terms unstated",
        evidence_quote=pay_quote,
    )
    pay_days_val = parse_payment_days(pay_text)
    if pay_days_val is not None:
        fe_pay_days = FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=pay_days_val,
            evidence_quote=pay_quote,
        )
    else:
        fe_pay_days = FieldEvidence[int](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=pay_quote,
            absence_note="Payment days unclear or range specified",
        )

    # 12. Delivery Terms
    m_del = re.search(
        r"(?:^|\n)\s*(2\.\s*Delivery\.\s*[^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
        terms_block,
        re.IGNORECASE,
    )
    if not m_del:
        m_del = re.search(
            r"\bDelivery\.\s*([^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
            terms_block,
            re.IGNORECASE,
        )
    del_quote = m_del.group(1).strip() if m_del and m_del.lastindex else (m_del.group(0).strip() if m_del else terms_block)
    del_text = re.sub(r"^(?:2\.\s*)?Delivery\.\s*", "", del_quote, flags=re.IGNORECASE).strip() if m_del else None
    del_days_val = parse_days(del_text)

    fe_del_terms = FieldEvidence[str](
        status=FieldStatus.FOUND if del_text else FieldStatus.UNCERTAIN,
        value=del_text or "Delivery terms unstated",
        evidence_quote=del_quote,
    )
    if del_days_val is not None:
        fe_del_days = FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=del_days_val,
            evidence_quote=del_quote,
        )
    else:
        fe_del_days = FieldEvidence[int](status=FieldStatus.UNCERTAIN, evidence_quote=del_quote)

    # 13. Late Delivery Penalty Clause
    m_pen = re.search(
        r"(?:^|\n)\s*([0-9]+\.\s*Delay\.\s*[^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
        terms_block,
        re.IGNORECASE,
    )
    if not m_pen:
        m_pen = re.search(
            r"\bDelay\.\s*([^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
            terms_block,
            re.IGNORECASE,
        )
    if m_pen:
        pen_quote = m_pen.group(1).strip() if m_pen.lastindex else m_pen.group(0).strip()
        pen_rate = parse_percent(pen_quote)
        specifies_order_val = "order value" in pen_quote.lower()

        fe_pen_present = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=True,
            evidence_quote=pen_quote,
        )
        fe_pen_rate = FieldEvidence[Decimal](
            status=FieldStatus.FOUND if pen_rate is not None else FieldStatus.UNCERTAIN,
            value=pen_rate,
            evidence_quote=pen_quote,
        )
        fe_pen_specifies = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=specifies_order_val,
            evidence_quote=pen_quote,
        )
    else:
        # Absence of penalty clause (e.g. Pack 06)
        fe_pen_present = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=False,
            evidence_quote=None,
            absence_note="No late delivery penalty clause found in terms and conditions",
        )
        fe_pen_rate = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=None,
            absence_note="No late delivery penalty clause present",
        )
        fe_pen_specifies = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=False,
            evidence_quote=None,
            absence_note="No late delivery penalty clause present",
        )

    # 14. Validity
    m_val = re.search(
        r"(?:^|\n)\s*([0-9]+\.\s*Validity\.\s*[^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
        terms_block,
        re.IGNORECASE,
    )
    if not m_val:
        m_val = re.search(
            r"\bValidity\.\s*([^\n]+(?:\n(?![0-9]\.)[^\n]+)*)",
            terms_block,
            re.IGNORECASE,
        )
    val_quote = m_val.group(1).strip() if m_val and m_val.lastindex else (m_val.group(0).strip() if m_val else terms_block)
    val_text = re.sub(r"^(?:[0-9]+\.\s*)?Validity\.\s*", "", val_quote, flags=re.IGNORECASE).strip() if m_val else None
    val_days = parse_days(val_text)

    if val_days is not None:
        fe_val_days = FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=val_days,
            evidence_quote=val_quote,
        )
    else:
        fe_val_days = FieldEvidence[int](status=FieldStatus.UNCERTAIN, evidence_quote=val_quote)

    return ExtractedQuote(
        supplier_name=fe_supplier,
        quotation_no=fe_qt,
        quote_date=fe_date,
        reference_pr=fe_pr,
        line_item_count=line_item_count,
        item_code=fe_item_code,
        description=fe_desc,
        quantity=fe_qty,
        unit=fe_unit,
        unit_price=fe_price,
        subtotal=fe_subtotal,
        vat_amount=fe_vat_amount,
        vat_percent=fe_vat_percent,
        vat_shown_separately=fe_vat_shown,
        total=fe_total,
        tin=fe_tin,
        bin=fe_bin,
        advance_percent=fe_adv,
        payment_terms_text=fe_pay_terms,
        payment_days=fe_pay_days,
        delivery_terms_text=fe_del_terms,
        delivery_days=fe_del_days,
        late_penalty_percent_per_week=fe_pen_rate,
        late_penalty_clause_present=fe_pen_present,
        late_penalty_specifies_order_value=fe_pen_specifies,
        validity_days=fe_val_days,
    )
