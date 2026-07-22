"""
Aughor CLI — start the platform and run autonomous investigations from the terminal.

Usage:
  aughor up          # start API (:8000) + web UI (:3000) — the one-command bootstrap
  aughor investigate "Why did revenue drop 8% last week?"
  aughor investigate "Why did revenue drop 8% last week?" --db data/aughor.duckdb
  aughor seed        # create the fixture database
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

import click
import duckdb
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table

console = Console()

DEFAULT_DB = Path(__file__).parent.parent / "data" / "aughor.duckdb"

# Mirrors aughor.llm.provider.BACKENDS — kept as a literal so `aughor --help` stays
# instant (importing the provider pulls in instructor/openai at module scope).
# tests/unit/test_cli_up.py pins the two lists in sync.
LLM_BACKENDS: tuple[str, ...] = ("ollama", "lmstudio", "groq", "together", "anthropic",
                                 "gemini", "openrouter")


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Aughor — Autonomous Intelligence Platform"""


# ── Seed ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db", "db", default=str(DEFAULT_DB), show_default=True, help="Path to the DuckDB file to (re)create")
def seed(db: str):
    """Seed the demo DuckDB database (the one `aughor investigate` reads).

    Writes the bundled outage scenario — 90 days of SaaS revenue for ~800
    customers with a discoverable APAC payment-gateway outage — replacing any
    existing file at the target path.
    """
    from aughor.samples.scenario import seed_scenario_db

    summary = seed_scenario_db(Path(db), overwrite=True)
    console.print(f"Database seeded at: [bold]{db}[/bold]")
    console.print(f"  Customers:         {summary['customers']:,}")
    console.print(f"  Revenue rows:      {summary['revenue_rows']:,}")
    console.print(f"  Total revenue:     ${summary['total_revenue']:,.0f}")
    console.print(f"  Outage date:       {summary['outage_date']}")
    console.print(f"  APAC SMB revenue on outage day: ${summary['outage_apac_smb_revenue']:,.0f}")
    console.print(f"  APAC SMB baseline (7-day avg):  ${summary['baseline_apac_smb_revenue']:,.0f}")
    console.print(f"  Revenue drop in APAC SMB:       {summary['apac_smb_drop_pct']}%")
    console.print(f"  Failure rate APAC SMB on outage: {summary['apac_smb_outage_failure_rate_pct']}%")


# ── Up (one-command bootstrap: API + web UI) ─────────────────────────────────

def _repo_root() -> Path:
    """Locate the repo root for `aughor up`.

    Rule: prefer the current working directory when it looks like an Aughor
    checkout (has both pyproject.toml and web/) — that keeps `uv run aughor up`
    working from any clone; otherwise fall back to the parent of this package
    (the checkout the `aughor` package was imported from, same anchor DEFAULT_DB
    uses)."""
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").is_file() and (cwd / "web").is_dir():
        return cwd
    return Path(__file__).resolve().parent.parent


def _port_in_use(port: int) -> bool:
    """True when something already listens on the port (best-effort: try to bind
    127.0.0.1 — the interface uvicorn/next bind by default in dev)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _port_owner(port: int) -> str:
    """Best-effort 'command (pid N)' description of the port's listener via lsof.
    Empty string when lsof is unavailable or the owner can't be determined."""
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()
    except Exception:
        return ""  # lsof missing / not permitted — the port-busy verdict still stands
    if len(out) < 2:
        return ""
    parts = out[1].split()  # header then: COMMAND PID USER ...
    return f"{parts[0]} (pid {parts[1]})" if len(parts) >= 2 else ""


def _check_port_free(port: int, what: str, flag: str) -> None:
    """Refuse to start on a busy port — never kill the owner (it may be someone
    else's live server). Print who owns it and how to pick another port."""
    if not _port_in_use(port):
        return
    owner = _port_owner(port)
    owner_bit = f" — owned by [bold]{owner}[/bold]" if owner else ""
    console.print(f"[red]Port {port} is already in use[/red] (needed for {what}){owner_bit}.", soft_wrap=True)
    console.print(
        f"Aughor won't kill it. Stop that process yourself, or pick another port with [bold]{flag}[/bold].",
        soft_wrap=True,
    )
    sys.exit(1)


