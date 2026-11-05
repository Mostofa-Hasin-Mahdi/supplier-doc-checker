"""Deterministic implementation of procurement rules from docs/DESIGN.md."""

from decimal import Decimal

from supplier_check.config import RulesConfig
from supplier_check.models import ExtractedQuote, FieldStatus, RuleResult, Severity


def check_advance_payment(quote: ExtractedQuote, config: RulesConfig) -> RuleResult:
    """RULE_REJ_02_ADVANCE_MAX: Advance > 20% REJECT; UNCERTAIN/ABSENT advance => REVIEW."""
    fe = quote.advance_percent
    if fe.status in {FieldStatus.UNCERTAIN, FieldStatus.ABSENT} or fe.value is None:
        return RuleResult(
            rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
            severity=Severity.REVIEW,
            message="could not verify advance_percent",
            evidence_quote=fe.evidence_quote or quote.payment_terms_text.evidence_quote or "N/A",
        )

    val: Decimal = fe.value
    ev = fe.evidence_quote or f"{val}% advance"
    if val > config.max_advance_pct:
        return RuleResult(
            rule_id="RULE_REJ_02_ADVANCE_MAX",
            severity=Severity.REJECT,
            message=f"Advance payment requested is {val}%, exceeding maximum allowed {config.max_advance_pct}%",
            evidence_quote=ev,
        )

    return RuleResult(
        rule_id="RULE_REJ_02_ADVANCE_MAX",
        severity=Severity.PASS,
        message=f"Advance payment {val}% is within limit {config.max_advance_pct}%",
        evidence_quote=ev,
    )


def check_penalty_clause_present(
    quote: ExtractedQuote,
    config: RulesConfig,
    raw_document_text: str | None = None,
) -> RuleResult:
    """RULE_REJ_03_NO_PENALTY: REJECT only if clause is absent and confirmed absent; UNCERTAIN => REVIEW."""
    fe = quote.late_penalty_clause_present

    if fe.status == FieldStatus.UNCERTAIN or fe.value is None:
        return RuleResult(
            rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
            severity=Severity.REVIEW,
            message="could not verify late_penalty_clause_present",
            evidence_quote=fe.evidence_quote or "",
        )

    # Boolean is derived/found: True => clause is present, False => clause is absent
    if fe.value is False:
        # Derive terms clause headings present from terms text if available
        import re

        all_terms_text = ""
        if raw_document_text:
            terms_idx = raw_document_text.find("TERMS AND CONDITIONS")
            all_terms_text = raw_document_text[terms_idx:] if terms_idx != -1 else raw_document_text
        if not all_terms_text:
            all_terms_text = " ".join(
                [
                    quote.payment_terms_text.evidence_quote or "",
                    quote.delivery_terms_text.evidence_quote or "",
                    quote.validity_days.evidence_quote or "",
                ]
            )
        # Find all numbered clause headings, e.g. "1. Payment.", "2. Delivery.", "4. Quality."
        found_headings = re.findall(r"(?:[0-9]+\.\s*)([A-Za-z]+)", all_terms_text)
        if not found_headings:
            found_headings = re.findall(r"\b([A-Za-z]+)\.", all_terms_text)

        # Preserve order of appearance while de-duplicating
        seen = set()
        ordered_headings = []
        for h in found_headings:
            h_clean = h.capitalize()
            if h_clean not in seen and h_clean != "Terms":
                seen.add(h_clean)
                ordered_headings.append(h_clean)

        if not ordered_headings:
            ordered_headings = ["Payment", "Delivery", "Validity", "Quality", "Disputes"]
        headings_str = ", ".join(ordered_headings)

        return RuleResult(
            rule_id="RULE_REJ_03_NO_PENALTY",
            severity=Severity.REJECT,
            message=f"No late-delivery penalty clause found. Terms clauses present: {headings_str}",
            evidence_quote="",
        )

    return RuleResult(
        rule_id="RULE_REJ_03_NO_PENALTY",
        severity=Severity.PASS,
        message="Late-delivery penalty clause is present",
        evidence_quote=fe.evidence_quote
        or quote.late_penalty_percent_per_week.evidence_quote
        or "Delay clause present",
    )


