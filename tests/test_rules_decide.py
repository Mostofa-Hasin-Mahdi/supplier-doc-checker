"""Unit tests for compare.py, rules.py, and decide.py."""

from decimal import Decimal

from supplier_check.compare import (
    compare_price,
    compare_quantity,
    match_item_with_pr,
)
from supplier_check.config import RulesConfig
from supplier_check.decide import make_decision
from supplier_check.models import (
    ExtractedQuote,
    FieldEvidence,
    FieldStatus,
    PurchaseRequestItem,
    RuleResult,
    Severity,
    Verdict,
)
from supplier_check.rules import (
    check_advance_payment,
    check_arithmetic,
    check_delivery_days,
    check_payment_terms,
    check_penalty_clause_present,
    check_penalty_rate_and_base,
    check_tin_bin,
    check_validity,
    check_vat_presentation,
    run_all_policy_rules,
)


def make_clean_quote(**kwargs) -> ExtractedQuote:
    """Helper creating a baseline fully passing ExtractedQuote."""
    defaults = {
        "supplier_name": FieldEvidence[str](status=FieldStatus.FOUND, value="Padma Textile Mills Ltd", evidence_quote="Padma Textile Mills Ltd"),
        "quotation_no": FieldEvidence[str](status=FieldStatus.FOUND, value="QT-2026-901", evidence_quote="QT-2026-901"),
        "quote_date": FieldEvidence[str](status=FieldStatus.FOUND, value="2026-10-21", evidence_quote="2026-10-21"),
        "reference_pr": FieldEvidence[str](status=FieldStatus.FOUND, value="PR-2026-114", evidence_quote="PR-2026-114"),
        "line_item_count": 1,
        "item_code": FieldEvidence[str](status=FieldStatus.FOUND, value="A", evidence_quote="A"),
        "description": FieldEvidence[str](status=FieldStatus.FOUND, value="Cotton twill fabric, 280 gsm", evidence_quote="Cotton twill fabric, 280 gsm"),
        "quantity": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("12000"), evidence_quote="12,000"),
        "unit": FieldEvidence[str](status=FieldStatus.FOUND, value="metre", evidence_quote="metre"),
        "unit_price": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("472.00"), evidence_quote="472.00"),
        "subtotal": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("5664000.00"), evidence_quote="5,664,000.00"),
        "vat_amount": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("849600.00"), evidence_quote="849,600.00"),
        "vat_percent": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("15.0"), evidence_quote="VAT 15%"),
        "vat_shown_separately": FieldEvidence[bool](status=FieldStatus.DERIVED, value=True, evidence_quote="VAT 15%"),
        "total": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("6513600.00"), evidence_quote="6,513,600.00"),
        "tin": FieldEvidence[str](status=FieldStatus.FOUND, value="101458013391", evidence_quote="TIN: 101458013391"),
        "bin": FieldEvidence[str](status=FieldStatus.FOUND, value="000170141-0101", evidence_quote="BIN: 000170141-0101"),
        "advance_percent": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("10.0"), evidence_quote="10% advance"),
        "payment_terms_text": FieldEvidence[str](status=FieldStatus.FOUND, value="Balance payable within 45 days", evidence_quote="within 45 days"),
        "payment_days": FieldEvidence[int](status=FieldStatus.FOUND, value=45, evidence_quote="within 45 days"),
        "delivery_terms_text": FieldEvidence[str](status=FieldStatus.FOUND, value="Delivery within 24 days", evidence_quote="within 24 days"),
        "delivery_days": FieldEvidence[int](status=FieldStatus.FOUND, value=24, evidence_quote="within 24 days"),
        "late_penalty_percent_per_week": FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("1.0"), evidence_quote="1% of order value"),
        "late_penalty_clause_present": FieldEvidence[bool](status=FieldStatus.DERIVED, value=True, evidence_quote="Late delivery penalty: 1% of order value"),
        "late_penalty_specifies_order_value": FieldEvidence[bool](status=FieldStatus.DERIVED, value=True, evidence_quote="1% of order value"),
        "validity_days": FieldEvidence[int](status=FieldStatus.FOUND, value=45, evidence_quote="valid for 45 days"),
    }
    defaults.update(kwargs)
    return ExtractedQuote(**defaults)


