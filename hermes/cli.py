"""
Hermes CLI — run autonomous investigations from the terminal.

Usage:
  hermes investigate "Why did revenue drop 8% last week?"
  hermes investigate "Why did revenue drop 8% last week?" --db data/hermes.duckdb
  hermes seed        # create the fixture database
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Optional

import click
import duckdb
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()

DEFAULT_DB = Path(__file__).parent.parent / "data" / "hermes.duckdb"


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Hermes — Autonomous Data Analyst"""


# ── Seed ─────────────────────────────────────────────────────────────────────

@cli.command()
def seed():
    """Seed the fixture DuckDB database with synthetic SaaS data."""
    from data.seed import main as seed_main  # type: ignore
    seed_main()


# ── Investigate ──────────────────────────────────────────────────────────────

@cli.command()
@click.argument("question")
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to DuckDB file")
@click.option("--model", default=None, help="Override Ollama model (e.g. qwen2.5-coder:14b)")
@click.option("--backend", default="ollama", show_default=True, type=click.Choice(["ollama", "anthropic"]))
def investigate(question: str, db: str, model: Optional[str], backend: str):
    """Run an autonomous investigation on a business question."""
    import os
    if model:
        os.environ["HERMES_MODEL"] = model
    os.environ["HERMES_BACKEND"] = backend

    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[red]Database not found:[/red] {db_path}")
        console.print("Run [bold]hermes seed[/bold] first to create the fixture database.")
        sys.exit(1)

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
    except Exception as e:
        console.print(f"[red]Could not open database:[/red] {e}")
        sys.exit(1)

    console.print()
    console.print(Panel(
        f"[bold white]{question}[/bold white]",
        title="[bold cyan]Hermes Investigation[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    from hermes.agent.graph import run_investigation

    node_log: list[tuple[str, Any]] = []
    start = time.monotonic()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Decomposing question...", total=None)

        def on_node(node_name: str, state: Any):
            elapsed = time.monotonic() - start
            node_log.append((node_name, state, elapsed))

            descriptions = {
                "decompose":        "Decomposing question into hypotheses...",
                "plan_and_execute": f"Planning & executing queries (H{state.get('current_hypothesis_idx', 0) + 1})...",
                "score_evidence":   f"Scoring evidence (iteration {state.get('iteration', 0)})...",
                "synthesize":       "Synthesizing narrative report...",
            }
            desc = descriptions.get(node_name, f"Running: {node_name}")

            # Print live node updates
            _print_node_update(node_name, state, elapsed)
            progress.update(task, description=f"[cyan]{desc}")

        final_state = run_investigation(question, conn, on_node=on_node)

    elapsed_total = time.monotonic() - start
    conn.close()

    _print_final_report(final_state, elapsed_total)


# ── Rendering helpers ────────────────────────────────────────────────────────

_NODE_LABELS = {
    "decompose":        ("🔍", "Decomposed"),
    "plan_and_execute": ("⚡", "Planned & Executed"),
    "score_evidence":   ("📊", "Evidence Scored"),
    "synthesize":       ("✍️ ", "Synthesizing"),
}


def _print_node_update(node_name: str, state: Any, elapsed: float):
    icon, label = _NODE_LABELS.get(node_name, ("•", node_name))

    if node_name == "decompose" and state.get("hypotheses"):
        console.print(f"\n[dim]{elapsed:.1f}s[/dim]  {icon} [bold]{label}[/bold]")
        for i, h in enumerate(state["hypotheses"], 1):
            console.print(f"   H{i}: [italic]{h.description}[/italic]")

    elif node_name == "score_evidence" and state.get("evidence_scores"):
        scores = state["evidence_scores"]
        latest = scores[-1] if scores else None
        if latest:
            verdict_color = {
                "confirmed": "green",
                "refuted": "red",
                "inconclusive": "yellow",
            }.get(latest.verdict, "white")
            bar_filled = int(latest.confidence * 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            console.print(
                f"\n[dim]{elapsed:.1f}s[/dim]  {icon} [bold]{label}[/bold]  "
                f"[{verdict_color}]{latest.verdict.upper()}[/{verdict_color}]  "
                f"[{verdict_color}]{bar}[/{verdict_color}] {latest.confidence:.0%}"
            )
            console.print(f"   [dim]{latest.key_finding}[/dim]")


def _print_final_report(state: Any, elapsed: float):
    report = state.get("report")
    hypotheses = state.get("hypotheses", [])
    query_history = state.get("query_history", [])

    console.print()
    console.print(Rule("[bold cyan]Investigation Complete[/bold cyan]", style="cyan"))
    console.print(f"[dim]{elapsed:.1f}s · {len(query_history)} queries · {len(hypotheses)} hypotheses tested[/dim]")
    console.print()

    if not report:
        console.print("[red]No report was generated.[/red]")
        return

    # Headline
    console.print(Panel(
        f"[bold white]{report.headline}[/bold white]",
        title="[bold green]Verdict[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))
    console.print()

    # Hypothesis scorecard
    if hypotheses:
        console.print("[bold]Hypothesis Scorecard[/bold]")
        ht = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
        ht.add_column("", width=3)
        ht.add_column("Hypothesis", style="italic")
        ht.add_column("Verdict", width=14)
        ht.add_column("Confidence", width=22)

        for i, h in enumerate(hypotheses, 1):
            verdict_color = {"confirmed": "green", "refuted": "red", "inconclusive": "yellow", "untested": "dim"}.get(h.verdict, "white")
            bar = "█" * int(h.confidence * 10) + "░" * (10 - int(h.confidence * 10))
            ht.add_row(
                f"H{i}",
                h.description[:80] + ("…" if len(h.description) > 80 else ""),
                f"[{verdict_color}]{h.verdict.upper()}[/{verdict_color}]",
                f"[{verdict_color}]{bar}[/{verdict_color}] {h.confidence:.0%}",
            )
        console.print(ht)

    # Full verdict
    console.print(Panel(
        report.verdict,
        title="[bold]Diagnosis[/bold]",
        border_style="white",
        padding=(1, 2),
    ))

    # Key findings
    if report.key_findings:
        console.print("[bold]Key Findings[/bold]")
        ft = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
        ft.add_column("#", width=3)
        ft.add_column("Finding")
        ft.add_column("Evidence", style="dim")
        ft.add_column("Confidence", width=14)
        for i, f in enumerate(report.key_findings, 1):
            ft.add_row(
                str(i),
                f.claim,
                f.evidence[:80] + ("…" if len(f.evidence) > 80 else ""),
                f"{f.confidence:.0%}",
            )
        console.print(ft)

    # What was ruled out
    if report.what_is_not_the_cause:
        console.print("\n[bold dim]Ruled Out[/bold dim]")
        for item in report.what_is_not_the_cause:
            console.print(f"  [dim]✗ {item}[/dim]")

    # Recommended actions
    if report.recommended_actions:
        console.print("\n[bold]Recommended Actions[/bold]")
        for i, action in enumerate(report.recommended_actions, 1):
            console.print(f"  {i}. {action}")

    console.print()


if __name__ == "__main__":
    cli()
