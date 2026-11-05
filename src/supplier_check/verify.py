"""Deterministic grounding and cross-check verification."""

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


def normalize_whitespace(text: str) -> str:
    """Collapse all consecutive whitespace and newlines to a single space."""
    return re.sub(r"\s+", " ", text).strip()


def is_grounded_in_text(quote: str | None, full_text: str) -> bool:
    """Check whether quote appears verbatim in full_text after whitespace normalization."""
    if not quote or not quote.strip():
        return False
    norm_quote = normalize_whitespace(quote)
    norm_text = normalize_whitespace(full_text)
    return norm_quote in norm_text


def cross_check_parsed_value_with_quote(
    field_name: str,
    assigned_value: object,
    evidence_quote: str,
) -> bool:
    """Re-parse the evidence quote with deterministic parsers and compare with assigned value.

    Returns True if consistent, False if inconsistent.
    """
    if assigned_value is None:
        return True

    # Money fields
    if field_name in {"unit_price", "quantity", "subtotal", "vat_amount", "total"}:
        parsed = parse_money(evidence_quote)
        if parsed is not None and isinstance(assigned_value, Decimal):
            return parsed == assigned_value
        return True

    # Percentage fields
    if field_name == "vat_percent":
        parsed = parse_percent(evidence_quote)
        if parsed is not None and isinstance(assigned_value, Decimal):
            return parsed == assigned_value
        return True

    if field_name == "advance_percent":
        adv_val, adv_uncertain = parse_advance(evidence_quote)
        if not adv_uncertain and adv_val is not None and isinstance(assigned_value, Decimal):
            return adv_val == assigned_value
        return True

    if field_name == "late_penalty_percent_per_week":
        parsed = parse_percent(evidence_quote)
        if parsed is not None and isinstance(assigned_value, Decimal):
            return parsed == assigned_value
        return True

    # Day / Duration fields
    if field_name in {"delivery_days", "validity_days"}:
        parsed_days = parse_days(evidence_quote)
        if parsed_days is not None and isinstance(assigned_value, int):
            return parsed_days == assigned_value
        return True

    if field_name == "payment_days":
        parsed_pdays = parse_payment_days(evidence_quote)
        if parsed_pdays is not None and isinstance(assigned_value, int):
            return parsed_pdays == assigned_value
        return True

    # TIN / BIN
    if field_name in {"tin", "bin"}:
        tin_val, bin_val, _ = parse_tin_bin(evidence_quote)
        if field_name == "tin" and tin_val is not None:
            return tin_val == assigned_value
        if field_name == "bin" and bin_val is not None:
            return bin_val == assigned_value
        return True

    return True


