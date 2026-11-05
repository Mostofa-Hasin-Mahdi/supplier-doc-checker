"""Reconciliation logic comparing LLM extractor and Fallback extractor results.

Decision-relevant fields:
- unit_price, quantity, subtotal, vat_amount, vat_percent, total,
  advance_percent, payment_days, delivery_days, late_penalty_percent_per_week,
  validity_days, tin, bin, item_code.

If both extractors succeeded and agree: use the confirmed value.
If both succeeded and disagree: mark that field UNCERTAIN and record both values in audit log.
If only one extractor succeeded: use it and log a single-extractor note.
"""

import logging
from decimal import Decimal
from typing import Any

from supplier_check.models import ExtractedQuote, FieldEvidence, FieldStatus

logger = logging.getLogger(__name__)

DECISION_FIELDS = [
    "unit_price",
    "quantity",
    "subtotal",
    "vat_amount",
    "vat_percent",
    "total",
    "advance_percent",
    "payment_days",
    "delivery_days",
    "late_penalty_percent_per_week",
    "validity_days",
    "tin",
    "bin",
    "item_code",
    "late_penalty_clause_present",
    "late_penalty_specifies_order_value",
    "vat_shown_separately",
]


def values_match(val_a: Any, val_b: Any) -> bool:
    """Compare two normalized decision-relevant values."""
    if val_a is None and val_b is None:
        return True
    if val_a is None or val_b is None:
        return False

    # Boolean comparison (derived boolean fields)
    if isinstance(val_a, bool) or isinstance(val_b, bool):
        return val_a is val_b

    # Decimal comparison (money, percentages)
    if isinstance(val_a, Decimal) or isinstance(val_b, Decimal):
        try:
            return Decimal(str(val_a)) == Decimal(str(val_b))
        except Exception:
            return False

    # Integer comparison (days)
    if isinstance(val_a, int) and isinstance(val_b, int):
        return val_a == val_b

    # String comparison (text IDs like item_code, tin, bin): casefold & stripped
    if isinstance(val_a, str) and isinstance(val_b, str):
        return val_a.strip().casefold() == val_b.strip().casefold()

    return val_a == val_b




def reconcile_quotes(
    llm_quote: ExtractedQuote | None,
    fallback_quote: ExtractedQuote | None,
) -> tuple[ExtractedQuote, list[str]]:
    """Reconcile fields between LLM extraction and Fallback extraction.

    Returns:
        (reconciled_quote, audit_log_entries)
    """
    reconciled, notes, _ = reconcile_quotes_with_count(llm_quote, fallback_quote)
    return reconciled, notes


def reconcile_quotes_with_count(
    llm_quote: ExtractedQuote | None,
    fallback_quote: ExtractedQuote | None,
) -> tuple[ExtractedQuote, list[str], int]:
    """Reconcile fields between LLM extraction and Fallback extraction, reporting disagreement count.

    Returns:
        (reconciled_quote, audit_log_entries, disagreement_count)
    """
    audit_log: list[str] = []

    # Case 1: Only fallback extractor succeeded
    if llm_quote is None and fallback_quote is not None:
        audit_log.append("Extraction completed using Fallback extractor only (LLM unavailable/failed).")
        return fallback_quote, audit_log, 0

    # Case 2: Only LLM extractor succeeded
    if fallback_quote is None and llm_quote is not None:
        audit_log.append("Extraction completed using LLM extractor only.")
        return llm_quote, audit_log, 0

    # Case 3: Neither succeeded
    if llm_quote is None and fallback_quote is None:
        raise ValueError("Cannot reconcile when both extractors are None")

    # Case 4: Both succeeded -> compare decision-relevant fields
    audit_log.append("Reconciling outputs from both LLM and Fallback extractors.")
    reconciled = llm_quote.model_copy(deep=True)
    disagreements = 0

    for field_name in DECISION_FIELDS:
        fe_llm: FieldEvidence[Any] = getattr(llm_quote, field_name)
        fe_fb: FieldEvidence[Any] = getattr(fallback_quote, field_name)

        llm_val = fe_llm.value
        fb_val = fe_fb.value

        # Check for status or value disagreement
        # Compare normalized values (Decimal for money/pct, int for days, casefold for str)
        is_equal = False
        if llm_val is None and fb_val is None:
            # Both None: check if statuses agree (e.g. both ABSENT or both UNCERTAIN)
            is_equal = fe_llm.status == fe_fb.status
        elif llm_val is not None and fb_val is not None:
            is_equal = values_match(llm_val, fb_val) and (fe_llm.status == fe_fb.status)

        if not is_equal:
            disagreements += 1
            note = (
                f"Disagreement on '{field_name}': "
                f"LLM={fe_llm.status.value}({llm_val}) vs Fallback={fe_fb.status.value}({fb_val}). "
                "Marked UNCERTAIN."
            )
            audit_log.append(note)
            logger.warning(note)

            reconciled_fe = FieldEvidence[Any](
                status=FieldStatus.UNCERTAIN,
                value=llm_val if fe_llm.grounded else fb_val,
                evidence_quote=fe_llm.evidence_quote or fe_fb.evidence_quote,
                absence_note=note,
                grounded=fe_llm.grounded and fe_fb.grounded,
            )
            setattr(reconciled, field_name, reconciled_fe)
        else:
            # They agree
            # Prefer the one with confirmed grounding
            if fe_fb.grounded and not fe_llm.grounded:
                setattr(reconciled, field_name, fe_fb)

    # Compare line_item_count
    if llm_quote.line_item_count != fallback_quote.line_item_count:
        disagreements += 1
        note = (
            f"Disagreement on 'line_item_count': "
            f"LLM={llm_quote.line_item_count} vs Fallback={fallback_quote.line_item_count}. "
            "Set to None (undetermined)."
        )
        audit_log.append(note)
        logger.warning(note)
        reconciled.line_item_count = None
    else:
        reconciled.line_item_count = fallback_quote.line_item_count

    return reconciled, audit_log, disagreements