def make_sample_pr_items() -> list[PurchaseRequestItem]:
    return [
        PurchaseRequestItem(
            pr_number="PR-2026-114",
            item_code="A",
            description="Cotton twill fabric, 280 gsm",
            unit="metre",
            quantity_requested=Decimal("12000"),
            max_unit_price=Decimal("480.00"),
        ),
        PurchaseRequestItem(
            pr_number="PR-2026-114",
            item_code="B",
            description="Metal zipper, 18 cm",
            unit="piece",
            quantity_requested=Decimal("20000"),
            max_unit_price=Decimal("38.00"),
        ),
    ]


# -------------------------------------------------------------
# compare.py Tests
# -------------------------------------------------------------

def test_item_match_success() -> None:
    quote = make_clean_quote()
    pr_items = make_sample_pr_items()
    matched, res = match_item_with_pr(quote, pr_items)
    assert matched is not None
    assert matched.item_code == "A"
    assert res.severity == Severity.PASS


def test_item_match_line_item_count_none_or_multiple() -> None:
    pr_items = make_sample_pr_items()
    # None line item count
    quote_none = make_clean_quote(line_item_count=None)
    matched, res = match_item_with_pr(quote_none, pr_items)
    assert matched is None
    assert res.rule_id == "RULE_REV_12_ITEM_MATCH"
    assert res.severity == Severity.REVIEW

    # > 1 line items
    quote_multi = make_clean_quote(line_item_count=2)
    matched, res = match_item_with_pr(quote_multi, pr_items)
    assert matched is None
    assert res.severity == Severity.REVIEW


def test_item_match_mismatches() -> None:
    pr_items = make_sample_pr_items()
    # PR mismatch
    quote_bad_pr = make_clean_quote(reference_pr=FieldEvidence[str](status=FieldStatus.FOUND, value="PR-999", evidence_quote="PR-999"))
    matched, res = match_item_with_pr(quote_bad_pr, pr_items)
    assert matched is None
    assert res.severity == Severity.REVIEW

    # Item code mismatch
    quote_bad_code = make_clean_quote(item_code=FieldEvidence[str](status=FieldStatus.FOUND, value="Z", evidence_quote="Z"))
    matched, res = match_item_with_pr(quote_bad_code, pr_items)
    assert matched is None
    assert res.severity == Severity.REVIEW

    # Unit mismatch
    quote_bad_unit = make_clean_quote(unit=FieldEvidence[str](status=FieldStatus.FOUND, value="kg", evidence_quote="kg"))
    matched, res = match_item_with_pr(quote_bad_unit, pr_items)
    assert matched is None
    assert res.severity == Severity.REVIEW


def test_price_comparison_boundaries() -> None:
    config = RulesConfig(price_tolerance_pct=Decimal("3.0"))
    pr = PurchaseRequestItem(
        pr_number="PR-1", item_code="A", description="Item", unit="m",
        quantity_requested=Decimal("100"), max_unit_price=Decimal("100.00"),
    )

    # Within max: 100.00 <= 100.00 -> PASS
    q_pass = make_clean_quote(unit_price=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("100.00"), evidence_quote="100.00"))
    res = compare_price(q_pass, pr, config)
    assert res.severity == Severity.PASS

    # Exactly 3% over: 103.00 == 100 * (1 + 0.03) -> REVIEW
    q_exact_3 = make_clean_quote(unit_price=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("103.00"), evidence_quote="103.00"))
    res = compare_price(q_exact_3, pr, config)
    assert res.rule_id == "RULE_REV_01_PRICE_TOLERANCE"
    assert res.severity == Severity.REVIEW
    assert "3.00% above max" in res.message

    # Just over 3%: 103.01 > 103.00 -> REJECT
    q_over_3 = make_clean_quote(unit_price=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("103.01"), evidence_quote="103.01"))
    res = compare_price(q_over_3, pr, config)
    assert res.rule_id == "RULE_REJ_01_PRICE_MAX"
    assert res.severity == Severity.REJECT


