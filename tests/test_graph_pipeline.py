"""Phase 5 Integration and Graph Pipeline Tests."""

import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from supplier_check.graph import build_supplier_checker_graph
from supplier_check.llm_client import FakeLLMClient
from supplier_check.models import Verdict


def test_graph_integration_all_10_packs_fallback() -> None:
    """Run all 10 sample packs through LangGraph with EXTRACTOR=fallback and verify golden verdicts."""
    golden_path = Path("tests/golden/expected.json")
    expected_verdicts: dict[str, str] = json.loads(golden_path.read_text(encoding="utf-8"))

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)

    for pack_stem, expected in expected_verdicts.items():
        pdf_path = f"data/{pack_stem}.pdf"
        cfg = {"configurable": {"thread_id": pack_stem}}

        app.invoke(
            {"pdf_path": pdf_path, "extractor_mode": "fallback"},
            config=cfg,
        )

        state = app.get_state(cfg)
        if expected == "NEEDS_REVIEW":
            assert state.next and "human_review" in state.next
            assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
        elif expected == "APPROVE":
            assert state.values["decision"].verdict == Verdict.APPROVE
            assert state.values["report"]["system_verdict"] == "Approve"
        elif expected == "REJECT":
            assert state.values["decision"].verdict == Verdict.REJECT
            assert state.values["report"]["system_verdict"] == "Reject"


