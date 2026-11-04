"""Pure functions for matching quotation against purchase-request items and comparing price/quantity."""

from decimal import Decimal

from supplier_check.config import RulesConfig
from supplier_check.models import (
    ExtractedQuote,
    FieldStatus,
    PurchaseRequestItem,
    RuleResult,
    Severity,
)


def match_item_with_pr(
    quote: ExtractedQuote,
    pr_items: list[PurchaseRequestItem],
) -> tuple[PurchaseRequestItem | None, RuleResult]:
    """Match quote's item code, description, unit, and PR reference against PR items.

    Fails with RULE_REV_12_ITEM_MATCH (Severity.REVIEW) if:
    - line_item_count is None or > 1
    - No confident match is found
    - PR reference number does not match
    - Description or unit mismatch
    """
    quote_pr = quote.reference_pr.value if quote.reference_pr.status in {FieldStatus.FOUND, FieldStatus.DERIVED} else None
    quote_code = quote.item_code.value if quote.item_code.status in {FieldStatus.FOUND, FieldStatus.DERIVED} else None
    quote_desc = quote.description.value if quote.description.status in {FieldStatus.FOUND, FieldStatus.DERIVED} else None
    quote_unit = quote.unit.value if quote.unit.status in {FieldStatus.FOUND, FieldStatus.DERIVED} else None
    ev_quote = quote.item_code.evidence_quote or quote.reference_pr.evidence_quote or "N/A"

    # Line item count check
    if quote.line_item_count is None or quote.line_item_count > 1:
        lic_str = "undetermined" if quote.line_item_count is None else str(quote.line_item_count)
        return None, RuleResult(
            rule_id="RULE_REV_12_ITEM_MATCH",
            severity=Severity.REVIEW,
            message=f"Line item count is {lic_str}; human review required for multi-item or unverified line structure",
            evidence_quote=ev_quote,
        )

    if not quote_pr or not quote_code:
        return None, RuleResult(
            rule_id="RULE_REV_12_ITEM_MATCH",
            severity=Severity.REVIEW,
            message="Could not verify item code or reference PR number from quotation",
            evidence_quote=ev_quote,
        )

    # Search in PR items by PR number and item code (case-insensitive)
    matched_by_code: list[PurchaseRequestItem] = []
    for pr in pr_items:
        if pr.pr_number.strip().casefold() == quote_pr.strip().casefold() and pr.item_code.strip().casefold() == quote_code.strip().casefold():
            matched_by_code.append(pr)

    if not matched_by_code:
        # Check if PR number even matches any PR item
        pr_matches = [pr for pr in pr_items if pr.pr_number.strip().casefold() == quote_pr.strip().casefold()]
        if not pr_matches:
            return None, RuleResult(
                rule_id="RULE_REV_12_ITEM_MATCH",
                severity=Severity.REVIEW,
                message=f"Quotation reference PR '{quote_pr}' does not match any purchase request item",
                evidence_quote=quote.reference_pr.evidence_quote or ev_quote,
            )
        return None, RuleResult(
            rule_id="RULE_REV_12_ITEM_MATCH",
            severity=Severity.REVIEW,
            message=f"Item code '{quote_code}' not found under PR '{quote_pr}'",
            evidence_quote=quote.item_code.evidence_quote or ev_quote,
        )

    pr_candidate = matched_by_code[0]

    # Verify unit matching (case-insensitive)
    if quote_unit and pr_candidate.unit.strip().casefold() != quote_unit.strip().casefold():
        return None, RuleResult(
            rule_id="RULE_REV_12_ITEM_MATCH",
            severity=Severity.REVIEW,
            message=f"Item unit mismatch: quoted '{quote_unit}' vs requested '{pr_candidate.unit}'",
            evidence_quote=quote.unit.evidence_quote or ev_quote,
        )

    # Verify description core matching (first 10 chars or substring)
    if quote_desc:
        pr_desc_norm = " ".join(pr_candidate.description.split()).casefold()
        q_desc_norm = " ".join(quote_desc.split()).casefold()
        # Mismatch if neither is substring of the other and first words don't match
        pr_first_word = pr_desc_norm.split()[0] if pr_desc_norm.split() else ""
        if q_desc_norm not in pr_desc_norm and pr_desc_norm not in q_desc_norm and pr_first_word not in q_desc_norm:
            return None, RuleResult(
                rule_id="RULE_REV_12_ITEM_MATCH",
                severity=Severity.REVIEW,
                message=f"Description mismatch: quoted '{quote_desc}' does not match PR '{pr_candidate.description}'",
                evidence_quote=quote.description.evidence_quote or ev_quote,
            )

    return pr_candidate, RuleResult(
        rule_id="RULE_REV_12_ITEM_MATCH",
        severity=Severity.PASS,
        message=f"Matched item {pr_candidate.item_code} under {pr_candidate.pr_number}",
        evidence_quote=ev_quote,
    )


