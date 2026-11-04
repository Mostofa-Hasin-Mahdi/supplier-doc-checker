"""Command line interface for the supplier document checker."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any

import typer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from rich.console import Console
from rich.table import Table

from supplier_check.graph import build_supplier_checker_graph

app = typer.Typer(
    help="Supplier document checker CLI powered by LangGraph deterministic pipeline.",
    add_completion=False,
)
console = Console()

DEFAULT_DB_PATH = Path("outputs/checkpoints.sqlite")


def _get_checkpointer(db_path: Path = DEFAULT_DB_PATH) -> SqliteSaver:
    """Initialize SQLite checkpointer ensuring directory exists."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)


@app.command()
def check(
    pdf: Annotated[Path, typer.Argument(help="Path to supplier pack PDF file.")],
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for decision if review is needed.")
    ] = False,
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Extractor mode: auto|fallback|llm|both.")
    ] = "auto",
    db: Annotated[
        Path, typer.Option("--db", help="Path to checkpoint database.")
    ] = DEFAULT_DB_PATH,
) -> None:
    """Run verification pipeline on a single supplier pack PDF."""
    if not pdf.exists():
        console.print(f"[bold red]Error:[/] PDF file not found: {pdf}")
        raise typer.Exit(code=1)

    thread_id = pdf.stem
    checkpointer = _get_checkpointer(db)
    graph_app = build_supplier_checker_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        graph_app.invoke(
            {"pdf_path": str(pdf), "extractor_mode": mode},
            config=config,
        )
    except Exception as e:
        console.print(f"[bold red]Pipeline error:[/] {e}")
        raise typer.Exit(code=1) from e

    state = graph_app.get_state(config)

    # Check if interrupted for human review
    if state.next and "human_review" in state.next:
        # State paused at human review
        interrupt_val = state.tasks[0].interrupts[0].value if state.tasks and state.tasks[0].interrupts else {}
        reasons = interrupt_val.get("reasons", [])

        console.print(f"\n[bold yellow]Pack {pdf.name} requires human review.[/]")
        if reasons:
            console.print("[bold]Reasons:[/]")
            for r in reasons:
                console.print(f"  - {r}")

        if not interactive:
            console.print("\n[dim]Run with --interactive or use `review` command to resolve.[/]")
            raise typer.Exit(code=0)

        # Interactive resolution prompt
        console.print("\n[bold cyan]Interactive Reviewer Decision:[/]")
        choice = typer.prompt("Decision (Approve / Reject)", default="Reject")
        choice_clean = "Approve" if choice.strip().casefold() in {"approve", "a"} else "Reject"
        note = typer.prompt("Reviewer note (reason/justification)", default="")

        try:
            resumed = graph_app.invoke(
                Command(resume={"decision": choice_clean, "reviewer_note": note}),
                config=config,
            )
            report = resumed.get("report")
            console.print(f"\n[bold green]Resolved successfully:[/] {choice_clean}")
            if report:
                console.print(f"Final Verdict: [bold]{report.get('final_verdict')}[/]")
        except Exception as e:
            console.print(f"[bold red]Failed to resume human review:[/] {e}")
            raise typer.Exit(code=1) from e

    else:
        # Completed without human intervention
        report = state.values.get("report") or {}
        verdict = report.get("final_verdict", "Unknown")
        color = "green" if verdict == "Approve" else ("red" if verdict == "Reject" else "yellow")
        console.print(f"\nPack: [bold]{pdf.name}[/]")
        console.print(f"Verdict: [{color} bold]{verdict}[/]")
        triggered = report.get("triggered_rules", [])
        if triggered:
            console.print("[bold]Triggered Rules:[/]")
            for tr in triggered:
                console.print(f"  - [{tr.get('severity')}] {tr.get('message')} (Quote: \"{tr.get('evidence_quote')}\")")