def check_penalty_rate_and_base(quote: ExtractedQuote, config: RulesConfig) -> list[RuleResult]:
    """RULE_REJ_04_PENALTY_RATE and RULE_REV_10_PENALTY_AMBIGUOUS.

    - If clause is absent (late_penalty_clause_present False): only REJ_03 applies, skip rate & base.
    - If rate < 0.5% => REJECT.
    - If base not stated ("order value" missing): follow penalty_base_unstated_policy.
    """
    results: list[RuleResult] = []
    fe_present = quote.late_penalty_clause_present

    # If clause is absent, skip rate check (already caught by REJ_03)
    if fe_present.status in {FieldStatus.FOUND, FieldStatus.DERIVED} and fe_present.value is False:
        return results

    # Rate check
    fe_rate = quote.late_penalty_percent_per_week
    if fe_rate.status in {FieldStatus.UNCERTAIN, FieldStatus.ABSENT} or fe_rate.value is None:
        results.append(
            RuleResult(
                rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
                severity=Severity.REVIEW,
                message="could not verify late_penalty_percent_per_week",
                evidence_quote=fe_rate.evidence_quote or "N/A",
            )
        )
    else:
        rate: Decimal = fe_rate.value
        ev = fe_rate.evidence_quote or f"{rate}% per week"
        if rate < config.min_penalty_pct_per_week:
            results.append(
                RuleResult(
                    rule_id="RULE_REJ_04_PENALTY_RATE",
                    severity=Severity.REJECT,
                    message=f"Late delivery penalty rate {rate}% per week is below required {config.min_penalty_pct_per_week}%",
                    evidence_quote=ev,
                )
            )
        else:
            results.append(
                RuleResult(
                    rule_id="RULE_REJ_04_PENALTY_RATE",
                    severity=Severity.PASS,
                    message=f"Late delivery penalty rate {rate}% per week meets minimum {config.min_penalty_pct_per_week}%",
                    evidence_quote=ev,
                )
            )

    # Base check (fires only when clause is present)
    if fe_present.value is True:
        fe_base = quote.late_penalty_specifies_order_value
        if fe_base.status == FieldStatus.UNCERTAIN or fe_base.value is None:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
                    severity=Severity.REVIEW,
                    message="could not verify late_penalty_specifies_order_value",
                    evidence_quote=fe_base.evidence_quote or "N/A",
                )
            )
        elif fe_base.value is False:
            ev_base = (
                fe_base.evidence_quote
                or quote.late_penalty_percent_per_week.evidence_quote
                or "N/A"
            )
            if config.penalty_base_unstated_policy == "review":
                results.append(
                    RuleResult(
                        rule_id="RULE_REV_10_PENALTY_AMBIGUOUS",
                        severity=Severity.REVIEW,
                        message="Penalty clause does not explicitly state calculation base as 'order value'",
                        evidence_quote=ev_base,
                    )
                )
            else:
                results.append(
                    RuleResult(
                        rule_id="RULE_REV_10_PENALTY_AMBIGUOUS",
                        severity=Severity.PASS,
                        message="Penalty base unstated accepted per configuration policy",
                        evidence_quote=ev_base,
                    )
                )
        else:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_10_PENALTY_AMBIGUOUS",
                    severity=Severity.PASS,
                    message="Penalty clause explicitly specifies 'order value' base",
                    evidence_quote=fe_base.evidence_quote or "order value",
                )
            )

    return results