def _launch(cmd: list[str], *, cwd: Path, env: Optional[dict] = None) -> subprocess.Popen:
    """Thin Popen wrapper (module-level so tests can stub spawning). Children
    inherit stdout/stderr — `aughor up` is a foreground dev runner."""
    return subprocess.Popen(cmd, cwd=str(cwd), env=env)


def _ensure_web_deps(root: Path) -> None:
    """First-run preflight: install frontend deps when web/node_modules is absent."""
    web_dir = root / "web"
    if not web_dir.is_dir():
        console.print(f"[red]web/ not found under {root}[/red] — is this an Aughor checkout?")
        sys.exit(1)
    if (web_dir / "node_modules").exists():
        return
    console.print("[cyan]First run — installing frontend deps (npm install, one-time)…[/cyan]")
    try:
        proc = subprocess.run(["npm", "install", "--prefix", str(web_dir)])
    except FileNotFoundError:
        console.print("[red]npm not found.[/red] Install Node 20+ (https://nodejs.org) and re-run.")
        sys.exit(1)
    if proc.returncode != 0:
        console.print("[red]npm install failed[/red] — see the output above.")
        sys.exit(proc.returncode)


def _wait_for_health(
    url: str, timeout: float = 30.0, *, is_alive: Optional[Callable[[], bool]] = None
) -> Optional[dict]:
    """Poll /health until it answers 200 (returns its JSON) or the timeout lapses
    (returns None). `is_alive` short-circuits the wait when the API process dies."""
    import httpx
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_alive is not None and not is_alive():
            return None
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return r.json()
        except Exception:
            r = None  # not accepting connections yet — keep polling
        time.sleep(0.5)
    return None


def _print_boot_summary(health: Optional[dict], api_port: int, web_port: Optional[int]) -> None:
    console.print()
    console.print(Rule("[bold cyan]Aughor is up[/bold cyan]", style="cyan"))
    console.print(f"  API   [bold]http://localhost:{api_port}[/bold]  [dim](docs at /docs)[/dim]")
    if web_port is not None:
        console.print(f"  Web   [bold]http://localhost:{web_port}[/bold]")
    if health is None:
        console.print("  [yellow]/health did not answer within 30s — the API may still be starting; check the logs above.[/yellow]")
    else:
        if health.get("fixture_db"):
            console.print("  Data  demo dataset ready [dim](auto-seeded on first boot)[/dim]")
        else:
            console.print("  Data  [yellow]demo dataset not seeded yet[/yellow] [dim](run `aughor seed` if it never appears)[/dim]")
        llm = health.get("llm") or {}
        backend, model = llm.get("backend") or "unknown", llm.get("model") or "?"
        if llm.get("ready"):
            console.print(f"  LLM   {backend} · {model} · [green]ready[/green]", soft_wrap=True)
        else:
            console.print(f"  LLM   {backend} · {model} · [red]not ready (API key missing)[/red]", soft_wrap=True)
            console.print(
                "        Fix it in Settings → Inference in the web UI, or set AUGHOR_BACKEND/key envs in .env",
                soft_wrap=True,
            )
    console.print()
    console.print("[dim]Ctrl-C stops everything.[/dim]")
    console.print()


def _signal_quietly(proc: subprocess.Popen, method: str) -> None:
    """terminate()/kill() tolerant of the child exiting in the same instant."""
    try:
        getattr(proc, method)()
    except OSError as exc:
        _ = exc  # already gone — nothing left to stop


def _terminate(procs: list[subprocess.Popen], grace: float = 5.0) -> None:
    """Stop every still-running child: terminate → wait up to `grace`s → kill."""
    live = [p for p in procs if p.poll() is None]
    for p in live:
        _signal_quietly(p, "terminate")
    deadline = time.monotonic() + grace
    for p in live:
        try:
            p.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _signal_quietly(p, "kill")
            p.wait()


def _supervise(procs: list[subprocess.Popen]) -> int:
    """Foreground both children; return the exit code of whichever exits first
    (the caller stops the sibling)."""
    while True:
        for p in procs:
            code = p.poll()
            if code is not None:
                return code
        time.sleep(0.5)


def _raise_sigterm(signum, frame):  # pragma: no cover — signal plumbing
    raise KeyboardInterrupt