@app.command()
def check_all(
    directory: Annotated[
        Path, typer.Argument(help="Directory containing supplier pack PDFs.")
    ] = Path("data"),
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Output directory for reports.")
    ] = Path("outputs"),
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Extractor mode: auto|fallback|llm|both.")
    ] = "auto",
    db: Annotated[
        Path, typer.Option("--db", help="Path to checkpoint database.")
    ] = DEFAULT_DB_PATH,
) -> None:
    """Run verification on all PDFs in a directory, queueing reviews without blocking."""
    if not directory.exists() or not directory.is_dir():
        console.print(f"[bold red]Error:[/] Directory not found: {directory}")
        raise typer.Exit(code=1)

    pdf_files = sorted(directory.glob("*.pdf"))
    if not pdf_files:
        console.print(f"[yellow]No PDF files found in {directory}[/]")
        raise typer.Exit(code=0)

    out.mkdir(parents=True, exist_ok=True)
    checkpointer = _get_checkpointer(db)
    graph_app = build_supplier_checker_graph(checkpointer=checkpointer)

    results: list[dict[str, Any]] = []
    queued_cases: list[str] = []

    console.print(f"Processing {len(pdf_files)} PDF packs from [bold]{directory}[/]...")

    table = Table(title="Supplier Verification Summary")
    table.add_column("Pack", style="cyan")
    table.add_column("Supplier", style="white")
    table.add_column("System Verdict", style="bold")
    table.add_column("Final Verdict", style="bold")
    table.add_column("Extractor", style="dim")
    table.add_column("Triggered Rules / Reasons", style="magenta")

    for pdf in pdf_files:
        thread_id = pdf.stem
        cfg = {"configurable": {"thread_id": thread_id}}
        try:
            graph_app.invoke(
                {"pdf_path": str(pdf), "extractor_mode": mode},
                config=cfg,
            )
        except Exception as e:
            console.print(f"[red]Error on {pdf.name}:[/] {e}")

        state = graph_app.get_state(cfg)

        if state.next and "human_review" in state.next:
            queued_cases.append(thread_id)
            interrupt_val = state.tasks[0].interrupts[0].value if state.tasks and state.tasks[0].interrupts else {}
            reasons = interrupt_val.get("reasons", [])
            extracted_quote = state.values.get("extracted_quote")
            supplier = extracted_quote.supplier_name.value if extracted_quote and extracted_quote.supplier_name else "Unknown"

            row_data: dict[str, Any] = {
                "pdf": str(pdf),
                "pack": pdf.stem,
                "supplier": supplier or "Unknown",
                "item": (extracted_quote.item_code.value if extracted_quote and extracted_quote.item_code else "Unknown"),
                "system_verdict": "Needs a person to check",
                "final_verdict": "Pending Review",
                "reviewer_note": None,
                "extractor_used": state.values.get("extractor_used", mode),
                "reasons": reasons,
                "triggered_rules": interrupt_val.get("triggered_rules", []),
                "audit_log": state.values.get("audit_log", []),
            }
            results.append(row_data)

            reasons_str = "; ".join(reasons) if reasons else "Needs human check"
            table.add_row(
                pdf.stem,
                str(supplier or "Unknown"),
                "[yellow]Needs a person to check[/]",
                "[yellow]Pending Review[/]",
                row_data["extractor_used"],
                reasons_str,
            )
        else:
            rep = state.values.get("report") or {}
            sys_v = rep.get("system_verdict", "Unknown")
            fin_v = rep.get("final_verdict", "Unknown")
            ext = rep.get("extractor_used", mode)
            supp = rep.get("supplier", "Unknown")

            color = "green" if sys_v == "Approve" else ("red" if sys_v == "Reject" else "yellow")
            trig_rules = rep.get("triggered_rules", [])
            reasons_list = [f"{t.get('rule_id')}: {t.get('message')}" for t in trig_rules]
            reasons_str = "; ".join(reasons_list) if reasons_list else "All checks passed"

            row_data = {
                "pdf": str(pdf),
                "pack": pdf.stem,
                "supplier": supp,
                "item": rep.get("item", "Unknown"),
                "system_verdict": sys_v,
                "final_verdict": fin_v,
                "reviewer_note": rep.get("reviewer_note"),
                "extractor_used": ext,
                "reasons": reasons_list,
                "triggered_rules": trig_rules,
                "audit_log": rep.get("audit_log", []),
            }
            results.append(row_data)

            table.add_row(
                pdf.stem,
                supp,
                f"[{color}]{sys_v}[/]",
                f"[{color}]{fin_v}[/]",
                ext,
                reasons_str,
            )

    console.print(table)

    # Save outputs/results.json
    json_path = out / "results.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    console.print(f"Results written to: [bold]{json_path}[/]")

    # Save outputs/results.md
    md_path = out / "results.md"
    _write_markdown_results(results, md_path)
    console.print(f"Markdown report written to: [bold]{md_path}[/]")

    if queued_cases:
        console.print(f"\n[bold yellow]Queued {len(queued_cases)} case(s) needing review:[/] {', '.join(queued_cases)}")
        console.print("Resume with: `python -m supplier_check.cli review <thread_id>`")