def test_human_pause_and_resume_pack_09() -> None:
    """Pack 09 pauses, resumes with Approve + note, and report records both original and final verdicts."""
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "test_pack_09_resume"}}

    # Initial invoke -> pauses at human_review
    app.invoke(
        {"pdf_path": "data/supplier-pack-09.pdf", "extractor_mode": "fallback"},
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.next and "human_review" in state.next
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW

    # Resume with Approve and reviewer note
    resumed = app.invoke(
        Command(
            resume={
                "decision": "Approve",
                "reviewer_note": "Special waiver granted for payment terms",
            }
        ),
        config=cfg,
    )
    report = resumed.get("report")
    assert report is not None
    assert report["system_verdict"] == "Needs a person to check"
    assert report["final_verdict"] == "Approve"
    assert report["reviewer_note"] == "Special waiver granted for payment terms"


def test_failure_nonexistent_pdf() -> None:
    """Nonexistent PDF routes safely to Needs a person to check with explanation in audit log."""
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "missing_pdf"}}

    app.invoke(
        {"pdf_path": "data/nonexistent_file.pdf", "extractor_mode": "fallback"},
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.next and "human_review" in state.next
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    assert any("does not exist" in log for log in state.values["audit_log"])


def test_failure_empty_pdf_text(tmp_path: Path) -> None:
    """Empty PDF routes to Needs a person to check without crashing."""
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "empty_pdf"}}

    app.invoke(
        {"pdf_path": str(empty_file), "extractor_mode": "fallback"},
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.next and "human_review" in state.next
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW


def test_failure_llm_client_raises_exception() -> None:
    """An LLM client that raises an exception logs error, falls back to fallback, and continues."""

    class RaisingLLMClient(FakeLLMClient):
        def extract(self, document_text: str) -> dict:
            raise RuntimeError("API quota exhausted or network error")

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=RaisingLLMClient({}))
    cfg = {"configurable": {"thread_id": "raising_llm"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "extractor_mode": "both",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    # Pack 01 with fallback succeeds and approves
    assert state.values["decision"].verdict == Verdict.APPROVE
    assert any("LLM failed:" in log and "fallback used" in log for log in state.values["audit_log"])
    assert state.values["extractor_used"] == "fallback only (LLM failed)"


def test_failure_llm_client_invalid_json() -> None:
    """An LLM client returning invalid schema/json falls back to fallback extractor."""
    bad_json_client = FakeLLMClient("not valid json at all")

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=bad_json_client)
    cfg = {"configurable": {"thread_id": "invalid_json_llm"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "extractor_mode": "llm",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.APPROVE
    assert any("LLM failed:" in log and "fallback used" in log for log in state.values["audit_log"])
    assert state.values["extractor_used"] == "fallback only (LLM failed)"


def test_failure_llm_disagrees_with_fallback_produces_uncertain_and_review() -> None:
    """When LLM disagrees with fallback on decision field (e.g. price), field becomes UNCERTAIN => REVIEW."""
    canned_mismatch: dict[str, Any] = {
        "supplier_name": "Padma Textile Mills Ltd",
        "quotation_no": "QT-2026-0881",
        "quote_date": "2026-10-25",
        "reference_pr": "PR-2026-114",
        "item_code": "A",
        "description": "Cotton twill fabric, 280 gsm",
        "quantity": "12,000",
        "unit": "metre",
        "unit_price": "999.00",  # Deliberate disagreement: Pack 01 is 472.00
        "subtotal": "5,664,000.00",
        "vat_amount": "849,600.00",
        "vat_percent": "15%",
        "total": "6,513,600.00",
        "tin": "101458013391",
        "bin": "000170141-0101",
        "advance_percent": "0%",
        "payment_terms_text": "30 days net",
        "delivery_terms_text": "24 days",
        "late_penalty_text": "0.5% per week",
        "validity_text": "45 days",
    }
    mismatch_client = FakeLLMClient(canned_mismatch)

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=mismatch_client)
    cfg = {"configurable": {"thread_id": "disagreement_llm"}}

    app.invoke(
        {
            "pdf_path": "data/supplier-pack-01.pdf",
            "extractor_mode": "both",
        },
        config=cfg,
    )
    state = app.get_state(cfg)
    assert state.next and "human_review" in state.next
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW
    assert any("Disagreement on 'unit_price'" in log for log in state.values["audit_log"])


def test_no_src_code_references_golden_or_pack_numbers() -> None:
    """Assert that nothing in src/ reads expected.json or branches on pack names/supplier names."""
    src_dir = Path("src")
    forbidden_terms = [
        "expected.json",
        "golden",
        "supplier-pack-",
        "Padma Textile",
        "Surma Packaging",
        "Karnafuli",
    ]

    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"Forbidden term '{term}' found in {py_file}"


def test_auto_mode_invokes_configured_llm_client() -> None:
    """Assert that default EXTRACTOR=auto invokes the configured LLM client."""
    canned: dict[str, Any] = {
        "supplier_name": "Padma Textile Mills Ltd",
        "quotation_no": "QT-2026-0881",
        "quote_date": "2026-10-25",
        "reference_pr": "PR-2026-114",
        "item_code": "A",
        "description": "Cotton twill fabric, 280 gsm",
        "quantity": "12,000",
        "unit": "metre",
        "unit_price": "472.00",
        "subtotal": "5,664,000.00",
        "vat_amount": "849,600.00",
        "vat_percent": "15%",
        "total": "6,513,600.00",
        "tin": "101458013391",
        "bin": "000170141-0101",
        "advance_percent": "10%",
        "payment_terms_text": "10% advance payable with the purchase order. Balance payable within 45 days",
        "delivery_terms_text": "24 days",
        "late_penalty_text": "Late delivery penalty: 1% of order value for each full week of delay",
        "validity_text": "45 days",
    }
    fake_client = FakeLLMClient(canned)
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=fake_client)
    cfg = {"configurable": {"thread_id": "auto_mode_invokes_llm"}}

    app.invoke(
        {"pdf_path": "data/supplier-pack-01.pdf", "extractor_mode": "auto"},
        config=cfg,
    )

    state = app.get_state(cfg)
    assert len(fake_client.calls) >= 1
    assert state.values["extractor_used"] == "gemini+fallback (agreed)"
    assert state.values["report"]["extractor_used"] == "gemini+fallback (agreed)"
    assert state.values["decision"].verdict == Verdict.APPROVE


def test_auto_mode_does_not_crash_when_llm_raises() -> None:
    """Assert that auto mode does not crash when LLM raises, logs failure, and continues with fallback."""

    class CrashingLLMClient(FakeLLMClient):
        def extract(self, document_text: str) -> dict:
            raise RuntimeError("Network timeout or LLM failure")

    crashing_client = CrashingLLMClient({})
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=crashing_client)
    cfg = {"configurable": {"thread_id": "auto_mode_crashing_llm"}}

    app.invoke(
        {"pdf_path": "data/supplier-pack-01.pdf", "extractor_mode": "auto"},
        config=cfg,
    )

    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.APPROVE
    assert state.values["extractor_used"] == "fallback only (LLM failed)"
    assert state.values["report"]["extractor_used"] == "fallback only (LLM failed)"
    assert any(
        "LLM failed: Network timeout or LLM failure; fallback used" in log
        for log in state.values["audit_log"]
    )


def test_node_failure_produces_explicit_reason_and_error_extractor_label() -> None:
    """When a node encounters an exception, report has a non-empty explicit reason and error Extractor label."""
    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "simulated_node_failure"}}

    # Ingest a non-existent PDF file which triggers ingest exception/failure
    app.invoke(
        {"pdf_path": "data/completely_missing_corrupt_file.pdf", "extractor_mode": "fallback"},
        config=cfg,
    )

    state = app.get_state(cfg)
    assert state.values["decision"].verdict == Verdict.NEEDS_REVIEW

    # Check report payload
    rep = state.values.get("report")
    assert rep is not None
    assert rep["system_verdict"] == "Needs a person to check"
    assert rep["extractor_used"] in {"error: see audit log", "fallback only (no key)", "failed"}
    assert len(rep["triggered_rules"]) > 0
    # Assert non-empty explicit reason
    assert any(
        "Extracted quote is missing" in r["message"] or "extraction failed" in r["message"]
        for r in rep["triggered_rules"]
    )