@cli.command()
@click.option("--api-port", default=8000, show_default=True, type=int, help="Port for the FastAPI backend")
@click.option("--web-port", default=3000, show_default=True, type=int, help="Port for the Next.js web UI")
@click.option("--dev", is_flag=True, help="Run the API with auto-reload (uvicorn --reload)")
@click.option("--api-only", is_flag=True, help="Start only the API")
@click.option("--web-only", is_flag=True, help="Start only the web UI")
def up(api_port: int, web_port: int, dev: bool, api_only: bool, web_only: bool):
    """Start Aughor — API + web UI — with one command.

    Installs frontend deps on the first run, refuses to touch ports something
    else owns, waits for the API to come up healthy, then prints where
    everything is (URLs, demo-data status, LLM readiness). First boot
    auto-seeds a demo dataset. Ctrl-C stops both processes.
    """
    if api_only and web_only:
        raise click.UsageError("--api-only and --web-only are mutually exclusive.")

    root = _repo_root()
    run_api, run_web = not web_only, not api_only

    if run_api:
        _check_port_free(api_port, "the Aughor API", "--api-port")
    if run_web:
        _check_port_free(web_port, "the web UI", "--web-port")
        _ensure_web_deps(root)

    procs: list[subprocess.Popen] = []
    api_proc: Optional[subprocess.Popen] = None
    signal.signal(signal.SIGTERM, _raise_sigterm)  # docker/CI stop → same clean path as Ctrl-C

    try:
        if run_api:
            api_cmd = [sys.executable, "-m", "uvicorn", "aughor.api:app", "--port", str(api_port)]
            if dev:
                api_cmd += ["--reload", "--timeout-graceful-shutdown", "3"]
            api_proc = _launch(api_cmd, cwd=root)
            procs.append(api_proc)

        if run_web:
            env = dict(os.environ)
            if api_port != 8000:
                # The web app defaults to http://localhost:8000 — point it at the chosen port.
                env["NEXT_PUBLIC_API_URL"] = f"http://localhost:{api_port}"
            web_cmd = ["npm", "run", "dev", "--prefix", str(root / "web"), "--", "-p", str(web_port)]
            procs.append(_launch(web_cmd, cwd=root, env=env))

        if api_proc is not None:
            health = _wait_for_health(
                f"http://127.0.0.1:{api_port}/health",
                is_alive=lambda: api_proc.poll() is None,
            )
            if health is None and api_proc.poll() is not None:
                console.print(f"[red]API exited during startup (code {api_proc.returncode})[/red] — see the logs above.")
                sys.exit(api_proc.returncode or 1)
            _print_boot_summary(health, api_port, web_port if run_web else None)
        else:
            console.print(f"\n  Web  [bold]http://localhost:{web_port}[/bold]  [dim](expects the API on :{api_port})[/dim]\n")

        code = _supervise(procs)
        console.print(f"\n[yellow]A process exited (code {code}) — stopping the rest.[/yellow]")
        sys.exit(code)
    except KeyboardInterrupt:
        console.print("\n[dim]Shutting down…[/dim]")
        sys.exit(0)
    finally:
        _terminate(procs)


# ── Investigate ──────────────────────────────────────────────────────────────

@cli.command()
@click.argument("question")
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to DuckDB file")
@click.option("--model", default=None, help="Override the model (e.g. qwen2.5-coder:14b)")
@click.option("--backend", default="ollama", show_default=True, type=click.Choice(list(LLM_BACKENDS)))
def investigate(question: str, db: str, model: Optional[str], backend: str):
    """Run an autonomous investigation on a business question."""
    import os
    if model:
        os.environ["AUGHOR_MODEL"] = model
    os.environ["AUGHOR_BACKEND"] = backend

    # Plug the Agent into the Platform registries (schema annotators, purge hooks) so
    # the CLI host runs the same plugged-in agent the API does.
    from aughor.agent.bootstrap import register_agent_plugins
    register_agent_plugins()

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

    # The deep-analysis (ADA) path produces a rich answer_report (phases, per-finding SQL,
    # key numbers, real significance). Render that directly — the legacy AnalysisReport
    # flattens away the SQL and the logic. Fall back to legacy only when no answer_report exists.
    if final_state.get("answer_report"):
        _print_ada_report(final_state["answer_report"], elapsed_total)
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