def test_quantity_comparison_boundaries() -> None:
    config = RulesConfig(quantity_tolerance_pct=Decimal("5.0"))
    pr = PurchaseRequestItem(
        pr_number="PR-1", item_code="A", description="Item", unit="m",
        quantity_requested=Decimal("1000"), max_unit_price=Decimal("10.00"),
    )

    # Exactly 5% off: 950 (-5%) and 1050 (+5%) -> PASS
    q_exact_minus_5 = make_clean_quote(quantity=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("950"), evidence_quote="950"))
    assert compare_quantity(q_exact_minus_5, pr, config).severity == Severity.PASS

    q_exact_plus_5 = make_clean_quote(quantity=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("1050"), evidence_quote="1050"))
    assert compare_quantity(q_exact_plus_5, pr, config).severity == Severity.PASS

    # 5.01% off: 1051 -> REVIEW
    q_over_5 = make_clean_quote(quantity=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("1051"), evidence_quote="1051"))
    res = compare_quantity(q_over_5, pr, config)
    assert res.rule_id == "RULE_REV_02_QTY_TOLERANCE"
    assert res.severity == Severity.REVIEW


# -------------------------------------------------------------
# rules.py Tests
# -------------------------------------------------------------

def test_rule_rej_02_advance_boundaries() -> None:
    config = RulesConfig(max_advance_pct=Decimal("20.0"))

    # 20.0% -> PASS
    q_20 = make_clean_quote(advance_percent=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("20.0"), evidence_quote="20%"))
    assert check_advance_payment(q_20, config).severity == Severity.PASS

    # 20.1% -> REJECT
    q_20_1 = make_clean_quote(advance_percent=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("20.1"), evidence_quote="20.1%"))
    res = check_advance_payment(q_20_1, config)
    assert res.rule_id == "RULE_REJ_02_ADVANCE_MAX"
    assert res.severity == Severity.REJECT

    # UNCERTAIN -> REVIEW
    q_unc = make_clean_quote(advance_percent=FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN, value=None, evidence_quote="N/A"))
    assert check_advance_payment(q_unc, config).severity == Severity.REVIEW

    # ABSENT -> REVIEW
    q_abs = make_clean_quote(advance_percent=FieldEvidence[Decimal](status=FieldStatus.ABSENT, value=None, evidence_quote=None))
    assert check_advance_payment(q_abs, config).severity == Severity.REVIEW


def test_rule_rej_03_no_penalty_clause() -> None:
    config = RulesConfig()

    # Clause present (DERIVED True) -> PASS
    q_present = make_clean_quote(late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.DERIVED, value=True, evidence_quote="delay clause"))
    assert check_penalty_clause_present(q_present, config).severity == Severity.PASS

    # Clause absent (DERIVED False) -> REJECT
    q_absent = make_clean_quote(late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.DERIVED, value=False, evidence_quote=None, absence_note="absent"))
    res = check_penalty_clause_present(q_absent, config)
    assert res.rule_id == "RULE_REJ_03_NO_PENALTY"
    assert res.severity == Severity.REJECT

    # Test that REJ_03 message lists all terms clause headings found in text
    sample_terms_doc = (
        "TERMS AND CONDITIONS\n"
        "1. Payment. 10% advance payable with PO.\n"
        "2. Delivery. Delivery within 27 days of PO.\n"
        "3. Validity. Valid for 30 days.\n"
        "4. Quality. Defective goods replaced.\n"
        "5. Disputes. Settled by arbitration.\n"
    )
    res_headings = check_penalty_clause_present(q_absent, config, raw_document_text=sample_terms_doc)
    assert "Payment, Delivery, Validity, Quality, Disputes" in res_headings.message

    # Clause UNCERTAIN -> REVIEW
    q_unc = make_clean_quote(late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.UNCERTAIN, value=None, evidence_quote="delay?"))
    assert check_penalty_clause_present(q_unc, config).severity == Severity.REVIEW


def test_rule_rej_04_penalty_rate_boundaries() -> None:
    config = RulesConfig(min_penalty_pct_per_week=Decimal("0.5"), penalty_base_unstated_policy="review")

    # 0.5% -> PASS
    q_0_5 = make_clean_quote(
        late_penalty_percent_per_week=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("0.5"), evidence_quote="0.5%"),
        late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.DERIVED, value=True, evidence_quote="delay"),
    )
    results = check_penalty_rate_and_base(q_0_5, config)
    assert any(r.rule_id == "RULE_REJ_04_PENALTY_RATE" and r.severity == Severity.PASS for r in results)

    # 0.49% -> REJECT
    q_0_49 = make_clean_quote(
        late_penalty_percent_per_week=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("0.49"), evidence_quote="0.49%"),
        late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.DERIVED, value=True, evidence_quote="delay"),
    )
    results = check_penalty_rate_and_base(q_0_49, config)
    assert any(r.rule_id == "RULE_REJ_04_PENALTY_RATE" and r.severity == Severity.REJECT for r in results)

    # If clause is absent, rate check does not run (skip to avoid double penalty)
    q_clause_absent = make_clean_quote(late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.DERIVED, value=False, evidence_quote=None, absence_note="none"))
    results_absent = check_penalty_rate_and_base(q_clause_absent, config)
    assert len(results_absent) == 0