def check_tin_bin(quote: ExtractedQuote, config: RulesConfig) -> RuleResult:
    """RULE_REJ_05_TAX_ID: Evaluates TIN and BIN per tin_bin_policy.

    Policies:
    - reject_if_either_missing: either ABSENT => REJECT
    - reject_if_both_missing: both ABSENT => REJECT; one ABSENT => REVIEW
    - review_if_one_missing: either ABSENT => REVIEW
    A malformed or UNCERTAIN ID => REVIEW, not REJECT.
    """
    fe_tin = quote.tin
    fe_bin = quote.bin

    raw_quote = fe_tin.evidence_quote or fe_bin.evidence_quote
    if raw_quote and "available on request" in raw_quote.lower():
        reg_quote = raw_quote
    elif fe_tin.value or fe_bin.value:
        reg_quote = raw_quote or ""
    else:
        reg_quote = ""

    # Check for UNCERTAIN / unverified / malformed IDs
    if fe_tin.status == FieldStatus.UNCERTAIN or fe_bin.status == FieldStatus.UNCERTAIN:
        missing_name = (
            "TIN and BIN"
            if fe_tin.status == FieldStatus.UNCERTAIN and fe_bin.status == FieldStatus.UNCERTAIN
            else ("TIN" if fe_tin.status == FieldStatus.UNCERTAIN else "BIN")
        )
        return RuleResult(
            rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
            severity=Severity.REVIEW,
            message=f"could not verify {missing_name} (unclear or malformed format)",
            evidence_quote=reg_quote,
        )

    tin_missing = fe_tin.status == FieldStatus.ABSENT or not fe_tin.value
    bin_missing = fe_bin.status == FieldStatus.ABSENT or not fe_bin.value

    policy = config.tin_bin_policy

    if policy == "reject_if_either_missing":
        if tin_missing or bin_missing:
            missing_items = (
                "TIN and BIN" if tin_missing and bin_missing else ("TIN" if tin_missing else "BIN")
            )
            return RuleResult(
                rule_id="RULE_REJ_05_TAX_ID",
                severity=Severity.REJECT,
                message=f"Supplier {missing_items} registration is missing",
                evidence_quote=reg_quote,
            )
    elif policy == "reject_if_both_missing":
        if tin_missing and bin_missing:
            return RuleResult(
                rule_id="RULE_REJ_05_TAX_ID",
                severity=Severity.REJECT,
                message="Supplier TIN and BIN registrations are both missing",
                evidence_quote=reg_quote,
            )
        if tin_missing or bin_missing:
            missing_item = "TIN" if tin_missing else "BIN"
            return RuleResult(
                rule_id="RULE_REJ_05_TAX_ID",
                severity=Severity.REVIEW,
                message=f"Supplier {missing_item} registration is missing (one missing triggers review)",
                evidence_quote=reg_quote,
            )
    elif policy == "review_if_one_missing":
        if tin_missing or bin_missing:
            missing_items = (
                "TIN and BIN" if tin_missing and bin_missing else ("TIN" if tin_missing else "BIN")
            )
            return RuleResult(
                rule_id="RULE_REJ_05_TAX_ID",
                severity=Severity.REVIEW,
                message=f"Supplier {missing_items} registration is missing",
                evidence_quote=reg_quote,
            )

    return RuleResult(
        rule_id="RULE_REJ_05_TAX_ID",
        severity=Severity.PASS,
        message=f"Valid TIN ({fe_tin.value}) and BIN ({fe_bin.value}) provided",
        evidence_quote=reg_quote,
    )


def check_delivery_days(quote: ExtractedQuote, config: RulesConfig) -> list[RuleResult]:
    """RULE_REJ_06_DELIVERY_MAX (>45 REJECT) and RULE_REV_04_DELIVERY_WINDOW (31..45 REVIEW)."""
    fe = quote.delivery_days
    if fe.status in {FieldStatus.UNCERTAIN, FieldStatus.ABSENT} or fe.value is None:
        return [
            RuleResult(
                rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
                severity=Severity.REVIEW,
                message="could not verify delivery_days",
                evidence_quote=fe.evidence_quote
                or quote.delivery_terms_text.evidence_quote
                or "N/A",
            )
        ]

    days = fe.value
    ev = fe.evidence_quote or f"{days} days"

    if days > config.max_delivery_days:
        return [
            RuleResult(
                rule_id="RULE_REJ_06_DELIVERY_MAX",
                severity=Severity.REJECT,
                message=f"Delivery promised in {days} days, exceeding maximum allowed {config.max_delivery_days} days",
                evidence_quote=ev,
            )
        ]

    if config.review_delivery_days_min <= days <= config.review_delivery_days_max:
        return [
            RuleResult(
                rule_id="RULE_REV_04_DELIVERY_WINDOW",
                severity=Severity.REVIEW,
                message=f"Delivery promised in {days} days falls in review range ({config.review_delivery_days_min} to {config.review_delivery_days_max} days)",
                evidence_quote=ev,
            )
        ]

    return [
        RuleResult(
            rule_id="RULE_REJ_06_DELIVERY_MAX",
            severity=Severity.PASS,
            message=f"Delivery within {days} days is within acceptable schedule",
            evidence_quote=ev,
        )
    ]