@cli.command(name="ontology-docs")
@click.argument("connection_id")
@click.option("--schema", default="", help="Schema to document (default: the connection's cached ontology schema)")
@click.option("--confirm", is_flag=True, help="Build and persist the doc tree (default: estimate only)")
@click.option("--full", is_flag=True, help="Full rebuild — ignore the prior tree's Merkle cache")
@click.option("--enrich", is_flag=True,
              help="R8b: also LLM-polish stale table summaries (estimated first; spends only with --confirm)")
def ontology_docs(connection_id: str, schema: str, confirm: bool, full: bool, enrich: bool):
    """Compile the ontology into a persisted doc-tree artifact (R8).

    Estimate-then-confirm: without --confirm this only reports what a build would touch (no
    writes). The core is deterministic — no model; --enrich adds the OPTIONAL per-table LLM
    polish (R8b), estimated up front and width-routed (small tables → fast, wide → coder).
    Requires the connection's ontology to already be built.
    """
    from aughor.ontology.doctree import (build_and_persist, enrich_tree,
                                          estimate_doc_build, estimate_enrichment,
                                          load_doc_tree)
    from aughor.ontology.store import load_latest_ontology

    graph = load_latest_ontology(connection_id, schema or None)
    if graph is None:
        console.print(f"[red]No ontology found for[/red] {connection_id} (schema={schema or 'any'}).")
        console.print("Build intelligence first (open/explore the connection), then retry.")
        sys.exit(1)

    eff_schema = graph.schema_name or schema or ""
    prior = None if full else load_doc_tree(connection_id, eff_schema)
    est = estimate_doc_build(graph, prior=prior)

    # R8b — the enrichment spend is estimated on the tree the build WOULD produce
    # (prior-aware), so the number shown is the number --confirm would pay.
    llm_line = f"LLM tokens: {est['llm_tokens']} (deterministic)"
    if enrich:
        from aughor.ontology.doctree import build_doc_tree
        _preview = build_doc_tree(graph, prior=prior)
        enr_est = estimate_enrichment(_preview)
        llm_line = (f"LLM tokens (--enrich): ~[yellow]{enr_est['est_tokens']:,}[/yellow] across "
                    f"{enr_est['nodes']} stale tables (fast {enr_est['fast']} / coder {enr_est['coder']})")

    console.print()
    console.print(Panel(
        f"[bold]{connection_id}[/bold]  schema=[cyan]{eff_schema or '(default)'}[/cyan]\n"
        f"nodes: [bold]{est['nodes']}[/bold]  ({est['tables']} tables, {est['columns']} columns)\n"
        f"would rebuild: [yellow]{est['would_rebuild']}[/yellow]   "
        f"reuse (Merkle cache): [green]{est['would_reuse']}[/green]\n"
        f"skipped (ignore-globs): {len(est['skipped_tables'])}   "
        f"{llm_line}",
        title="[bold cyan]Ontology docs — estimate[/bold cyan]", border_style="cyan", padding=(1, 2),
    ))

    if not confirm:
        console.print("\n[dim]Dry run. Re-run with [bold]--confirm[/bold] to build and persist.[/dim]\n")
        return

    tree = build_and_persist(connection_id, eff_schema, graph=graph, incremental=not full)
    console.print(
        f"\n[green]Built[/green] doc tree — root checksum [bold]{tree.root_checksum}[/bold] "
        f"(reused {tree.stats['cache_hits']}, rebuilt {tree.stats['rebuilt']}).")
    if enrich:
        enr = enrich_tree(tree, persist=True)
        console.print(
            f"[green]Enriched[/green] {enr['enriched']} table summaries "
            f"(fast {enr['routed']['fast']} / coder {enr['routed']['coder']}"
            + (f", [yellow]{enr['failed']} failed[/yellow] — kept deterministic" if enr['failed'] else "")
            + ").")
    console.print(f"[dim]Persisted under data/ontology_docs/{connection_id}/{eff_schema or 'default'}/[/dim]\n")

    for node in tree.tables()[:8]:
        console.print(f"[bold]{node.fqn}[/bold] — {node.best_summary()}")
        for q in node.questions:
            console.print(f"    [cyan]?[/cyan] {q}")
    console.print()


if __name__ == "__main__":
    cli()