def test_rule_rev_10_penalty_base_policies() -> None:
    # When base unstated and policy is 'review' -> REVIEW
    config_rev = RulesConfig(penalty_base_unstated_policy="review")
    q_base_false = make_clean_quote(
        late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.DERIVED, value=True, evidence_quote="delay"),
        late_penalty_specifies_order_value=FieldEvidence[bool](status=FieldStatus.DERIVED, value=False, evidence_quote="0.5% per week of delay"),
    )
    res_rev = check_penalty_rate_and_base(q_base_false, config_rev)
    assert any(r.rule_id == "RULE_REV_10_PENALTY_AMBIGUOUS" and r.severity == Severity.REVIEW for r in res_rev)

    # When base unstated and policy is 'accept' -> PASS
    config_acc = RulesConfig(penalty_base_unstated_policy="accept")
    res_acc = check_penalty_rate_and_base(q_base_false, config_acc)
    assert any(r.rule_id == "RULE_REV_10_PENALTY_AMBIGUOUS" and r.severity == Severity.PASS for r in res_acc)


def test_rule_rej_05_tin_bin_policies() -> None:
    # 1. reject_if_either_missing
    cfg_either = RulesConfig(tin_bin_policy="reject_if_either_missing")
    q_tin_absent = make_clean_quote(
        tin=FieldEvidence[str](status=FieldStatus.ABSENT, value=None, absence_note="on request"),
        bin=FieldEvidence[str](status=FieldStatus.FOUND, value="000170141-0101", evidence_quote="BIN: 000170141-0101"),
    )
    assert check_tin_bin(q_tin_absent, cfg_either).severity == Severity.REJECT

    # 2. reject_if_both_missing: one missing -> REVIEW, both missing -> REJECT
    cfg_both = RulesConfig(tin_bin_policy="reject_if_both_missing")
    assert check_tin_bin(q_tin_absent, cfg_both).severity == Severity.REVIEW

    q_both_absent = make_clean_quote(
        tin=FieldEvidence[str](status=FieldStatus.ABSENT, value=None, absence_note="on request"),
        bin=FieldEvidence[str](status=FieldStatus.ABSENT, value=None, absence_note="on request"),
    )
    assert check_tin_bin(q_both_absent, cfg_both).severity == Severity.REJECT

    # 3. review_if_one_missing: either missing -> REVIEW
    cfg_one = RulesConfig(tin_bin_policy="review_if_one_missing")
    assert check_tin_bin(q_tin_absent, cfg_one).severity == Severity.REVIEW

    # 4. UNCERTAIN or malformed ID -> REVIEW, not REJECT
    q_malformed = make_clean_quote(
        tin=FieldEvidence[str](status=FieldStatus.UNCERTAIN, value="abc", evidence_quote="TIN: abc"),
    )
    res_malformed = check_tin_bin(q_malformed, cfg_either)
    assert res_malformed.rule_id == "RULE_REV_11_UNVERIFIABLE_FIELD"
    assert res_malformed.severity == Severity.REVIEW


def test_delivery_days_boundaries() -> None:
    config = RulesConfig(max_delivery_days=45, review_delivery_days_min=31, review_delivery_days_max=45)

    # 30 days -> PASS
    q_30 = make_clean_quote(delivery_days=FieldEvidence[int](status=FieldStatus.FOUND, value=30, evidence_quote="30 days"))
    assert check_delivery_days(q_30, config)[0].severity == Severity.PASS

    # 31 days -> REVIEW (boundary of 31..45)
    q_31 = make_clean_quote(delivery_days=FieldEvidence[int](status=FieldStatus.FOUND, value=31, evidence_quote="31 days"))
    res_31 = check_delivery_days(q_31, config)[0]
    assert res_31.rule_id == "RULE_REV_04_DELIVERY_RANGE"
    assert res_31.severity == Severity.REVIEW

    # 45 days -> REVIEW
    q_45 = make_clean_quote(delivery_days=FieldEvidence[int](status=FieldStatus.FOUND, value=45, evidence_quote="45 days"))
    assert check_delivery_days(q_45, config)[0].severity == Severity.REVIEW

    # 46 days -> REJECT (> 45 days)
    q_46 = make_clean_quote(delivery_days=FieldEvidence[int](status=FieldStatus.FOUND, value=46, evidence_quote="46 days"))
    res_46 = check_delivery_days(q_46, config)[0]
    assert res_46.rule_id == "RULE_REJ_06_DELIVERY_MAX"
    assert res_46.severity == Severity.REJECT


