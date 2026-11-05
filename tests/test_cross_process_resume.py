"""Test resume of queued cases across distinct processes and SQLite database persistence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cross_process_resume_pack_09(tmp_path: Path) -> None:
    """Run check-all to queue packs, then in a separate python process review pack 09 with Approve and a note.

    Assert that the final report preserves system_verdict='Needs a person to check' and final_verdict='Approve'.
    """
    db_file = tmp_path / "test_proc.sqlite"
    out_dir = tmp_path / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Run check-all using CLI in a subprocess
    cmd_check_all = [
        sys.executable,
        "-m",
        "supplier_check.cli",
        "check-all",
        "data",
        "--out",
        str(out_dir),
        "--mode",
        "fallback",
        "--db",
        str(db_file),
    ]
    proc1 = subprocess.run(cmd_check_all, capture_output=True, text=True, timeout=30)
    assert proc1.returncode == 0, f"check-all failed: {proc1.stderr}"

    # Verify supplier-pack-09 was queued in results.json
    res_json_path = out_dir / "results.json"
    assert res_json_path.exists()
    data = json.loads(res_json_path.read_text(encoding="utf-8"))
    p09_entry = next((row for row in data if row.get("pack") == "supplier-pack-09"), None)
    assert p09_entry is not None
    assert p09_entry["system_verdict"] == "Needs a person to check"
    assert p09_entry["final_verdict"] == "Pending Review"

    # Step 2: In a separate subprocess, resume pack 09 directly using the Python CLI API
    # Since review with arguments prompts for input, we invoke the graph resume via a one-line script
    # exactly as the CLI review command does, pointing to the same sqlite file
    resume_script = f"""
import sys
from pathlib import Path
from supplier_check.cli import _get_checkpointer, _write_markdown_results
from supplier_check.graph import build_supplier_checker_graph
from langgraph.types import Command
import json

db_path = Path(r'{db_file}')
out_path = Path(r'{out_dir}')
thread_id = 'supplier-pack-09'

checkpointer = _get_checkpointer(db_path)
graph_app = build_supplier_checker_graph(checkpointer=checkpointer)
config = {{'configurable': {{'thread_id': thread_id}}}}

resumed = graph_app.invoke(
    Command(resume={{'decision': 'Approve', 'reviewer_note': 'Approved with management waiver'}}),
    config=config,
)
report = resumed.get('report')

results_file = out_path / 'results.json'
data = json.loads(results_file.read_text(encoding='utf-8'))
for row in data:
    if row.get('pack') == thread_id:
        row['final_verdict'] = report.get('final_verdict')
        row['reviewer_note'] = report.get('reviewer_note')
results_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
_write_markdown_results(data, out_path / 'results.md')
"""
    proc2 = subprocess.run(
        [sys.executable, "-c", resume_script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc2.returncode == 0, f"resume script failed: {proc2.stderr}"

    # Step 3: Inspect updated results.json and results.md
    updated_data = json.loads(res_json_path.read_text(encoding="utf-8"))
    updated_p09 = next((row for row in updated_data if row.get("pack") == "supplier-pack-09"), None)
    assert updated_p09 is not None
    assert updated_p09["system_verdict"] == "Needs a person to check"
    assert updated_p09["final_verdict"] == "Approve"
    assert updated_p09["reviewer_note"] == "Approved with management waiver"

    # Inspect results.md to confirm side-by-side display
    results_md = (out_dir / "results.md").read_text(encoding="utf-8")
    assert "supplier-pack-09" in results_md
    assert "**Needs a person to check**" in results_md
    assert "**Approve**" in results_md