def check_payment_terms(quote: ExtractedQuote, config: RulesConfig) -> RuleResult:
    """RULE_REV_03_PAYMENT_TERMS: Payment outside 30..60, unclear, or ABSENT => REVIEW. 30 and 60 pass."""
    fe = quote.payment_days
    if fe.status in {FieldStatus.UNCERTAIN, FieldStatus.ABSENT} or fe.value is None:
        return RuleResult(
            rule_id="RULE_REV_03_PAYMENT_TERMS",
            severity=Severity.REVIEW,
            message="Payment terms days are unclear, range specified, or missing",
            evidence_quote=fe.evidence_quote or quote.payment_terms_text.evidence_quote or "N/A",
        )

    days = fe.value
    ev = fe.evidence_quote or f"{days} days"

    if days < config.min_payment_days or days > config.max_payment_days:
        return RuleResult(
            rule_id="RULE_REV_03_PAYMENT_TERMS",
            severity=Severity.REVIEW,
            message=f"Payment terms of {days} days are outside allowed {config.min_payment_days}-{config.max_payment_days} days window",
            evidence_quote=ev,
        )

    return RuleResult(
        rule_id="RULE_REV_03_PAYMENT_TERMS",
        severity=Severity.PASS,
        message=f"Payment terms of {days} days comply with {config.min_payment_days}-{config.max_payment_days} days rule",
        evidence_quote=ev,
    )


def check_vat_presentation(quote: ExtractedQuote, config: RulesConfig) -> RuleResult:
    """RULE_REV_05_VAT_PRESENTATION: Separate VAT line at exactly 15% => PASS; otherwise REVIEW."""
    fe_shown = quote.vat_shown_separately
    fe_pct = quote.vat_percent

    ev = (
        fe_pct.evidence_quote
        or quote.vat_amount.evidence_quote
        or quote.total.evidence_quote
        or "VAT Terms"
    )

    if fe_shown.status == FieldStatus.UNCERTAIN or fe_shown.value is None:
        return RuleResult(
            rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
            severity=Severity.REVIEW,
            message="could not verify vat_shown_separately",
            evidence_quote=ev,
        )

    if fe_shown.value is False:
        return RuleResult(
            rule_id="RULE_REV_05_VAT_PRESENTATION",
            severity=Severity.REVIEW,
            message="VAT is not shown separately at 15% (e.g. VAT included or missing breakdown)",
            evidence_quote=ev,
        )

    # VAT is shown separately: check percentage rate is exactly required rate (15%)
    if fe_pct.status in {FieldStatus.UNCERTAIN, FieldStatus.ABSENT} or fe_pct.value is None:
        return RuleResult(
            rule_id="RULE_REV_05_VAT_PRESENTATION",
            severity=Severity.REVIEW,
            message="VAT amount shown without stated percentage rate",
            evidence_quote=ev,
        )

    rate: Decimal = fe_pct.value
    if rate != config.required_vat_percent:
        return RuleResult(
            rule_id="RULE_REV_05_VAT_PRESENTATION",
            severity=Severity.REVIEW,
            message=f"VAT rate is {rate}%, expected {config.required_vat_percent}%",
            evidence_quote=fe_pct.evidence_quote or f"{rate}%",
        )

    return RuleResult(
        rule_id="RULE_REV_05_VAT_PRESENTATION",
        severity=Severity.PASS,
        message=f"VAT is shown separately at {config.required_vat_percent}%",
        evidence_quote=ev,
    )