def test_payment_terms_boundaries() -> None:
    config = RulesConfig(min_payment_days=30, max_payment_days=60)

    # 29 days -> REVIEW
    q_29 = make_clean_quote(payment_days=FieldEvidence[int](status=FieldStatus.FOUND, value=29, evidence_quote="29 days"))
    assert check_payment_terms(q_29, config).severity == Severity.REVIEW

    # 30 days -> PASS
    q_30 = make_clean_quote(payment_days=FieldEvidence[int](status=FieldStatus.FOUND, value=30, evidence_quote="30 days"))
    assert check_payment_terms(q_30, config).severity == Severity.PASS

    # 60 days -> PASS
    q_60 = make_clean_quote(payment_days=FieldEvidence[int](status=FieldStatus.FOUND, value=60, evidence_quote="60 days"))
    assert check_payment_terms(q_60, config).severity == Severity.PASS

    # 61 days -> REVIEW
    q_61 = make_clean_quote(payment_days=FieldEvidence[int](status=FieldStatus.FOUND, value=61, evidence_quote="61 days"))
    assert check_payment_terms(q_61, config).severity == Severity.REVIEW

    # UNCERTAIN -> REVIEW
    q_unc = make_clean_quote(payment_days=FieldEvidence[int](status=FieldStatus.UNCERTAIN, value=None, evidence_quote="30 to 90 days"))
    assert check_payment_terms(q_unc, config).severity == Severity.REVIEW


def test_vat_presentation() -> None:
    config = RulesConfig(required_vat_percent=Decimal("15.0"))

    # Separate 15% -> PASS
    q_pass = make_clean_quote()
    assert check_vat_presentation(q_pass, config).severity == Severity.PASS

    # Not shown separately (e.g. Pack 10) -> REVIEW
    q_not_shown = make_clean_quote(
        vat_shown_separately=FieldEvidence[bool](status=FieldStatus.DERIVED, value=False, evidence_quote=None, absence_note="included"),
    )
    assert check_vat_presentation(q_not_shown, config).severity == Severity.REVIEW

    # Stated at 10% instead of 15% -> REVIEW
    q_diff_rate = make_clean_quote(
        vat_percent=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("10.0"), evidence_quote="VAT 10%"),
    )
    assert check_vat_presentation(q_diff_rate, config).severity == Severity.REVIEW


def test_arithmetic_subtotal_absent_pack_10_style() -> None:
    """When subtotal is absent (Pack 10), verify total = qty x price without crashing."""
    config = RulesConfig(math_tolerance=Decimal("1.00"))
    # Pack 10: 3000 x 94.00 = 282,000.00
    q_p10 = make_clean_quote(
        quantity=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("3000"), evidence_quote="3,000"),
        unit_price=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("94.00"), evidence_quote="94.00"),
        subtotal=FieldEvidence[Decimal](status=FieldStatus.ABSENT, value=None, absence_note="no subtotal"),
        vat_amount=FieldEvidence[Decimal](status=FieldStatus.ABSENT, value=None, absence_note="no vat"),
        vat_percent=FieldEvidence[Decimal](status=FieldStatus.ABSENT, value=None, absence_note="no vat"),
        vat_shown_separately=FieldEvidence[bool](status=FieldStatus.DERIVED, value=False, evidence_quote="VAT included"),
        total=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("282000.00"), evidence_quote="282,000.00"),
    )
    results = check_arithmetic(q_p10, config)
    assert len(results) == 1
    assert results[0].rule_id == "RULE_REV_08_MATH_TOTAL"
    assert results[0].severity == Severity.PASS


