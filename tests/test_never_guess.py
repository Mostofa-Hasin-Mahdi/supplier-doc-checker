"""Never-guess policy tests.

Ensures that:
- Garbled text, empty text, a PDF with no text, an LLM returning invalid JSON,
  an LLM raw value not in text (hallucination guard), and an LLM that disagrees
  with the fallback extractor all strictly end in 'Needs a person to check' (NEEDS_REVIEW)
  with an explanatory entry in the audit log.
- No UNCERTAIN field can ever lead to an APPROVE verdict.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from supplier_check.config import RulesConfig
from supplier_check.decide import make_decision
from supplier_check.graph import build_supplier_checker_graph
from supplier_check.llm_client import FakeLLMClient
from supplier_check.models import (
    ExtractedQuote,
    FieldEvidence,
    FieldStatus,
    Verdict,
)
from supplier_check.rules import run_all_policy_rules


def test_garbled_text_ends_in_needs_review() -> None:
    """Garbled/corrupted text cannot be reliably extracted and must route to NEEDS_REVIEW."""
    garbled = "%%%$$$@@@ !@#$%^&*()_+ ??? ||||"
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_garbled"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "raw_text": garbled,
            "extractor_mode": "fallback",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    # Audit log must contain explanation
    assert len(state.values["audit_log"]) > 0


def test_empty_text_ends_in_needs_review() -> None:
    """Empty string raw text must route to NEEDS_REVIEW with audit log explanation."""
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_empty_str"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "raw_text": "   \n\t   ",
            "extractor_mode": "fallback",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    assert any("empty" in log.lower() for log in state.values["audit_log"])


def test_pdf_with_no_text_ends_in_needs_review(tmp_path: Path) -> None:
    """A zero-byte PDF file must route to NEEDS_REVIEW with audit log note."""
    empty_pdf = tmp_path / "blank.pdf"
    empty_pdf.write_bytes(b"")

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_blank_pdf"}}

    app.invoke(
        {"pdf_path": str(empty_pdf), "extractor_mode": "fallback"},
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    assert any(
        "empty or unreadable" in log.lower() or "exception" in log.lower()
        for log in state.values["audit_log"]
    )


def test_llm_invalid_json_ends_in_needs_review_when_fallback_fails() -> None:
    """When LLM returns invalid JSON on garbled text where fallback cannot find fields => NEEDS_REVIEW."""
    bad_llm = FakeLLMClient("not json")
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=bad_llm)
    cfg = {"configurable": {"thread_id": "test_bad_llm_json"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "raw_text": "Random text without table or terms",
            "extractor_mode": "llm",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    assert any(
        "falling back" in log.lower()
        or "could not verify" in str(state.values["decision"].reasons).lower()
        for log in state.values["audit_log"]
    )


def test_llm_hallucinated_value_not_in_text_triggers_needs_review() -> None:
    """If LLM proposes a raw value not present in text, hallucination guard marks it UNCERTAIN => NEEDS_REVIEW."""
    canned: dict[str, Any] = {
        "supplier_name": "Padma Textile Mills Ltd",
        "quotation_no": "QT-2026-901",
        "quote_date": "2026-10-21",
        "reference_pr": "PR-2026-114",
        "item_code": "A",
        "description": "Cotton twill fabric, 280 gsm",
        "quantity": "99,999,999",  # Hallucinated: does NOT exist anywhere in text
        "unit": "metre",
        "unit_price": "472.00",
        "subtotal": "5,664,000.00",
        "vat_amount": "849,600.00",
        "vat_percent": "15%",
        "total": "6,513,600.00",
        "tin": "101458013391",
        "bin": "000170141-0101",
        "advance_percent": "10%",
        "payment_terms_text": "within 45 days",
        "delivery_terms_text": "within 24 days",
        "late_penalty_text": "1% of order value",
        "validity_text": "45 days",
    }
    llm = FakeLLMClient(canned)
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=llm)
    cfg = {"configurable": {"thread_id": "test_hallucination"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "extractor_mode": "llm",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    assert any("hallucination guard" in log.lower() for log in state.values["audit_log"])


def test_llm_disagrees_with_fallback_triggers_needs_review() -> None:
    """LLM disagreeing with fallback on decision field (unit_price) strictly yields NEEDS_REVIEW."""
    canned: dict[str, Any] = {
        "supplier_name": "Padma Textile Mills Ltd",
        "quotation_no": "QT-2026-901",
        "quote_date": "2026-10-21",
        "reference_pr": "PR-2026-114",
        "item_code": "A",
        "description": "Cotton twill fabric, 280 gsm",
        "quantity": "12,000",
        "unit": "metre",
        "unit_price": "999.00",  # Disagrees with actual 472.00
        "subtotal": "5,664,000.00",
        "vat_amount": "849,600.00",
        "vat_percent": "15%",
        "total": "6,513,600.00",
        "tin": "101458013391",
        "bin": "000170141-0101",
        "advance_percent": "10%",
        "payment_terms_text": "within 45 days",
        "delivery_terms_text": "within 24 days",
        "late_penalty_text": "1% of order value",
        "validity_text": "45 days",
    }
    llm = FakeLLMClient(canned)
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=llm)
    cfg = {"configurable": {"thread_id": "test_disagree"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "extractor_mode": "both",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    assert any("Disagreement on 'unit_price'" in log for log in state.values["audit_log"])


def test_no_uncertain_field_can_ever_lead_to_approve() -> None:
    """Exhaustively verify that if ANY decision field is UNCERTAIN, the verdict can NEVER be APPROVE."""
    decision_fields = [
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
    ]

    config = RulesConfig()

    # For item_code, quantity, and unit_price, matching and comparison rules run in compare.py
    for field_name in decision_fields:
        if field_name in {"item_code", "quantity", "unit_price"}:
            clean_kwargs: dict[str, Any] = {
                "supplier_name": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="Padma", evidence_quote="Padma"
                ),
                "quotation_no": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="QT-1", evidence_quote="QT-1"
                ),
                "quote_date": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="2026-10-21", evidence_quote="2026-10-21"
                ),
                "reference_pr": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="PR-2026-114", evidence_quote="PR-2026-114"
                ),
                "line_item_count": 1,
                "item_code": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="A", evidence_quote="A"
                ),
                "description": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="Cotton", evidence_quote="Cotton"
                ),
                "quantity": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND, value=Decimal("12000"), evidence_quote="12,000"
                ),
                "unit": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="metre", evidence_quote="metre"
                ),
                "unit_price": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND, value=Decimal("472.00"), evidence_quote="472.00"
                ),
                "subtotal": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND,
                    value=Decimal("5664000.00"),
                    evidence_quote="5,664,000.00",
                ),
                "vat_amount": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND,
                    value=Decimal("849600.00"),
                    evidence_quote="849,600.00",
                ),
                "vat_percent": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND, value=Decimal("15.0"), evidence_quote="15%"
                ),
                "vat_shown_separately": FieldEvidence[bool](
                    status=FieldStatus.DERIVED, value=True, evidence_quote="15%"
                ),
                "total": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND,
                    value=Decimal("6513600.00"),
                    evidence_quote="6,513,600.00",
                ),
                "tin": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="101458013391", evidence_quote="101458013391"
                ),
                "bin": FieldEvidence[str](
                    status=FieldStatus.FOUND,
                    value="000170141-0101",
                    evidence_quote="000170141-0101",
                ),
                "advance_percent": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND, value=Decimal("10.0"), evidence_quote="10%"
                ),
                "payment_terms_text": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="45 days", evidence_quote="45 days"
                ),
                "payment_days": FieldEvidence[int](
                    status=FieldStatus.FOUND, value=45, evidence_quote="45 days"
                ),
                "delivery_terms_text": FieldEvidence[str](
                    status=FieldStatus.FOUND, value="24 days", evidence_quote="24 days"
                ),
                "delivery_days": FieldEvidence[int](
                    status=FieldStatus.FOUND, value=24, evidence_quote="24 days"
                ),
                "late_penalty_percent_per_week": FieldEvidence[Decimal](
                    status=FieldStatus.FOUND, value=Decimal("1.0"), evidence_quote="1%"
                ),
                "late_penalty_clause_present": FieldEvidence[bool](
                    status=FieldStatus.DERIVED, value=True, evidence_quote="Delay"
                ),
                "late_penalty_specifies_order_value": FieldEvidence[bool](
                    status=FieldStatus.DERIVED, value=True, evidence_quote="order value"
                ),
                "validity_days": FieldEvidence[int](
                    status=FieldStatus.FOUND, value=45, evidence_quote="45 days"
                ),
            }
            clean_kwargs[field_name] = FieldEvidence[Any](
                status=FieldStatus.UNCERTAIN,
                value=None,
                evidence_quote="N/A",
                absence_note="Uncertain value",
            )
            quote = ExtractedQuote(**clean_kwargs)
            from supplier_check.compare import run_pr_comparisons
            from supplier_check.models import PurchaseRequestItem

            pr_item = PurchaseRequestItem(
                pr_number="PR-2026-114",
                item_code="A",
                description="Cotton",
                unit="metre",
                quantity_requested=Decimal("12000"),
                max_unit_price=Decimal("480.00"),
            )
            _, comp_res = run_pr_comparisons(quote, [pr_item], config)
            pol_res = run_all_policy_rules(quote, config)
            decision = make_decision(comp_res + pol_res)
            assert decision.verdict != Verdict.APPROVE
            continue
        # Build baseline clean quote
        clean_kwargs: dict[str, Any] = {
            "supplier_name": FieldEvidence[str](
                status=FieldStatus.FOUND, value="Padma", evidence_quote="Padma"
            ),
            "quotation_no": FieldEvidence[str](
                status=FieldStatus.FOUND, value="QT-1", evidence_quote="QT-1"
            ),
            "quote_date": FieldEvidence[str](
                status=FieldStatus.FOUND, value="2026-10-21", evidence_quote="2026-10-21"
            ),
            "reference_pr": FieldEvidence[str](
                status=FieldStatus.FOUND, value="PR-2026-114", evidence_quote="PR-2026-114"
            ),
            "line_item_count": 1,
            "item_code": FieldEvidence[str](
                status=FieldStatus.FOUND, value="A", evidence_quote="A"
            ),
            "description": FieldEvidence[str](
                status=FieldStatus.FOUND, value="Cotton", evidence_quote="Cotton"
            ),
            "quantity": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("12000"), evidence_quote="12,000"
            ),
            "unit": FieldEvidence[str](
                status=FieldStatus.FOUND, value="metre", evidence_quote="metre"
            ),
            "unit_price": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("472.00"), evidence_quote="472.00"
            ),
            "subtotal": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("5664000.00"), evidence_quote="5,664,000.00"
            ),
            "vat_amount": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("849600.00"), evidence_quote="849,600.00"
            ),
            "vat_percent": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("15.0"), evidence_quote="15%"
            ),
            "vat_shown_separately": FieldEvidence[bool](
                status=FieldStatus.DERIVED, value=True, evidence_quote="15%"
            ),
            "total": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("6513600.00"), evidence_quote="6,513,600.00"
            ),
            "tin": FieldEvidence[str](
                status=FieldStatus.FOUND, value="101458013391", evidence_quote="101458013391"
            ),
            "bin": FieldEvidence[str](
                status=FieldStatus.FOUND, value="000170141-0101", evidence_quote="000170141-0101"
            ),
            "advance_percent": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("10.0"), evidence_quote="10%"
            ),
            "payment_terms_text": FieldEvidence[str](
                status=FieldStatus.FOUND, value="45 days", evidence_quote="45 days"
            ),
            "payment_days": FieldEvidence[int](
                status=FieldStatus.FOUND, value=45, evidence_quote="45 days"
            ),
            "delivery_terms_text": FieldEvidence[str](
                status=FieldStatus.FOUND, value="24 days", evidence_quote="24 days"
            ),
            "delivery_days": FieldEvidence[int](
                status=FieldStatus.FOUND, value=24, evidence_quote="24 days"
            ),
            "late_penalty_percent_per_week": FieldEvidence[Decimal](
                status=FieldStatus.FOUND, value=Decimal("1.0"), evidence_quote="1%"
            ),
            "late_penalty_clause_present": FieldEvidence[bool](
                status=FieldStatus.DERIVED, value=True, evidence_quote="Delay"
            ),
            "late_penalty_specifies_order_value": FieldEvidence[bool](
                status=FieldStatus.DERIVED, value=True, evidence_quote="order value"
            ),
            "validity_days": FieldEvidence[int](
                status=FieldStatus.FOUND, value=45, evidence_quote="45 days"
            ),
        }

        # Set the single field to UNCERTAIN
        clean_kwargs[field_name] = FieldEvidence[Any](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote="N/A",
            absence_note="Uncertain value",
        )
        quote = ExtractedQuote(**clean_kwargs)

        rule_results = run_all_policy_rules(quote, config)
        decision = make_decision(rule_results)

        assert decision.verdict != Verdict.APPROVE, (
            f"Field '{field_name}' marked UNCERTAIN must NEVER produce APPROVE. Got: {decision.verdict}"
        )