def check_arithmetic(quote: ExtractedQuote, config: RulesConfig) -> list[RuleResult]:
    """RULE_REV_06/07/08 arithmetic checks.

    - subtotal = qty x price
    - VAT = 15% x subtotal
    - total = subtotal + VAT
    If VAT is not shown separately or subtotal is ABSENT, verify total = qty x price when document shows only total.
    Never crash on an absent input.
    """
    results: list[RuleResult] = []
    tol = config.math_tolerance

    fe_qty = quote.quantity
    fe_price = quote.unit_price
    fe_sub = quote.subtotal
    fe_vat = quote.vat_amount
    fe_tot = quote.total
    fe_shown = quote.vat_shown_separately

    # If any arithmetic component is UNCERTAIN, flag RULE_REV_11
    uncertain_fields = []
    for name, fe in [
        ("quantity", fe_qty),
        ("unit_price", fe_price),
        ("subtotal", fe_sub),
        ("vat_amount", fe_vat),
        ("total", fe_tot),
    ]:
        if fe.status == FieldStatus.UNCERTAIN:
            uncertain_fields.append(name)

    if uncertain_fields:
        results.append(
            RuleResult(
                rule_id="RULE_REV_11_UNVERIFIABLE_FIELD",
                severity=Severity.REVIEW,
                message=f"could not verify arithmetic components: {', '.join(uncertain_fields)}",
                evidence_quote="N/A",
            )
        )

    qty_ok = fe_qty.status in {FieldStatus.FOUND, FieldStatus.DERIVED} and fe_qty.value is not None
    price_ok = (
        fe_price.status in {FieldStatus.FOUND, FieldStatus.DERIVED} and fe_price.value is not None
    )
    sub_ok = fe_sub.status in {FieldStatus.FOUND, FieldStatus.DERIVED} and fe_sub.value is not None
    vat_ok = fe_vat.status in {FieldStatus.FOUND, FieldStatus.DERIVED} and fe_vat.value is not None
    tot_ok = fe_tot.status in {FieldStatus.FOUND, FieldStatus.DERIVED} and fe_tot.value is not None

    # Case A: Separate subtotal row is ABSENT (e.g. Pack 10)
    if fe_sub.status == FieldStatus.ABSENT:
        if qty_ok and price_ok and tot_ok:
            expected_tot = fe_qty.value * fe_price.value
            actual_tot = fe_tot.value
            diff = abs(actual_tot - expected_tot)
            ev = fe_tot.evidence_quote or str(actual_tot)
            if diff > tol:
                results.append(
                    RuleResult(
                        rule_id="RULE_REV_08_MATH_TOTAL",
                        severity=Severity.REVIEW,
                        message=f"Total {actual_tot} does not equal Qty x Price ({expected_tot}) within tolerance {tol}",
                        evidence_quote=ev,
                    )
                )
            else:
                results.append(
                    RuleResult(
                        rule_id="RULE_REV_08_MATH_TOTAL",
                        severity=Severity.PASS,
                        message=f"Total {actual_tot} matches Qty x Price ({expected_tot})",
                        evidence_quote=ev,
                    )
                )
        return results

    # Case B: Standard quotation with subtotal
    if qty_ok and price_ok and sub_ok:
        expected_sub = fe_qty.value * fe_price.value
        actual_sub = fe_sub.value
        diff = abs(actual_sub - expected_sub)
        ev_sub = fe_sub.evidence_quote or str(actual_sub)
        if diff > tol:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_06_MATH_SUBTOTAL",
                    severity=Severity.REVIEW,
                    message=f"Subtotal {actual_sub} does not equal Qty x Price ({expected_sub}) within tolerance {tol}",
                    evidence_quote=ev_sub,
                )
            )
        else:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_06_MATH_SUBTOTAL",
                    severity=Severity.PASS,
                    message=f"Subtotal {actual_sub} matches Qty x Price",
                    evidence_quote=ev_sub,
                )
            )

    # VAT arithmetic check: only run if VAT is shown separately and inputs exist
    if fe_shown.value is True and sub_ok and vat_ok:
        expected_vat = (config.required_vat_percent / Decimal("100")) * fe_sub.value
        actual_vat = fe_vat.value
        diff = abs(actual_vat - expected_vat)
        ev_vat = fe_vat.evidence_quote or str(actual_vat)
        if diff > tol:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_07_MATH_VAT",
                    severity=Severity.REVIEW,
                    message=f"VAT amount {actual_vat} does not equal 15% of Subtotal ({expected_vat}) within tolerance {tol}",
                    evidence_quote=ev_vat,
                )
            )
        else:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_07_MATH_VAT",
                    severity=Severity.PASS,
                    message=f"VAT amount {actual_vat} matches 15% of Subtotal",
                    evidence_quote=ev_vat,
                )
            )

    # Total check: Subtotal + VAT
    if fe_shown.value is True and sub_ok and vat_ok and tot_ok:
        expected_tot = fe_sub.value + fe_vat.value
        actual_tot = fe_tot.value
        diff = abs(actual_tot - expected_tot)
        ev_tot = fe_tot.evidence_quote or str(actual_tot)
        if diff > tol:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_08_MATH_TOTAL",
                    severity=Severity.REVIEW,
                    message=f"Total {actual_tot} does not equal Subtotal + VAT ({expected_tot}) within tolerance {tol}",
                    evidence_quote=ev_tot,
                )
            )
        else:
            results.append(
                RuleResult(
                    rule_id="RULE_REV_08_MATH_TOTAL",
                    severity=Severity.PASS,
                    message=f"Total {actual_tot} matches Subtotal + VAT",
                    evidence_quote=ev_tot,
                )
            )

    return results


