"""Live check running LangGraph with EXTRACTOR=both and RUN_LIVE_LLM=1 across all 10 sample packs."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from pypdf import PdfReader

# Load credentials from .env
load_dotenv()

from supplier_check.cli import _write_markdown_results  # noqa: E402
from supplier_check.extract_fallback import extract_fallback_from_text  # noqa: E402
from supplier_check.graph import build_supplier_checker_graph  # noqa: E402
from supplier_check.llm_client import GeminiClient, map_flat_to_extracted_quote  # noqa: E402
from supplier_check.llm_schema import FlatLLMQuote  # noqa: E402
from supplier_check.reconcile import DECISION_FIELDS, values_match  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_live_check(pack_stems: list[str] | None = None) -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        msg = "GEMINI_API_KEY not found in environment or .env file."
        Path("outputs/live_run_status.md").write_text(
            f"# Live Run Status\n\n**Skipped**: {msg}\n", encoding="utf-8"
        )
        print(msg)
        return

    os.environ["EXTRACTOR"] = "auto"
    if "RUN_LIVE_LLM" in os.environ:
        del os.environ["RUN_LIVE_LLM"]

    golden_path = Path("tests/golden/expected.json")
    expected_verdicts: dict[str, str] = json.loads(golden_path.read_text(encoding="utf-8"))

    all_pdfs = sorted(Path("data").glob("*.pdf"))
    if pack_stems:
        pdf_files = [p for p in all_pdfs if p.stem in pack_stems]
    else:
        pdf_files = all_pdfs

    if not pdf_files:
        print("No matching PDF files found in data/")
        return

    print(f"Starting live Gemini check on {len(pdf_files)} packs (timeout 180s)...")
    start_time = time.time()
    max_timeout = 180.0

    try:
        gemini_client = GeminiClient()
    except Exception as e:
        err_msg = f"Failed to initialize GeminiClient: {e}"
        Path("outputs/live_run_status.md").write_text(
            f"# Live Run Status\n\n**Error**: {err_msg}\n", encoding="utf-8"
        )
        print(err_msg)
        return

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer, llm_client=gemini_client)

    results: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    matches = 0

    try:
        for idx, pdf in enumerate(pdf_files, 1):
            elapsed = time.time() - start_time
            if elapsed > max_timeout:
                raise TimeoutError(f"Live run exceeded {max_timeout}s timeout at pack {pdf.name}")

            thread_id = f"live_{pdf.stem}"
            cfg = {"configurable": {"thread_id": thread_id}}

            # Read raw text for extractor comparison table
            reader = PdfReader(str(pdf))
            raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)

            # Run full graph
            print(f"[{idx}/{len(pdf_files)}] Running {pdf.name} through live LangGraph...")
            app.invoke(
                {"pdf_path": str(pdf), "extractor_mode": "auto"},
                config=cfg,
            )
            state = app.get_state(cfg)
            dec = state.values.get("decision")
            actual_verdict = dec.verdict.value if dec else "UNKNOWN"
            exp_verdict = expected_verdicts.get(pdf.stem, "UNKNOWN")

            if actual_verdict == exp_verdict:
                matches += 1

            # Run side-by-side field inspection for extraction_llm_vs_fallback_live.md
            try:
                raw_dict = gemini_client.extract(raw_text)
                flat = FlatLLMQuote.model_validate(raw_dict)
                llm_q = map_flat_to_extracted_quote(flat, raw_text)
            except Exception as e:
                logger.warning(f"Live LLM direct extract error on {pdf.name}: {e}")
                llm_q = None

            fb_q = extract_fallback_from_text(raw_text)

            comparison_rows.append(
                {
                    "pack": pdf.stem,
                    "llm_quote": llm_q,
                    "fb_quote": fb_q,
                }
            )

            rep = state.values.get("report") or {}
            dec = state.values.get("decision")
            system_verdict = rep.get("system_verdict") or (
                dec.display_verdict if dec else "Needs a person to check"
            )
            final_verdict = rep.get("final_verdict") or system_verdict
            supplier = rep.get("supplier") or "Unknown"

            trig_rules = rep.get("triggered_rules")
            if trig_rules is None and dec:
                trig_rules = [
                    {
                        "rule_id": r.rule_id,
                        "severity": r.severity.value,
                        "message": r.message,
                        "evidence_quote": r.evidence_quote,
                    }
                    for r in dec.triggered_rules
                ]
            trig_rules = trig_rules or []
            reasons_list = [f"{t.get('rule_id')}: {t.get('message')}" for t in trig_rules]

            results.append(
                {
                    "pdf": str(pdf),
                    "pack": pdf.stem,
                    "supplier": supplier,
                    "item": rep.get("item", "Unknown"),
                    "system_verdict": system_verdict,
                    "final_verdict": final_verdict,
                    "reviewer_note": rep.get("reviewer_note"),
                    "extractor_used": rep.get(
                        "extractor_used", state.values.get("extractor_used", "auto")
                    ),
                    "reasons": reasons_list,
                    "triggered_rules": trig_rules,
                    "audit_log": rep.get("audit_log", state.values.get("audit_log", [])),
                }
            )

            # Small delay to respect free-tier rate limits
            time.sleep(1.0)

        # Write outputs/results_live.md
        live_res_md = Path("outputs/results_live.md")
        _write_markdown_results(results, live_res_md)
        print(f"Results saved to: {live_res_md}")

        # Write outputs/extraction_llm_vs_fallback_live.md
        _write_comparison_report(
            comparison_rows, Path("outputs/extraction_llm_vs_fallback_live.md")
        )

        status_content = (
            f"# Live Run Status\n\n"
            f"- **Status**: SUCCESS\n"
            f"- **Verdict Match Count**: {matches}/{len(pdf_files)} matching expected golden verdicts.\n"
            f"- **Execution Time**: {time.time() - start_time:.2f}s\n"
        )
        Path("outputs/live_run_status.md").write_text(status_content, encoding="utf-8")
        print(status_content)

    except Exception as e:
        err_msg = f"Live run encountered error: {e}"
        logger.error(err_msg, exc_info=True)
        Path("outputs/live_run_status.md").write_text(
            f"# Live Run Status\n\n**FAILED**: {err_msg}\n", encoding="utf-8"
        )
        print(err_msg)


def _write_comparison_report(rows: list[dict[str, Any]], out_path: Path) -> None:
    lines = [
        "# Live Extraction Comparison: Gemini LLM vs Deterministic Fallback",
        "",
        "| Pack | Field | LLM Status | LLM Value | Fallback Status | Fallback Value | Agree? |",
        "| :--- | :--- | :---: | :--- | :---: | :--- | :---: |",
    ]

    for r in rows:
        pack = r["pack"]
        llm_q = r["llm_quote"]
        fb_q = r["fb_quote"]

        for fld in DECISION_FIELDS:
            if llm_q:
                fe_llm = getattr(llm_q, fld)
                llm_st = fe_llm.status.value
                llm_val = str(fe_llm.value) if fe_llm.value is not None else "None"
            else:
                llm_st = "FAILED"
                llm_val = "N/A"

            fe_fb = getattr(fb_q, fld)
            fb_st = fe_fb.status.value
            fb_val = str(fe_fb.value) if fe_fb.value is not None else "None"

            agree = (
                "Yes"
                if (
                    llm_q
                    and values_match(fe_llm.value, fe_fb.value)
                    and fe_llm.status == fe_fb.status
                )
                else "No"
            )
            lines.append(
                f"| {pack} | `{fld}` | {llm_st} | `{llm_val}` | {fb_st} | `{fb_val}` | **{agree}** |"
            )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Comparison report saved to: {out_path}")


if __name__ == "__main__":
    import sys

    target_packs = sys.argv[1:] if len(sys.argv) > 1 else None
    run_live_check(target_packs)
