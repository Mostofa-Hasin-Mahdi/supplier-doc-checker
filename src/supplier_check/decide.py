"""Deterministic verdict consolidation and precedence logic."""

from supplier_check.models import Decision, RuleResult, Severity, Verdict


def make_decision(
    rule_results: list[RuleResult],
    grounding_errors: list[str] | None = None,
    extraction_errors: list[str] | None = None,
) -> Decision:
    """Aggregate rule results following strict precedence:

    Precedence:
    1. Any REJECT -> Verdict.REJECT
    2. Else any REVIEW, grounding error, or extraction error -> Verdict.NEEDS_REVIEW
    3. Else -> Verdict.APPROVE

    Never short-circuits: evaluates and collects ALL triggered rules.
    Reasons are de-duplicated and format the supporting quote.
    """
    g_errs = grounding_errors or []
    ext_errs = extraction_errors or []

    triggered_rules: list[RuleResult] = []
    reasons_set: set[str] = set()
    reasons_list: list[str] = []

    has_reject = False
    has_review = False

    def add_reason(r_text: str) -> None:
        if r_text not in reasons_set:
            reasons_set.add(r_text)
            reasons_list.append(r_text)

    # Process extraction errors
    for err in ext_errs:
        has_review = True
        add_reason(f"Extraction error: {err}")

    # Process grounding errors
    for g_err in g_errs:
        has_review = True
        add_reason(f"Grounding failure: {g_err}")

    # Process evaluated rule results: separate reject and review to ensure Reject first
    reject_rules: list[RuleResult] = []
    review_rules: list[RuleResult] = []
    seen_rule_ids: set[str] = set()

    for res in rule_results:
        if res.severity in {Severity.REJECT, Severity.REVIEW}:
            if res.rule_id not in seen_rule_ids:
                seen_rule_ids.add(res.rule_id)
                if res.severity == Severity.REJECT:
                    reject_rules.append(res)
                else:
                    review_rules.append(res)

    for res in reject_rules:
        has_reject = True
        triggered_rules.append(res)
        quote_suffix = (
            f" (quote: '{res.evidence_quote}')"
            if res.evidence_quote and res.evidence_quote != "N/A"
            else ""
        )
        add_reason(f"[{res.rule_id}] {res.message}{quote_suffix}")

    for res in review_rules:
        has_review = True
        triggered_rules.append(res)
        quote_suffix = (
            f" (quote: '{res.evidence_quote}')"
            if res.evidence_quote and res.evidence_quote != "N/A"
            else ""
        )
        add_reason(f"[{res.rule_id}] {res.message}{quote_suffix}")

    # Precedence resolution:
    # "Never Guess" Policy: Any extraction or grounding error strictly forces NEEDS_REVIEW.
    # An unverified document must NEVER be rejected or approved based on ungrounded/corrupted text.
    if ext_errs or g_errs:
        final_verdict = Verdict.NEEDS_REVIEW
    elif has_reject:
        final_verdict = Verdict.REJECT
    elif has_review:
        final_verdict = Verdict.NEEDS_REVIEW
    else:
        final_verdict = Verdict.APPROVE
        add_reason("All procurement checks passed successfully.")

    return Decision(
        verdict=final_verdict,
        triggered_rules=triggered_rules,
        reasons=reasons_list,
    )
