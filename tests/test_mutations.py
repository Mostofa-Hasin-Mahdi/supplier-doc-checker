"""Mutation tests for the full LangGraph pipeline.

Takes real supplier pack text, applies synthetic text mutations, and runs through the full graph.
Asserts both the resulting final system verdict and the exact triggered rule IDs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from pypdf import PdfReader

from supplier_check.graph import build_supplier_checker_graph
from supplier_check.models import Verdict


@pytest.fixture(scope="module")
def pack01_text() -> str:
    """Extract baseline clean text from supplier-pack-01.pdf (normally APPROVE)."""
    pdf_path = Path("data/supplier-pack-01.pdf")
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _run_graph_on_mutated_text(text: str, thread_id: str) -> tuple[Verdict, list[str]]:
    """Helper to run the full graph with mutated raw_text."""
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": thread_id}}

    # We provide raw_text and pr_csv_path; ingest node keeps provided raw_text
    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "raw_text": text,
            "extractor_mode": "fallback",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    dec = state.values.get("decision")
    assert dec is not None, "Pipeline must produce a decision"
    triggered_ids = [r.rule_id for r in dec.triggered_rules]
    return dec.verdict, triggered_ids


def test_clean_pack_mutation_stays_approve(pack01_text: str) -> None:
    """Changing supplier name only must stay APPROVE with no triggered rules."""
    mutated = pack01_text.replace("Padma Textile Mills Ltd", "Brahmaputra Spinning Mills Ltd")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_clean")
    assert verdict == Verdict.APPROVE
    assert len(triggered) == 0


def test_mutation_price_plus_10_percent(pack01_text: str) -> None:
    """Price +10% (e.g. 472.00 -> 520.00 vs max 480.00, +8.3% over max) => REJECT RULE_REJ_01_PRICE_MAX."""
    # Max budget for Item A is 480.00; 480 * 1.03 = 494.40
    # 528.00 is 10% above max 480.00
    mutated = pack01_text.replace("472.00", "528.00")
    mutated = mutated.replace("5,664,000.00", "6,336,000.00")
    mutated = mutated.replace("849,600.00", "950,400.00")
    mutated = mutated.replace("6,513,600.00", "7,286,400.00")

    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_price_high")
    assert verdict == Verdict.REJECT
    assert "RULE_REJ_01_PRICE_MAX" in triggered


def test_mutation_price_exact_3_percent_over(pack01_text: str) -> None:
    """Price at exactly 3% over max (480.00 * 1.03 = 494.40) => REVIEW RULE_REV_01_PRICE_TOLERANCE."""
    mutated = pack01_text.replace("472.00", "494.40")
    # Update amounts to maintain math consistency so math rules pass
    mutated = mutated.replace("5,664,000.00", "5,932,800.00")
    mutated = mutated.replace("849,600.00", "889,920.00")
    mutated = mutated.replace("6,513,600.00", "6,822,720.00")

    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_price_3pct")
    assert verdict == Verdict.NEEDS_REVIEW
    assert "RULE_REV_01_PRICE_TOLERANCE" in triggered


def test_mutation_delete_tin_line(pack01_text: str) -> None:
    """Deleting the TIN line => REJECT RULE_REJ_05_TAX_ID."""
    mutated = pack01_text.replace("Supplier TIN: 101458013391 BIN: 000170141-0101", "")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_no_tin")
    assert verdict == Verdict.REJECT
    assert "RULE_REJ_05_TAX_ID" in triggered


def test_mutation_delivery_46_days(pack01_text: str) -> None:
    """Delivery promised in 46 days (>45 days) => REJECT RULE_REJ_06_DELIVERY_MAX."""
    mutated = pack01_text.replace("Delivery within 24 days", "Delivery within 46 days")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_del_46")
    assert verdict == Verdict.REJECT
    assert "RULE_REJ_06_DELIVERY_MAX" in triggered


def test_mutation_delivery_40_days(pack01_text: str) -> None:
    """Delivery in 40 days (31..45 days) => REVIEW RULE_REV_04_DELIVERY_RANGE."""
    mutated = pack01_text.replace("Delivery within 24 days", "Delivery within 40 days")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_del_40")
    assert verdict == Verdict.NEEDS_REVIEW
    assert "RULE_REV_04_DELIVERY_RANGE" in triggered


def test_mutation_remove_penalty_clause(pack01_text: str) -> None:
    """Removing penalty clause => REJECT RULE_REJ_03_NO_PENALTY."""
    mutated = re.sub(r"3\.\s*Delay\.[^\n]+\n?", "", pack01_text)
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_no_penalty")
    assert verdict == Verdict.REJECT
    assert "RULE_REJ_03_NO_PENALTY" in triggered


def test_mutation_advance_21_percent(pack01_text: str) -> None:
    """Advance payment 21% (>20%) => REJECT RULE_REJ_02_ADVANCE_MAX."""
    mutated = pack01_text.replace("10% advance payable", "21% advance payable")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_adv_21")
    assert verdict == Verdict.REJECT
    assert "RULE_REJ_02_ADVANCE_MAX" in triggered


def test_mutation_vat_amount_wrong(pack01_text: str) -> None:
    """VAT amount wrong (849,600.00 -> 900,000.00) => REVIEW RULE_REV_07_MATH_VAT."""
    mutated = pack01_text.replace("849,600.00", "900,000.00")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_vat_wrong")
    assert verdict == Verdict.NEEDS_REVIEW
    assert "RULE_REV_07_MATH_VAT" in triggered


def test_mutation_total_wrong(pack01_text: str) -> None:
    """Total wrong (6,513,600.00 -> 7,000,000.00) => REVIEW RULE_REV_08_MATH_TOTAL."""
    mutated = pack01_text.replace("6,513,600.00", "7,000,000.00")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_total_wrong")
    assert verdict == Verdict.NEEDS_REVIEW
    assert "RULE_REV_08_MATH_TOTAL" in triggered


def test_mutation_validity_29_days(pack01_text: str) -> None:
    """Validity 29 days (<30 days) => REVIEW RULE_REV_09_VALIDITY."""
    mutated = pack01_text.replace("valid for 45 days", "valid for 29 days")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_val_29")
    assert verdict == Verdict.NEEDS_REVIEW
    assert "RULE_REV_09_VALIDITY" in triggered


def test_mutation_quantity_plus_6_percent(pack01_text: str) -> None:
    """Quantity +6% (12,000 * 1.06 = 12,720 vs requested 12,000) => REVIEW RULE_REV_02_QTY_TOLERANCE."""
    mutated = pack01_text.replace("12,000", "12,720")
    # Adjust amounts to avoid arithmetic failures
    mutated = mutated.replace("5,664,000.00", "6,003,840.00")
    mutated = mutated.replace("849,600.00", "900,576.00")
    mutated = mutated.replace("6,513,600.00", "6,904,416.00")

    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_qty_6pct")
    assert verdict == Verdict.NEEDS_REVIEW
    assert "RULE_REV_02_QTY_TOLERANCE" in triggered


def test_mutation_payment_90_days(pack01_text: str) -> None:
    """Payment 90 days (>60 days window) => REVIEW RULE_REV_03_PAYMENT_TERMS."""
    mutated = pack01_text.replace("within 45 days after delivery", "within 90 days after delivery")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_pay_90")
    assert verdict == Verdict.NEEDS_REVIEW
    assert "RULE_REV_03_PAYMENT_TERMS" in triggered


def test_mutation_penalty_rate_point_4_percent(pack01_text: str) -> None:
    """Penalty rate 0.4% per week (<0.5%) => REJECT RULE_REJ_04_PENALTY_RATE."""
    mutated = pack01_text.replace("1% of order value", "0.4% of order value")
    verdict, triggered = _run_graph_on_mutated_text(mutated, "mut_pen_04")
    assert verdict == Verdict.REJECT
    assert "RULE_REJ_04_PENALTY_RATE" in triggered