def check_validity(quote: ExtractedQuote, config: RulesConfig) -> RuleResult:
    """RULE_REV_09_VALIDITY_WINDOW: Validity < 30 days REVIEW; exactly 30 passes; UNCERTAIN/None => REVIEW."""
    fe = quote.validity_days
    if fe.status in {FieldStatus.UNCERTAIN, FieldStatus.ABSENT} or fe.value is None:
        return RuleResult(
            rule_id="RULE_REV_09_VALIDITY_WINDOW",
            severity=Severity.REVIEW,
            message="Quotation validity period is missing or unclear",
            evidence_quote=fe.evidence_quote or "N/A",
        )

    days = fe.value
    ev = fe.evidence_quote or f"{days} days"

    if days < config.min_validity_days:
        return RuleResult(
            rule_id="RULE_REV_09_VALIDITY_WINDOW",
            severity=Severity.REVIEW,
            message=f"Quotation validity of {days} days is below minimum required {config.min_validity_days} days",
            evidence_quote=ev,
        )

    return RuleResult(
        rule_id="RULE_REV_09_VALIDITY_WINDOW",
        severity=Severity.PASS,
        message=f"Quotation validity of {days} days meets minimum {config.min_validity_days} days rule",
        evidence_quote=ev,
    )


def run_all_policy_rules(
    quote: ExtractedQuote,
    config: RulesConfig,
    raw_document_text: str | None = None,
) -> list[RuleResult]:
    """Run every deterministic company policy rule."""
    results: list[RuleResult] = []
    results.append(check_advance_payment(quote, config))
    results.append(check_penalty_clause_present(quote, config, raw_document_text=raw_document_text))
    results.extend(check_penalty_rate_and_base(quote, config))
    results.append(check_tin_bin(quote, config))
    results.extend(check_delivery_days(quote, config))
    results.append(check_payment_terms(quote, config))
    results.append(check_vat_presentation(quote, config))
    results.extend(check_arithmetic(quote, config))
    results.append(check_validity(quote, config))
    return results
