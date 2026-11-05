"""Evaluation script for supplier-document-checker pipeline.

Runs the full graph on the 10 sample packs (EXTRACTOR=fallback), compares results against
tests/golden/expected.json, prints the evaluation summary, and writes outputs/eval_report.md.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from supplier_check.graph import build_supplier_checker_graph
from supplier_check.models import Verdict


def run_evaluation() -> dict[str, Any]:
    golden_path = Path("tests/golden/expected.json")
    if not golden_path.exists():
        raise FileNotFoundError(f"Golden expectations file not found: {golden_path}")

    expected_verdicts: dict[str, str] = json.loads(golden_path.read_text(encoding="utf-8"))

    checkpointer = MemorySaver()
    app = build_supplier_checker_graph(checkpointer=checkpointer)

    # Expected triggered rules per pack from pipeline design specification
    expected_rules_map: dict[str, list[str]] = {
        "supplier-pack-01": [],
        "supplier-pack-02": [],
        "supplier-pack-03": ["RULE_REJ_01_PRICE_MAX"],
        "supplier-pack-04": ["RULE_REV_01_PRICE_TOLERANCE"],
        "supplier-pack-05": ["RULE_REJ_02_ADVANCE_MAX"],
        "supplier-pack-06": ["RULE_REJ_03_NO_PENALTY"],
        "supplier-pack-07": ["RULE_REV_02_QTY_TOLERANCE"],
        "supplier-pack-08": ["RULE_REJ_05_TAX_ID", "RULE_REV_10_PENALTY_AMBIGUOUS"],
        "supplier-pack-09": ["RULE_REV_03_PAYMENT_TERMS", "RULE_REV_06_MATH_SUBTOTAL"],
        "supplier-pack-10": ["RULE_REJ_06_DELIVERY_MAX", "RULE_REV_05_VAT_PRESENTATION"],
    }

    rows: list[dict[str, Any]] = []
    correct_count = 0
    confusion_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for pack_stem, exp_verdict in expected_verdicts.items():
        pdf_path = f"data/{pack_stem}.pdf"
        cfg = {"configurable": {"thread_id": f"eval_{pack_stem}"}}

        app.invoke(
            {"pdf_path": pdf_path, "extractor_mode": "fallback"},
            config=cfg,
        )

        state = app.get_state(cfg)
        dec = state.values.get("decision")
        actual_verdict = dec.verdict.value if dec else "UNKNOWN"

        match = actual_verdict == exp_verdict
        if match:
            correct_count += 1

        confusion_matrix[exp_verdict][actual_verdict] += 1

        # Check triggered rules
        actual_triggered_ids = [r.rule_id for r in (dec.triggered_rules if dec else [])]
        expected_triggered_ids = expected_rules_map.get(pack_stem, [])
        rules_present = all(rid in actual_triggered_ids for rid in expected_triggered_ids)

        # Check if matched by error path rather than rule verification
        g_errors = state.values.get("grounding_errors") or []
        is_error_match = False
        if match and exp_verdict == "NEEDS_REVIEW":
            # If the verdict is NEEDS_REVIEW, did it match because of grounding/node errors instead of expected rules?
            if g_errors or not rules_present:
                is_error_match = True

        rows.append(
            {
                "pack": pack_stem,
                "expected": exp_verdict,
                "actual": actual_verdict,
                "match": match,
                "expected_rules": expected_triggered_ids,
                "actual_rules": actual_triggered_ids,
                "rules_match": rules_present,
                "error_match": is_error_match,
            }
        )

    eval_data = {
        "total": len(expected_verdicts),
        "correct": correct_count,
        "rows": rows,
        "confusion_matrix": confusion_matrix,
    }

    _write_report(eval_data, Path("outputs/eval_report.md"))
    return eval_data


def _write_report(eval_data: dict[str, Any], out_path: Path) -> None:
    total = eval_data["total"]
    correct = eval_data["correct"]
    rows = eval_data["rows"]
    matrix = eval_data["confusion_matrix"]

    lines = [
        "# Evaluation Report: Supplier Document Checker Pipeline",
        "",
        f"**Accuracy:** {correct}/{total} ({correct / total * 100:.1f}%) verdicts matching expected golden dataset.",
        "",
        "## Pack Verdict Evaluation",
        "",
        "| Pack | Expected Verdict | Actual Verdict | Verdict Match | Expected Rules Present | Actual Triggered Rules |",
        "| :--- | :--- | :--- | :---: | :---: | :--- |",
    ]

    for r in rows:
        if r.get("error_match"):
            v_match = "matched by error path, not verified"
        else:
            v_match = "PASS" if r["match"] else "FAIL"
        r_match = "Yes" if r["rules_match"] else "No"
        act_rules_str = ", ".join(r["actual_rules"]) if r["actual_rules"] else "*(none)*"
        lines.append(
            f"| {r['pack']} | `{r['expected']}` | `{r['actual']}` | **{v_match}** | {r_match} | {act_rules_str} |"
        )

    lines.extend(
        [
            "",
            "## Confusion Matrix",
            "",
            "| Expected \\ Actual | APPROVE | REJECT | NEEDS_REVIEW |",
            "| :--- | :---: | :---: | :---: |",
        ]
    )

    all_verdicts = [Verdict.APPROVE.value, Verdict.REJECT.value, Verdict.NEEDS_REVIEW.value]
    for exp in all_verdicts:
        counts = [str(matrix[exp][act]) for act in all_verdicts]
        lines.append(f"| **{exp}** | " + " | ".join(counts) + " |")

    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    result = run_evaluation()
    print(f"Evaluation complete: {result['correct']}/{result['total']} correct.")
    print("Report written to outputs/eval_report.md")