def _write_markdown_results(results: list[dict[str, Any]], md_path: Path) -> None:
    """Write markdown summary table."""
    lines: list[str] = [
        "# Supplier Document Checker Pipeline Results",
        "",
        f"Generated: {len(results)} packs processed.",
        "",
        "| Pack | Supplier | System Verdict | Final Verdict | Extractor | Triggered Rules / Reasons |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        pack = r.get("pack", "Unknown")
        supp = r.get("supplier", "Unknown")
        sys_v = r.get("system_verdict", "Unknown")
        fin_v = r.get("final_verdict", "Unknown")
        ext = r.get("extractor_used", "none")

        trigs = r.get("triggered_rules", [])
        if trigs:
            reasons_summary = "<br>".join(
                f"**{t.get('rule_id')}**: {t.get('message')} *(quote: \"{t.get('evidence_quote')}\")*"
                for t in trigs
            )
        else:
            reasons_summary = "All checks passed"

        lines.append(f"| {pack} | {supp} | **{sys_v}** | **{fin_v}** | `{ext}` | {reasons_summary} |")

    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


@app.command()
def review(
    thread_id: Annotated[
        str | None,
        typer.Argument(help="Thread ID / Pack stem to resume (omit to list all queued cases)."),
    ] = None,
    db: Annotated[
        Path, typer.Option("--db", help="Path to checkpoint database.")
    ] = DEFAULT_DB_PATH,
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Output directory for reports.")
    ] = Path("outputs"),
) -> None:
    """List queued reviews or resume a specific case with a human decision."""
    checkpointer = _get_checkpointer(db)
    graph_app = build_supplier_checker_graph(checkpointer=checkpointer)

    if thread_id is None:
        # Scan SQLite DB for interrupted threads
        console.print("[bold]Scanning checkpoint database for queued reviews...[/]")
        try:
            conn = sqlite3.connect(str(db))
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            console.print(f"[bold red]Failed to inspect checkpoints:[/] {e}")
            raise typer.Exit(code=1) from e

        queued: list[str] = []
        for (tid,) in rows:
            cfg = {"configurable": {"thread_id": tid}}
            st = graph_app.get_state(cfg)
            if st.next and "human_review" in st.next:
                queued.append(tid)

        if not queued:
            console.print("[green]No pending reviews in the queue![/]")
            return

        console.print(f"\n[bold yellow]Pending Reviews ({len(queued)}):[/]")
        for q in queued:
            console.print(f"  - [bold cyan]{q}[/]")
        console.print("\nTo review a pack, run: `python -m supplier_check.cli review <thread_id>`")
        return

    # Resume specific thread_id
    config = {"configurable": {"thread_id": thread_id}}
    state = graph_app.get_state(config)

    if not state.next or "human_review" not in state.next:
        console.print(f"[yellow]Case '{thread_id}' is not currently paused at human review (next={state.next}).[/]")
        if state.values.get("report"):
            console.print(f"Current report: {state.values.get('report')}")
        return

    interrupt_val = state.tasks[0].interrupts[0].value if state.tasks and state.tasks[0].interrupts else {}
    console.print(f"\n[bold yellow]Reviewing case:[/] [bold cyan]{thread_id}[/]")
    console.print(f"System Verdict: [bold]{interrupt_val.get('system_verdict')}[/]")
    reasons = interrupt_val.get("reasons", [])
    if reasons:
        console.print("[bold]Reasons:[/]")
        for r in reasons:
            console.print(f"  - {r}")

    choice = typer.prompt("Decision (Approve / Reject)", default="Reject")
    choice_clean = "Approve" if choice.strip().casefold() in {"approve", "a"} else "Reject"
    note = typer.prompt("Reviewer note (reason/justification)", default="")

    try:
        resumed = graph_app.invoke(
            Command(resume={"decision": choice_clean, "reviewer_note": note}),
            config=config,
        )
        report = resumed.get("report")
        console.print(f"\n[bold green]Case '{thread_id}' resolved successfully![/]")
        console.print(f"System Verdict: [bold]{report.get('system_verdict')}[/]")
        console.print(f"Final Verdict:  [bold green]{report.get('final_verdict')}[/]")
        console.print(f"Reviewer Note:  {report.get('reviewer_note')}")

        # Update results.json and results.md if outputs directory exists
        results_file = out / "results.json"
        if results_file.exists():
            try:
                data = json.loads(results_file.read_text(encoding="utf-8"))
                for row in data:
                    if row.get("pack") == thread_id:
                        row["final_verdict"] = report.get("final_verdict")
                        row["reviewer_note"] = report.get("reviewer_note")
                results_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                _write_markdown_results(data, out / "results.md")
                console.print(f"[dim]Updated {results_file} and {out / 'results.md'}[/]")
            except Exception as e:
                console.print(f"[dim yellow]Warning updating reports file: {e}[/]")

    except Exception as e:
        console.print(f"[bold red]Failed to resume human review:[/] {e}")
        raise typer.Exit(code=1) from e


if __name__ == "__main__":
    app()