def test_arithmetic_mismatch_triggers_review() -> None:
    config = RulesConfig(math_tolerance=Decimal("1.00"))
    # 50,000 x 6.40 = 320,000 vs stated subtotal 322,000
    q_mismatch = make_clean_quote(
        quantity=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("50000"), evidence_quote="50,000"),
        unit_price=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("6.40"), evidence_quote="6.40"),
        subtotal=FieldEvidence[Decimal](status=FieldStatus.FOUND, value=Decimal("322000.00"), evidence_quote="322,000.00"),
    )
    results = check_arithmetic(q_mismatch, config)
    sub_res = [r for r in results if r.rule_id == "RULE_REV_06_MATH_SUBTOTAL"][0]
    assert sub_res.severity == Severity.REVIEW


def test_validity_boundaries() -> None:
    config = RulesConfig(min_validity_days=30)

    # 29 days -> REVIEW
    q_29 = make_clean_quote(validity_days=FieldEvidence[int](status=FieldStatus.FOUND, value=29, evidence_quote="29 days"))
    assert check_validity(q_29, config).severity == Severity.REVIEW

    # 30 days -> PASS
    q_30 = make_clean_quote(validity_days=FieldEvidence[int](status=FieldStatus.FOUND, value=30, evidence_quote="30 days"))
    assert check_validity(q_30, config).severity == Severity.PASS


# -------------------------------------------------------------
# decide.py Tests
# -------------------------------------------------------------

def test_decide_precedence_and_reporting() -> None:
    # 1. Clean quote -> APPROVE
    clean_results = [
        RuleResult(rule_id="RULE_1", severity=Severity.PASS, message="ok", evidence_quote="ok"),
    ]
    dec_app = make_decision(clean_results)
    assert dec_app.verdict == Verdict.APPROVE
    assert dec_app.display_verdict == "Approve"

    # 2. Contains REVIEW -> NEEDS_REVIEW
    rev_results = [
        RuleResult(rule_id="RULE_1", severity=Severity.PASS, message="ok", evidence_quote="ok"),
        RuleResult(rule_id="RULE_REV_01", severity=Severity.REVIEW, message="Price slightly over", evidence_quote="6.65"),
    ]
    dec_rev = make_decision(rev_results)
    assert dec_rev.verdict == Verdict.NEEDS_REVIEW
    assert dec_rev.display_verdict == "Needs a person to check"
    assert len(dec_rev.triggered_rules) == 1

    # 3. Contains both REJECT and REVIEW -> REJECT, but reports ALL triggered rules
    mixed_results = [
        RuleResult(rule_id="RULE_REV_01", severity=Severity.REVIEW, message="Price slightly over", evidence_quote="6.65"),
        RuleResult(rule_id="RULE_REJ_02", severity=Severity.REJECT, message="Advance 40%", evidence_quote="40%"),
    ]
    dec_mix = make_decision(mixed_results)
    assert dec_mix.verdict == Verdict.REJECT
    assert dec_mix.display_verdict == "Reject"
    assert len(dec_mix.triggered_rules) == 2
    assert any("RULE_REV_01" in r for r in dec_mix.reasons)
    assert any("RULE_REJ_02" in r for r in dec_mix.reasons)

    # 4. Grounding failure forces NEEDS_REVIEW even if rules passed
    dec_grounding = make_decision(clean_results, grounding_errors=["Quote not verbatim"])
    assert dec_grounding.verdict == Verdict.NEEDS_REVIEW
    assert any("Grounding failure" in r for r in dec_grounding.reasons)


def test_uncertain_fields_never_produce_pass() -> None:
    """Every rule must yield REVIEW for UNCERTAIN fields, never PASS or REJECT."""
    config = RulesConfig()
    quote = make_clean_quote(
        unit_price=FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN, value=None),
        advance_percent=FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN, value=None),
        delivery_days=FieldEvidence[int](status=FieldStatus.UNCERTAIN, value=None),
        payment_days=FieldEvidence[int](status=FieldStatus.UNCERTAIN, value=None),
        validity_days=FieldEvidence[int](status=FieldStatus.UNCERTAIN, value=None),
        late_penalty_clause_present=FieldEvidence[bool](status=FieldStatus.UNCERTAIN, value=None),
        late_penalty_percent_per_week=FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN, value=None),
    )
    all_results = run_all_policy_rules(quote, config)
    # Filter non-pass results
    non_pass_rules = [r for r in all_results if r.severity != Severity.PASS]
    assert len(non_pass_rules) >= 6
    assert all(r.severity == Severity.REVIEW for r in non_pass_rules)