def verify_and_ground_quote(raw_quote: ExtractedQuote, full_document_text: str) -> ExtractedQuote:
    """Verify that every extracted quote is verbatim grounded and cross-check derived fields.

    Rules:
    - Non-empty evidence_quote must appear in source text; otherwise status=UNCERTAIN,
      grounded=False.
    - If status was FOUND but evidence is not grounded in source text -> status=UNCERTAIN.
    - Cross-check: parse the value from the evidence quote with the deterministic parsers;
      if it disagrees with the LLM's raw value, set the field to UNCERTAIN.
    - Derived fields (clause_present, specifies_order_value, vat_shown_separately) are
      cross-checked deterministically.
    """
    fields_dict = raw_quote.model_dump()
    terms_text = full_document_text.lower()

    # 1. Verify grounding and cross-check parsed values for all FieldEvidence fields
    for field_name in list(fields_dict.keys()):
        field_val = getattr(raw_quote, field_name)
        if not isinstance(field_val, FieldEvidence):
            continue

        quote = field_val.evidence_quote
        status = field_val.status
        grounded = False

        if quote and quote.strip():
            grounded = is_grounded_in_text(quote, full_document_text)

        if status == FieldStatus.DERIVED:
            # Derived boolean fields: verify grounding if quote is provided
            if quote and quote.strip():
                grounded = is_grounded_in_text(quote, full_document_text)
            else:
                grounded = True  # absence note provides the derivation basis
            field_val = FieldEvidence(
                status=FieldStatus.DERIVED,
                value=field_val.value,
                evidence_quote=quote
                if (quote and is_grounded_in_text(quote, full_document_text))
                else None,
                absence_note=field_val.absence_note,
                grounded=grounded,
            )
        elif status == FieldStatus.FOUND:
            if not grounded:
                # Hallucinated or non-matching quote: strictly demote to UNCERTAIN
                field_val = FieldEvidence(
                    status=FieldStatus.UNCERTAIN,
                    value=field_val.value,
                    evidence_quote=quote,
                    absence_note="Quote not found verbatim in document text",
                    grounded=False,
                )
            else:
                # Verify cross-check between assigned value and quote
                is_consistent = cross_check_parsed_value_with_quote(
                    field_name=field_name,
                    assigned_value=field_val.value,
                    evidence_quote=quote,
                )
                if not is_consistent:
                    field_val = FieldEvidence(
                        status=FieldStatus.UNCERTAIN,
                        value=field_val.value,
                        evidence_quote=quote,
                        absence_note="Parsed value from quote disagrees with extracted value",
                        grounded=True,
                    )
                else:
                    field_val = FieldEvidence(
                        status=FieldStatus.FOUND,
                        value=field_val.value,
                        evidence_quote=quote,
                        absence_note=None,
                        grounded=True,
                    )
        elif status == FieldStatus.ABSENT:
            field_val = FieldEvidence(
                status=FieldStatus.ABSENT,
                value=None,
                evidence_quote=quote if grounded else None,
                absence_note=field_val.absence_note,
                grounded=grounded if quote else False,
            )
        else:  # UNCERTAIN
            field_val = FieldEvidence(
                status=FieldStatus.UNCERTAIN,
                value=field_val.value,
                evidence_quote=quote,
                absence_note=field_val.absence_note,
                grounded=grounded,
            )

        setattr(raw_quote, field_name, field_val)

    # 2. Cross-check late penalty clause keyword scan
    has_delay_keywords = "penalt" in terms_text or "delay" in terms_text
    penalty_fe = raw_quote.late_penalty_clause_present
    penalty_quote = raw_quote.late_penalty_percent_per_week.evidence_quote

    if (
        has_delay_keywords
        and penalty_fe.status == FieldStatus.DERIVED
        and penalty_fe.value is False
    ):
        raw_quote.late_penalty_clause_present = FieldEvidence[bool](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=penalty_fe.evidence_quote,
            absence_note="Delay keywords found in text but penalty clause marked absent",
            grounded=False,
        )
    elif penalty_quote and not is_grounded_in_text(penalty_quote, full_document_text):
        raw_quote.late_penalty_clause_present = FieldEvidence[bool](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=penalty_quote,
            absence_note="Penalty quote not grounded in document text",
            grounded=False,
        )

    # 3. Cross-check late_penalty_specifies_order_value
    if raw_quote.late_penalty_clause_present.value is True and penalty_quote:
        specifies = "order value" in penalty_quote.lower()
        is_pen_grounded = is_grounded_in_text(penalty_quote, full_document_text)
        raw_quote.late_penalty_specifies_order_value = FieldEvidence[bool](
            status=FieldStatus.DERIVED if is_pen_grounded else FieldStatus.UNCERTAIN,
            value=specifies if is_pen_grounded else None,
            evidence_quote=penalty_quote,
            grounded=is_pen_grounded,
        )

    # 4. Cross-check VAT presentation
    has_tax_included = "vat included" in terms_text or "all taxes included" in terms_text
    has_separate_vat = (
        "vat 15%" in terms_text
        and raw_quote.vat_amount.status == FieldStatus.FOUND
        and not has_tax_included
    )
    vat_quote = (
        raw_quote.vat_percent.evidence_quote
        or raw_quote.total.evidence_quote
        or ("Total" if "total" in terms_text else None)
    )
    is_vat_grounded = is_grounded_in_text(vat_quote, full_document_text) if vat_quote else False

    if vat_quote and is_vat_grounded:
        raw_quote.vat_shown_separately = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=has_separate_vat,
            evidence_quote=vat_quote,
            grounded=True,
        )
    else:
        raw_quote.vat_shown_separately = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=False,
            evidence_quote=None,
            absence_note="VAT presentation evaluated from document tax terms",
            grounded=True,
        )

    return raw_quote