def compare_price(
    quote: ExtractedQuote,
    pr_item: PurchaseRequestItem,
    config: RulesConfig,
) -> RuleResult:
    """Compare unit price against PR maximum unit price using Decimal arithmetic.

    Threshold: max * (1 + price_tolerance_pct / 100)
    - price > threshold => REJECT (RULE_REJ_01_PRICE_MAX)
    - max < price <= threshold => REVIEW (RULE_REV_01_PRICE_TOLERANCE), exactly 3% over is REVIEW
    - price <= max => PASS (RULE_REJ_01_PRICE_MAX)
    """
    price_fe = quote.unit_price
    if price_fe.status not in {FieldStatus.FOUND, FieldStatus.DERIVED} or price_fe.value is None:
        return RuleResult(
            rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
            severity=Severity.REVIEW,
            message="could not verify unit_price",
            evidence_quote=price_fe.evidence_quote or "N/A",
        )

    price: Decimal = price_fe.value
    max_price: Decimal = pr_item.max_unit_price
    ev_quote = price_fe.evidence_quote or str(price)

    threshold = max_price * (Decimal("1") + (config.price_tolerance_pct / Decimal("100")))

    if price > threshold:
        diff_pct = ((price - max_price) / max_price) * Decimal("100")
        return RuleResult(
            rule_id="RULE_REJ_01_PRICE_MAX",
            severity=Severity.REJECT,
            message=f"{price} is {diff_pct:.2f}% above max {max_price} (limit {config.price_tolerance_pct}%)",
            evidence_quote=ev_quote,
        )

    if price > max_price:
        diff_pct = ((price - max_price) / max_price) * Decimal("100")
        return RuleResult(
            rule_id="RULE_REV_01_PRICE_TOLERANCE",
            severity=Severity.REVIEW,
            message=f"{price} is {diff_pct:.2f}% above max {max_price} (within {config.price_tolerance_pct}% tolerance)",
            evidence_quote=ev_quote,
        )

    return RuleResult(
        rule_id="RULE_REJ_01_PRICE_MAX",
        severity=Severity.PASS,
        message=f"{price} is within maximum unit price {max_price}",
        evidence_quote=ev_quote,
    )


def compare_quantity(
    quote: ExtractedQuote,
    pr_item: PurchaseRequestItem,
    config: RulesConfig,
) -> RuleResult:
    """Compare quoted quantity against requested quantity using Decimal arithmetic.

    - abs(qty - requested) / requested > 5% => REVIEW (RULE_REV_02_QTY_TOLERANCE)
    - Exactly 5% passes.
    """
    qty_fe = quote.quantity
    if qty_fe.status not in {FieldStatus.FOUND, FieldStatus.DERIVED} or qty_fe.value is None:
        return RuleResult(
            rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
            severity=Severity.REVIEW,
            message="could not verify quantity",
            evidence_quote=qty_fe.evidence_quote or "N/A",
        )

    qty: Decimal = qty_fe.value
    req_qty: Decimal = pr_item.quantity_requested
    ev_quote = qty_fe.evidence_quote or str(qty)

    diff_ratio = abs(qty - req_qty) / req_qty
    tolerance_ratio = config.quantity_tolerance_pct / Decimal("100")

    if diff_ratio > tolerance_ratio:
        diff_pct = diff_ratio * Decimal("100")
        direction = "above" if qty > req_qty else "below"
        return RuleResult(
            rule_id="RULE_REV_02_QTY_TOLERANCE",
            severity=Severity.REVIEW,
            message=f"{qty} is {diff_pct:.2f}% {direction} requested {req_qty} (tolerance {config.quantity_tolerance_pct}%)",
            evidence_quote=ev_quote,
        )

    return RuleResult(
        rule_id="RULE_REV_02_QTY_TOLERANCE",
        severity=Severity.PASS,
        message=f"Quantity {qty} is within {config.quantity_tolerance_pct}% tolerance of requested {req_qty}",
        evidence_quote=ev_quote,
    )


def run_pr_comparisons(
    quote: ExtractedQuote,
    pr_items: list[PurchaseRequestItem],
    config: RulesConfig,
) -> tuple[PurchaseRequestItem | None, list[RuleResult]]:
    """Execute all PR matching and comparison checks."""
    matched_pr, match_result = match_item_with_pr(quote, pr_items)
    results: list[RuleResult] = [match_result]

    if matched_pr is None:
        return None, results

    results.append(compare_price(quote, matched_pr, config))
    results.append(compare_quantity(quote, matched_pr, config))
    return matched_pr, results

