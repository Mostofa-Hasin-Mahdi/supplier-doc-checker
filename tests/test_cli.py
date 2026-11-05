"""CLI integration tests testing input validation and options."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_missing_pdf_error() -> None:
    """CLI prints clean error message without traceback for missing PDF."""
    res = subprocess.run(
        [sys.executable, "-m", "supplier_check.cli", "check", "nonexistent_file.pdf"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "Error:" in res.stdout
    assert "PDF file not found" in res.stdout
    assert "Traceback" not in res.stderr
    assert "Traceback" not in res.stdout


def test_cli_non_pdf_file_error(tmp_path: Path) -> None:
    """CLI prints clean error message when file is not a PDF."""
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("Not a pdf", encoding="utf-8")
    res = subprocess.run(
        [sys.executable, "-m", "supplier_check.cli", "check", str(txt_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "Input file is not a PDF" in res.stdout
    assert "Traceback" not in res.stderr
    assert "Traceback" not in res.stdout


def test_cli_corrupt_pdf_error(tmp_path: Path) -> None:
    """CLI prints clean error message when PDF is corrupt/unreadable."""
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4 unreadable stream")
    res = subprocess.run(
        [sys.executable, "-m", "supplier_check.cli", "check", str(corrupt_pdf)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "PDF is corrupt or unreadable" in res.stdout
    assert "Traceback" not in res.stdout


def test_cli_missing_pr_columns_error(tmp_path: Path) -> None:
    """CLI prints clean error message when PR CSV is missing required columns."""
    bad_pr = tmp_path / "bad_pr.csv"
    bad_pr.write_text("ColA,ColB\n1,2\n", encoding="utf-8")
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "supplier_check.cli",
            "check",
            "data/supplier-pack-01.pdf",
            "--pr",
            str(bad_pr),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    collapsed = " ".join(res.stdout.split())
    assert "missing required columns" in collapsed
    assert "Traceback" not in res.stderr
    assert "Traceback" not in res.stdout


def test_cli_check_json_output() -> None:
    """CLI check with --json outputs valid parseable JSON."""
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "supplier_check.cli",
            "check",
            "data/supplier-pack-01.pdf",
            "--mode",
            "fallback",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["final_verdict"] == "Approve"
    assert data["supplier"] == "Padma Textile Mills Ltd"


def test_cli_check_all_with_custom_pr_and_rules(tmp_path: Path) -> None:
    """check-all respects --pr and --rules options and validates inputs."""
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "supplier_check.cli",
            "check-all",
            "data",
            "--pr",
            "data/purchase-request.csv",
            "--rules",
            "config/rules.yaml",
            "--mode",
            "fallback",
            "--out",
            str(tmp_path / "custom_out"),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "Supplier Verification Summary" in res.stdout
