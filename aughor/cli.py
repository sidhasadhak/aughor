"""
Aughor CLI — run autonomous investigations from the terminal.

Usage:
  aughor investigate "Why did revenue drop 8% last week?"
  aughor investigate "Why did revenue drop 8% last week?" --db data/aughor.duckdb
  aughor seed        # create the fixture database
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
from rich.padding import Padding
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()

DEFAULT_DB = Path(__file__).parent.parent / "data" / "aughor.duckdb"


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Aughor — Autonomous Intelligence Platform"""


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
        os.environ["AUGHOR_MODEL"] = model
    os.environ["AUGHOR_BACKEND"] = backend

    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[red]Database not found:[/red] {db_path}")
        console.print("Run [bold]aughor seed[/bold] first to create the fixture database.")
        sys.exit(1)

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
    except Exception as e:
        console.print(f"[red]Could not open database:[/red] {e}")
        sys.exit(1)

    console.print()
    console.print(Panel(
        f"[bold white]{question}[/bold white]",
        title="[bold cyan]Aughor Investigation[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    from aughor.agent.graph import run_investigation

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

    # The deep-analysis (ADA) path produces a rich ada_report (phases, per-finding SQL,
    # key numbers, real significance). Render that directly — the legacy AnalysisReport
    # flattens away the SQL and the logic. Fall back to legacy only when no ada_report exists.
    if final_state.get("ada_report"):
        _print_ada_report(final_state["ada_report"], elapsed_total)
    else:
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


def _print_ada_report(report: dict, elapsed: float):
    """Render the rich deep-analysis (ADA) report: phases, per-finding SQL, key numbers,
    real significance and confidence. Prose is rendered as Markdown (so **bold** doesn't leak
    as literal asterisks), and the actual query for each finding is shown — the terminal user
    gets the same access to query + logic the web report gives."""
    phases = report.get("phases") or []
    analysis_phases = [p for p in phases if p.get("phase_id") != "intake" and p.get("status") != "skipped"]
    findings_with_sql = [
        f for p in phases for f in (p.get("findings") or [])
        if f.get("sql") and not f.get("error")
    ]

    console.print()
    console.print(Rule("[bold cyan]Investigation Complete[/bold cyan]", style="cyan"))
    console.print(
        f"[dim]{elapsed:.1f}s · {len(findings_with_sql)} queries · "
        f"{len(analysis_phases)} phases[/dim]"
    )
    console.print()

    # Headline
    if report.get("headline"):
        console.print(Panel(
            Markdown(report["headline"]),
            title="[bold green]Verdict[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))

    # Metadata line — only the parts that actually apply (a cross-sectional scan has no period)
    meta_bits = [b for b in (
        report.get("metric"),
        report.get("observation_period"),
        f"vs {report['comparison_basis']}" if report.get("comparison_basis") else "",
        report.get("total_change_label"),
        f"{report['confidence'].title()} confidence" if report.get("confidence") else "",
    ) if b]
    if meta_bits:
        console.print(f"[dim]{'  ·  '.join(meta_bits)}[/dim]")
    console.print()

    # Executive summary
    if report.get("executive_summary"):
        console.print(Panel(
            Markdown(report["executive_summary"]),
            title="[bold]Diagnosis[/bold]",
            border_style="white",
            padding=(1, 2),
        ))

    # Phases — each a section with its findings, key numbers, significance, and SQL
    for p in analysis_phases:
        icon = p.get("phase_icon") or "•"
        console.print(f"\n[bold]{icon}  {p.get('phase_name', p.get('phase_id', 'Phase'))}[/bold]")
        if p.get("summary"):
            console.print(Markdown(p["summary"]))
        for f in p.get("findings") or []:
            if f.get("error"):
                console.print(f"  [red]✗ {f.get('title', 'finding')}: {f['error']}[/red]")
                continue
            console.print(f"\n  [italic]{f.get('title', '')}[/italic]")

            key_numbers = f.get("key_numbers") or []
            if key_numbers:
                parts = []
                for kn in key_numbers:
                    seg = f"[bold]{kn.get('value', '')}[/bold] {kn.get('label', '')}"
                    if kn.get("delta"):
                        seg += f" ([cyan]{kn['delta']}[/cyan])"
                    parts.append(seg.strip())
                console.print("  " + "   ".join(parts))

            if f.get("interpretation"):
                console.print(Padding(Markdown(f["interpretation"]), (0, 0, 0, 2)))

            sig = f.get("stat_note") or ("Significant" if f.get("is_significant") else "Within noise")
            sig_color = "green" if f.get("is_significant") else "dim"
            console.print(f"  [{sig_color}]▸ {sig}[/{sig_color}]")

            if f.get("trust_caveat"):
                console.print(f"  [yellow]⚠ Trust advisory: {f['trust_caveat']}[/yellow]")

            if f.get("sql"):
                console.print(Padding(
                    Syntax(f["sql"].strip(), "sql", theme="ansi_dark", word_wrap=True, background_color="default"),
                    (0, 0, 0, 2),
                ))

    # Attribution waterfall
    waterfall = report.get("attribution_waterfall") or []
    if waterfall:
        console.print("\n[bold]Attribution[/bold]")
        wt = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
        wt.add_column("Cause")
        wt.add_column("Amount", width=14)
        wt.add_column("Share", width=8, justify="right")
        wt.add_column("Type", width=14)
        for w in waterfall:
            kind = "controllable" if w.get("controllable") else ("structural" if w.get("structural") else "transient")
            wt.add_row(w.get("cause", ""), w.get("amount_label", ""), f"{w.get('pct_of_total', 0):.0f}%", kind)
        console.print(wt)

    # Data gaps
    if report.get("data_gaps"):
        console.print("\n[bold dim]Data gaps[/bold dim]")
        for g in report["data_gaps"]:
            console.print(f"  [dim]✗ {g}[/dim]")

    # Recommendations
    recs = report.get("recommendations") or []
    if recs:
        console.print("\n[bold]Recommended Actions[/bold]")
        for i, r in enumerate(recs, 1):
            line = f"  {i}. {r.get('action', '')}"
            tail = "  ".join(b for b in (r.get("expected_impact"), r.get("owner"), r.get("timeline")) if b)
            console.print(Markdown(line))
            if tail:
                console.print(f"     [dim]{tail}[/dim]")

    console.print()


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
