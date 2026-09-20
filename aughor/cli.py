"""
Aughor CLI — start the platform and run autonomous deep analyses from the terminal.

Usage:
  aughor up          # install what's missing, start API (:8000) + web app (:3000), open it
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

from aughor import netprobe as _netprobe

import click
import duckdb
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
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
    # Before any output. Redirected on Windows, a stream encodes as the ANSI code page, which has
    # no "→": one in `aughor up`'s summary crashed it the moment its servers were up.
    from aughor.installer import tolerate_narrow_output
    tolerate_narrow_output()
    # 🔴 Load `.env` HERE, in the group callback every command passes through — not at
    # module import, which would put a developer's environment into any test that merely
    # imports this module (`test_env_isolation` guards exactly that, and said so).
    #
    # Why it matters, and the ledger item it closes: `.env` was read by `api.py` and
    # `semantic/kb_retriever.py` and nothing else, so a process starting at the CLI saw
    # none of it — including `AUGHOR_QDRANT_URL`, which pins the semantic index at a
    # server. Without that pin `vector_store._client()` takes the embedded branch at
    # `state_dir()/qdrant`, and `aughor investigate` reaches the store through
    # `agent.bootstrap` (`delete_by_filter` / `match_filter`). That is the stray
    # `data/qdrant/` that appeared in a tree whose `.env` pinned a server — the loose end
    # nobody could account for.
    #
    # At the ENTRYPOINT rather than in each library module: `kb_retriever` had already
    # patched itself, and patching one call site is exactly why the gap survived — the
    # next path in did not go through it.
    if not os.environ.get("AUGHOR_SKIP_DOTENV"):
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).parent.parent / ".env")
        except ImportError as exc:
            # Through `tolerate`, not a bare `pass`. The silent-swallow ratchet caught the
            # first version and was right to: python-dotenv being absent is survivable, but
            # it means every pin in `.env` silently does not apply — which is the exact
            # class of failure this whole change exists to fix, so swallowing it without a
            # word would reintroduce the defect one layer down. `kb_retriever` already
            # handles it this way.
            from aughor.kernel.errors import tolerate
            tolerate(exc, "python-dotenv is optional; without it the CLI reads only the "
                          "real environment, so anything pinned in .env does not apply",
                     counter="cli.dotenv")


# ── Seed ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db", "db", default=str(DEFAULT_DB), show_default=True, help="Path to the DuckDB file to (re)create")
def seed(db: str):
    """Seed the demo DuckDB database (the one `aughor investigate` reads).

    Writes the bundled outage scenario — 90 days of SaaS revenue for ~800
    customers with a discoverable APAC payment-gateway outage — replacing any
    existing file at the target path.
    """
    from aughor.demo.scenario import seed_scenario_db

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


# ── Up (install what's missing, start the API and the web app) ───────────────

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


#: IN-1 — both live in `aughor.netprobe` now, because `doctor` needs the same two answers and
#: a private name imported across modules is what the kernel-contract ratchet forbids. The
#: aliases keep this module's own call sites reading as they did.
_port_in_use = _netprobe.port_in_use
_port_owner = _netprobe.port_owner


def _aughor_answers(port: int) -> bool:
    """Whether the listener on `port` is an Aughor API — so a second `aughor up` can say that
    Aughor is already running, instead of reading like a clash with some unknown program."""
    import httpx

    try:
        response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
        body = response.json() if response.status_code == 200 else None
    except Exception:
        return False  # not answering, not HTTP, or not JSON: not an Aughor API
    return isinstance(body, dict) and "status" in body and "llm" in body


def _check_port_free(port: int, what: str, flag: str, *, web_port: Optional[int] = None) -> None:
    """Refuse to start on a busy port — never kill the owner (it may be someone
    else's live server). Say who holds it, and how to pick another port."""
    if not _port_in_use(port):
        return
    owner = _port_owner(port)
    held_by = f" (held by [bold]{escape(owner)}[/bold])" if owner else ""
    console.print()
    if flag == "--api-port" and _aughor_answers(port):
        console.print(f"  [yellow]Aughor is already running[/yellow]: its API is on port {port}{held_by}.",
                      soft_wrap=True)
        if web_port is not None:
            console.print(f"  Open [bold]http://localhost:{web_port}[/bold], or stop it first "
                          "(Ctrl+C in the terminal it runs in).", soft_wrap=True)
        console.print(f"  To start a second copy, give it other ports with [bold]{flag}[/bold] "
                      "and [bold]--web-port[/bold].", soft_wrap=True)
    else:
        console.print(f"  [red]Port {port} is already in use[/red]{held_by}, and {what} needs it.",
                      soft_wrap=True)
        console.print("  Aughor won't kill another program. Stop it yourself, or pick another "
                      f"port with [bold]{flag}[/bold].", soft_wrap=True)
    console.print()
    sys.exit(1)


#: The default of AUGHOR_CORS_ORIGINS in aughor/api.py, mirrored so a web app on another port
#: can be ADDED to it without importing the API. tests/unit/test_cli_up.py pins the two together.
_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:3001,http://localhost:3210"


def _api_env(web_port: Optional[int]) -> dict:
    """The API's environment. Output unbuffered, so its log is current when a failure is read
    back from it. And a web app on a port the API does not already accept is added to CORS —
    otherwise the browser refuses every request it makes. An AUGHOR_CORS_ORIGINS the user set
    is left exactly as it is."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    if web_port is not None and "AUGHOR_CORS_ORIGINS" not in env:
        origin = f"http://localhost:{web_port}"
        if origin not in _DEFAULT_CORS_ORIGINS.split(","):
            env["AUGHOR_CORS_ORIGINS"] = f"{_DEFAULT_CORS_ORIGINS},{origin}"
    return env


def _launch(cmd: list[str], *, cwd: Path, env: Optional[dict] = None,
            log: Optional[Path] = None) -> subprocess.Popen:
    """Start one server (module-level so tests can stub spawning). With `log` its output goes to
    that file; without, it shares this terminal (`--dev`, `--verbose`)."""
    if log is None:
        return subprocess.Popen(cmd, cwd=str(cwd), env=env)
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        return subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT)


def _wait_for_health(
    url: str, timeout: float = 120.0, *, is_alive: Optional[Callable[[], bool]] = None,
    on_slow: Optional[Callable[[], None]] = None, slow_after: float = 12.0,
) -> Optional[dict]:
    """Poll /health until it answers 200 (returns its JSON) or the timeout lapses
    (returns None). `is_alive` short-circuits the wait when the API process dies.

    `on_slow` is called once, after `slow_after` seconds, so a slow start reads as progress
    rather than a hang. The ceiling is generous because `is_alive` already ends the wait the
    instant the API dies — waiting longer costs nothing on the failure path, and giving up
    early on a slow machine cost the user the summary.
    """
    import httpx
    start = time.monotonic()
    deadline = start + timeout
    announced = False
    while time.monotonic() < deadline:
        if is_alive is not None and not is_alive():
            return None
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return r.json()
        except Exception:
            r = None  # not accepting connections yet — keep polling
        if on_slow is not None and not announced and time.monotonic() - start >= slow_after:
            on_slow()
            announced = True
        time.sleep(0.5)
    return None


def _wait_for_web(port: int, timeout: float = 90.0, *,
                  is_alive: Optional[Callable[[], bool]] = None) -> bool:
    """Wait until the web server accepts connections. A connection rather than a page request:
    `next dev` compiles a page on its first request, and the browser is the one to make it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_alive is not None and not is_alive():
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)  # not listening yet
    return False


def _should_open_browser(no_browser: bool, dev: bool) -> bool:
    """Open the web app for the person who just started it — but not in `--dev` (restarted all
    day), not when told not to, and never where no browser can appear: CI, a pipe, an SSH
    session, or a Linux machine with no display, where Python's `webbrowser` would start a
    text-mode browser inside this very terminal."""
    if no_browser or dev or os.environ.get("CI"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return True


def _open_browser(url: str) -> bool:
    import webbrowser

    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False  # no usable browser: the summary prints the address either way


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _print_boot_summary(health: Optional[dict], api_port: int, web_port: Optional[int], *,
                        logs: Optional[Path] = None, browser_opened: bool = False,
                        next_time: str = "") -> None:
    """Where Aughor is, and what is still missing before the first question."""
    console.print()
    if web_port is not None:
        opened = "  [dim](opened in your browser)[/dim]" if browser_opened else ""
        console.print(f"  [bold]Aughor is ready:[/bold] [bold cyan]http://localhost:{web_port}[/bold cyan]{opened}",
                      soft_wrap=True)
        console.print(f"  [dim]API http://localhost:{api_port} · API docs http://localhost:{api_port}/docs[/dim]",
                      soft_wrap=True)
    else:
        console.print(f"  [bold]The API is ready:[/bold] [bold cyan]http://localhost:{api_port}[/bold cyan]"
                      "  [dim](docs at /docs)[/dim]", soft_wrap=True)
    console.print()
    if health is None:
        console.print("  [yellow]The API has not answered yet.[/yellow] It may still be starting; "
                      "the address above is right.", soft_wrap=True)
    else:
        llm = health.get("llm") or {}
        backend, model = llm.get("backend") or "", llm.get("model") or ""
        if llm.get("ready"):
            console.print(f"  Model  {escape(backend)} · {escape(model)} · [green]ready[/green]", soft_wrap=True)
        else:
            # Name the half that is missing: nothing ships a default model, so
            # "API key missing" was the wrong diagnosis on every fresh install.
            reason, fix = {
                "no_model": ("no model configured",
                             "choose one in Settings → Models, or set AUGHOR_CODER_MODEL "
                             "and AUGHOR_NARRATOR_MODEL in .env"),
                "no_key": ("API key missing",
                           f"add the {escape(backend) or 'backend'} key in Settings → Models, or in .env"),
            }.get(llm.get("reason"), ("not configured",
                                      "set one up in Settings → Models, or in .env"))
            console.print(f"  Model  [yellow]{reason}[/yellow]: {fix}", soft_wrap=True)
        # No demo data is the DEFAULT state, not a fault — nothing is seeded on boot.
        if health.get("fixture_db"):
            console.print("  Data   demo dataset loaded", soft_wrap=True)
        else:
            console.print("  Data   no demo data: connect your own with [bold]+ Add[/bold] in the app, "
                          "or run [bold]uv run aughor seed[/bold] for a demo dataset", soft_wrap=True)
    console.print()
    if logs is not None:
        console.print(f"  [dim]Server logs are in {escape(_display_path(logs))}[/dim]", soft_wrap=True)
    if next_time:
        console.print(f"  [dim]{escape(next_time)}[/dim]", soft_wrap=True)
    console.print("  Press [bold]Ctrl+C[/bold] to stop Aughor.")
    console.print()


def _signal_quietly(proc: subprocess.Popen, method: str) -> None:
    """terminate()/kill() tolerant of the child exiting in the same instant."""
    try:
        getattr(proc, method)()
    except OSError as exc:
        _ = exc  # already gone — nothing left to stop


def _terminate(procs: list[subprocess.Popen], grace: float = 5.0) -> None:
    """Stop every still-running child: terminate → wait up to `grace`s → kill. On Windows the
    whole process tree: TerminateProcess ends ONE process, and a server's own children would
    keep holding its port."""
    live = [p for p in procs if p.poll() is None]
    for p in live:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            _signal_quietly(p, "terminate")
    deadline = time.monotonic() + grace
    for p in live:
        try:
            p.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _signal_quietly(p, "kill")
            p.wait()


def _supervise(procs: list[subprocess.Popen]) -> subprocess.Popen:
    """Wait in the foreground until one server exits, and return it (the caller stops the rest)."""
    while True:
        for p in procs:
            if p.poll() is not None:
                return p
        time.sleep(0.5)


def _raise_sigterm(signum, frame):  # pragma: no cover — signal plumbing
    raise KeyboardInterrupt


_DOCTOR_MARK = {"ok": "[green]ok[/green]", "warn": "[yellow]warn[/yellow]",
                "fail": "[red]FAIL[/red]", "unknown": "[yellow]?[/yellow]"}


@cli.command()
@click.option("--api-port", default=8000, show_default=True, type=int, help="Port the API uses")
@click.option("--web-port", default=3000, show_default=True, type=int, help="Port the web app uses")
def doctor(api_port: int, web_port: int) -> None:
    """Check this install: uv, Python, Node, both ports, the state dir, PATH and the model.

    Answers WITHOUT a model call and WITHOUT a warehouse query, and writes nothing — including
    no store. Exit code 0 when everything is ok, 1 when any check failed, 2 when something
    could not be determined.
    """
    from aughor import doctor as _doctor
    checks = _doctor.run(_repo_root(), api_port=api_port, web_port=web_port)
    width = max(len(c.name) for c in checks)
    for c in checks:
        console.print(f"  {_DOCTOR_MARK[c.status]:<18} [bold]{c.name:<{width}}[/bold]  {c.found}")
        if not c.ok:
            if c.reason:
                console.print(f"     {' ' * width}   [dim]{c.reason}[/dim]", soft_wrap=True)
            if c.fix:
                console.print(f"     {' ' * width}   [cyan]{c.fix}[/cyan]", soft_wrap=True)
    verdict = _doctor.worst(checks)
    if verdict == _doctor.OK:
        console.print("\n[green]Everything checks out.[/green]")
    else:
        console.print(f"\n{sum(1 for c in checks if not c.ok)} of {len(checks)} need attention.")
    raise SystemExit({"ok": 0, "warn": 0, "fail": 1, "unknown": 2}[verdict])


@cli.command()
@click.option("--ref", default=None, help="Update to this ref instead of the tracked upstream.")
@click.option("--skip-build", is_flag=True, help="Fetch and fast-forward only; skip re-running the install steps.")
def update(ref: Optional[str], skip_build: bool) -> None:
    """Fetch and fast-forward this checkout, then re-run the install steps.

    A diverged checkout is REFUSED and named, never reset. Local changes outside `data/` are
    refused too; `data/` itself is state the app writes, so changes there never block.
    """
    from aughor import update as _update

    root = _repo_root()
    result = _update.update(root, ref=ref)

    if result.status == "refused":
        console.print(f"[yellow]Refused.[/yellow] {result.reason}")
        for line in result.blocking[:10]:
            console.print(f"    [dim]{line}[/dim]")
        raise SystemExit(1)
    if result.status == "failed":
        console.print(f"[red]Failed.[/red] {result.reason}")
        raise SystemExit(1)
    if result.status == "noop":
        console.print(f"[green]Nothing to do.[/green] {result.reason} ({result.before[:8]})")
        return

    console.print(f"[green]Updated.[/green] {result.before[:8]} → {result.after[:8]} "
                  f"({result.reason})")
    if skip_build:
        console.print("[dim]Install steps skipped (--skip-build). Run ./install.sh to finish.[/dim]")
        return

    # The code moved, so its dependencies and its built frontend are now the OLD ones. This is
    # the half that makes `update` mean "this install is new", rather than "git moved".
    from aughor.installer import Steps, prepare_web, sync_python
    steps = Steps()
    try:
        sync_python(root, steps)
        prepare_web(root, steps)
    except Exception as exc:                       # noqa: BLE001 — reported with its next action
        console.print(f"[red]The code updated, but the install steps failed:[/red] {exc}")
        console.print("[cyan]Run ./install.sh to finish.[/cyan]")
        raise SystemExit(1) from None
    console.print("[green]Dependencies and web build are up to date.[/green]")


@cli.command("migrate-state")
@click.option("--from", "source", default=None, type=click.Path(path_type=Path),
              help="The data/ directory to migrate (default: this checkout's).")
@click.option("--yes", is_flag=True, help="Do it, rather than showing what would move.")
def migrate_state(source: Optional[Path], yes: bool) -> None:
    """Move generated state out of the checkout into the per-user data home.

    Copies, verifies, and only then records the move. NOTHING is deleted — the originals stay
    exactly where they are until you remove them yourself. Stop the API first: this refuses to
    run beside a live writer.
    """
    from aughor.db import home as _home
    from aughor.db import migrate as _migrate

    src = Path(source) if source else _repo_root() / "data"
    if _home.in_use():
        console.print(f"[green]Already migrated.[/green] State lives in {_home.state_home()}.")
        return
    if not src.is_dir():
        console.print(f"[red]Nothing at {src} to migrate.[/red]")
        raise SystemExit(1)

    moving, staying = _migrate.sources(src)
    console.print(f"[bold]From[/bold] {src}\n[bold]To[/bold]   {_home.state_home()}\n")
    console.print(f"  {len(moving)} entries would move, {len(staying)} authored entries stay:")
    for entry in moving[:12]:
        console.print(f"    [cyan]move[/cyan]  {entry.name}")
    if len(moving) > 12:
        console.print(f"    [dim]… and {len(moving) - 12} more[/dim]")
    for name in staying:
        console.print(f"    [dim]stay  {name}  (tracked in the repo)[/dim]")
    if not yes:
        console.print("\n[yellow]Nothing done.[/yellow] Re-run with --yes once the API is stopped.")
        return

    out = _migrate.migrate(src)
    if out.status == "refused":
        console.print(f"\n[red]Refused.[/red] {out.reason}")
        raise SystemExit(1)
    if out.status == "failed":
        console.print(f"\n[red]Failed.[/red] {out.reason}")
        for problem in out.problems[:10]:
            console.print(f"  [red]•[/red] {problem}")
        raise SystemExit(1)
    console.print(f"\n[green]Done.[/green] {out.reason}")


@cli.command()
@click.option("--api-port", default=8000, show_default=True, type=int, help="Port for the API")
@click.option("--web-port", default=3000, show_default=True, type=int, help="Port for the web app")
@click.option("--dev", is_flag=True,
              help="Development mode: hot reload for the API and the web app, their logs in this terminal")
@click.option("--api-only", is_flag=True, help="Start only the API")
@click.option("--web-only", is_flag=True, help="Start only the web app")
@click.option("--no-browser", is_flag=True, help="Don't open the web app in a browser")
@click.option("--verbose", "-v", is_flag=True, help="Show install, build and server output in this terminal")
def up(api_port: int, web_port: int, dev: bool, api_only: bool, web_only: bool,
       no_browser: bool, verbose: bool):
    """Start Aughor — the API and the web app — with one command.

    Installs whatever the web app is missing first (its packages, a fresh production build),
    refuses to touch a port another program owns, waits until both servers answer, opens the
    web app in your browser and says what is left to set up. Server logs go to .aughor/logs/
    (--dev and --verbose show them here instead). No data is created on your behalf — run
    `aughor seed` for the demo dataset. Ctrl+C stops everything.
    """
    from aughor import installer

    if api_only and web_only:
        raise click.UsageError("--api-only and --web-only are mutually exclusive.")

    root = _repo_root()
    run_api, run_web = not web_only, not api_only
    steps = installer.Steps(verbose=verbose, show_up_to_date=False)
    if not os.environ.get("AUGHOR_INSTALLER"):  # started by the installer, its list continues
        steps.header("Aughor")

    if run_api:
        _check_port_free(api_port, "the Aughor API", "--api-port", web_port=web_port if run_web else None)
    if run_web:
        _check_port_free(web_port, "the web app", "--web-port")

    node, web_env = None, None
    if run_web:
        try:
            node, web_env = installer.prepare_web(root, steps, api_port=api_port, build=not dev)
        except installer.InstallError as error:
            steps.failure(error)
            sys.exit(1)
        except KeyboardInterrupt:
            steps.line()
            sys.exit(130)

    # Server output goes to files, so the terminal keeps to what a person needs — unless they
    # asked to watch it, and then a spinner would only scribble over it.
    logs = None if (dev or verbose) else installer.log_dir(root)
    steps.verbose = logs is None
    api_log = logs / "api.log" if logs is not None else None
    web_log = logs / "web.log" if logs is not None else None
    label, done = {(True, True): ("Starting Aughor", "Aughor started"),
                   (True, False): ("Starting the API", "API started"),
                   (False, True): ("Starting the web app", "Web app started")}[(run_api, run_web)]

    procs: list[subprocess.Popen] = []
    api_proc: Optional[subprocess.Popen] = None
    # docker/CI stop → the same clean path as Ctrl-C. Put back afterwards, so running this
    # command inside a test process does not leave the handler behind.
    previous_sigterm = signal.signal(signal.SIGTERM, _raise_sigterm)
    try:
        health: Optional[dict] = None
        try:
            with steps.working(label, done) as spinner:
                if run_api:
                    # A bounded graceful shutdown. An open browser tab holds a stream to the API,
                    # and without a bound uvicorn waits on it until `_terminate` gives up and
                    # kills the API — skipping its own shutdown (clocks stopped, traces flushed).
                    api_cmd = [sys.executable, "-m", "uvicorn", "aughor.api:app", "--port", str(api_port),
                               "--timeout-graceful-shutdown", "3"]
                    if dev:
                        api_cmd += ["--reload"]
                    api_proc = _launch(api_cmd, cwd=root, env=_api_env(web_port if run_web else None),
                                       log=api_log)
                    procs.append(api_proc)
                web_proc: Optional[subprocess.Popen] = None
                if node is not None and web_env is not None:
                    # Next.js's own CLI under node: no npm layer between Ctrl+C and the server,
                    # and no `.cmd` shim on Windows.
                    web_cmd = [str(node.exe), str(installer.next_bin(root)), "dev" if dev else "start",
                               "-p", str(web_port)]
                    web_proc = _launch(web_cmd, cwd=root / "web", env=node.env(web_env), log=web_log)
                    procs.append(web_proc)
                if api_proc is not None:
                    running_api = api_proc
                    health = _wait_for_health(
                        f"http://127.0.0.1:{api_port}/health",
                        is_alive=lambda: running_api.poll() is None,
                        on_slow=lambda: spinner.update("the first start takes a little longer"))
                    if health is None and running_api.poll() is not None:
                        raise installer.InstallError(
                            f"The API stopped while starting (exit code {running_api.returncode}).",
                            log=api_log, hint="" if api_log else "Its output is above.")
                if web_proc is not None:
                    running_web = web_proc
                    ready = _wait_for_web(web_port, is_alive=lambda: running_web.poll() is None)
                    if not ready and running_web.poll() is not None:
                        raise installer.InstallError(
                            f"The web app stopped while starting (exit code {running_web.returncode}).",
                            log=web_log, hint="" if web_log else "Its output is above.")
        except installer.InstallError as error:
            steps.failure(error)
            sys.exit(1)

        opened = bool(run_web and _should_open_browser(no_browser, dev)
                      and _open_browser(f"http://localhost:{web_port}"))
        if run_api:
            _print_boot_summary(health, api_port, web_port if run_web else None, logs=logs,
                                browser_opened=opened,
                                next_time=installer.start_command_hint() if os.environ.get("AUGHOR_INSTALLER") else "")
        else:
            console.print()
            console.print(f"  [bold]The web app is ready:[/bold] [bold cyan]http://localhost:{web_port}[/bold cyan]"
                          f"  [dim](it expects the API on port {api_port})[/dim]", soft_wrap=True)
            console.print()
            console.print("  Press [bold]Ctrl+C[/bold] to stop it.")
            console.print()

        stopped = _supervise(procs)
        name, log = ("The API", api_log) if stopped is api_proc else ("The web app", web_log)
        steps.failure(installer.InstallError(
            f"{name} stopped unexpectedly (exit code {stopped.returncode}), so Aughor is stopping too.",
            log=log))
        sys.exit(stopped.returncode or 1)
    except KeyboardInterrupt:
        steps.line()
        with steps.working("Stopping Aughor", "Aughor stopped"):
            _terminate(procs, grace=10.0)
        sys.exit(0)
    finally:
        _terminate(procs, grace=10.0)
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)


# ── Investigate ──────────────────────────────────────────────────────────────

@cli.command()
@click.argument("question")
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to DuckDB file")
@click.option("--model", default=None, help="Override the model (e.g. qwen2.5-coder:14b)")
@click.option("--backend", default="ollama", show_default=True, type=click.Choice(list(LLM_BACKENDS)))
def investigate(question: str, db: str, model: Optional[str], backend: str):
    """Run an autonomous deep analysis on a business question."""
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

    # The deep-analysis path produces a rich answer_report (phases, per-finding SQL,
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
    """Render the rich deep-analysis report: phases, per-finding SQL, key numbers,
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

    # Rule out first (IP-1) — the known ways the stated move can be the data, before the actions
    rule_outs = report.get("rule_outs") or {}
    if rule_outs.get("items"):
        from rich.markup import escape
        console.print("\n[bold]Rule out first[/bold]")
        console.print(f"  [dim]{escape(rule_outs.get('lead') or 'Not checked against your data.')}[/dim]")
        for item in rule_outs["items"]:
            console.print(f"  • {escape(item.get('cause', ''))}")
            if item.get("fix"):
                console.print(f"    [dim]Fix: {escape(item['fix'])}[/dim]")

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


@cli.command(name="graph-export")
@click.argument("connection_id")
@click.option("--out", "out_dir", required=True,
              help="Directory to write the pack into (created if absent)")
@click.option("--schema", default="",
              help="Export one schema (default: every schema of the connection, merged)")
def graph_export(connection_id: str, out_dir: str, schema: str):
    """Export a connection's knowledge graph as a self-contained skills pack (C6).

    The pack is consumed with NO LLM, no API key, and no Aughor running — graph.json plus
    two markdown skills that run the read-back protocol offline. The graph's typed
    freshness state travels with it, so a consumer is warned rather than misled when the
    pack lags the warehouse.

    Requires a graph already built for this connection.
    """
    from aughor.ontology.context_graph_export import export_pack

    pack = export_pack(connection_id, out_dir, schema_name=schema or None)
    if pack is None:
        console.print(f"[red]No committed graph for[/red] {connection_id} "
                      f"(schema={schema or 'any'}).")
        console.print("Build it first (open/explore the connection with [bold]graph.build[/bold] "
                      "on), then retry — an empty pack would answer from nothing.")
        sys.exit(1)

    shape = "  ".join(f"{k}: [bold]{v}[/bold]" for k, v in sorted(pack.counts.items()))
    colour = "green" if pack.staleness == "fresh" else "yellow"
    console.print()
    console.print(Panel(
        f"[bold]{connection_id}[/bold]  schema=[cyan]{schema or '(all, merged)'}[/cyan]\n"
        f"{shape}\n"
        f"freshness: [{colour}]{pack.staleness}[/{colour}]\n"
        f"files: {len(pack.files)}  →  [bold]{pack.root}[/bold]",
        title="[bold cyan]Graph pack exported[/bold cyan]", border_style="cyan", padding=(1, 2),
    ))
    console.print(f"[dim]Install the skills:[/dim] [bold]{pack.root}/install.sh[/bold]")
    console.print("[dim]Or point any agent at the pack — it reads graph.json directly.[/dim]\n")



# ── VA-1 · skills ─────────────────────────────────────────────────────────────
# The ingester without a door is a library nobody can reach; the linter without an
# importer was a gate on a door that did not exist. This is where both become usable.

def _skill_files(target: Path) -> list[Path]:
    """Every SKILL.md under `target`, or the file itself.

    A directory walk rather than one file at a time because the seed import is a
    LIBRARY — decision ② imports every data/analytics skill — and "run this command
    forty times" is the version of this feature that never gets run.
    """
    if target.is_file():
        return [target]
    return sorted(target.rglob("SKILL.md"))


def _render(plan, path: Optional[Path], *, verbose: bool) -> None:
    """One line per skill, plus its findings. BLOCK is red, WARN is yellow — the two
    mean different things and a single colour would flatten a refusal into a note."""
    if plan.blocked:
        console.print(f"  [red]✗ blocked[/red]  {plan.name}")
    elif path is not None:
        console.print(f"  [green]✓ wrote[/green]   {plan.pack_id}  [dim]{path}[/dim]")
    else:
        console.print(f"  [cyan]· planned[/cyan] {plan.pack_id}")
    for f in plan.findings:
        if f.severity.value == "block":
            console.print(f"      [red]{f.rule}[/red] line {f.line}: {f.why}")
        elif verbose:
            console.print(f"      [yellow]{f.rule}[/yellow] line {f.line}: {f.why}")


@cli.group()
def packs():
    """Inspect and promote domain packs."""


@packs.command("list")
@click.option("--packs-dir", default=None, type=Path,
              help="Override the pack root. Defaults to both roots (authored, then imported).")
def packs_list(packs_dir: Path):
    """Every pack on disk with its status — the answer to 'why is nothing steering'."""
    from aughor.packs.loader import load_pack
    from aughor.packs.intake import known_pack_ids

    from aughor.packs.roots import authored_root, imported_root, pack_dir

    ids = known_pack_ids(packs_dir)
    if not ids:
        console.print(f"[yellow]no packs in {authored_root()} or {imported_root()}[/yellow]")
        return
    for pid in ids:
        root = Path(packs_dir) / pid if packs_dir else pack_dir(pid)
        try:
            pack = load_pack(root)
        except Exception as exc:
            console.print(f"  [red]✗ {pid}[/red]: {exc}")
            continue
        m = pack.manifest
        colour = {"active": "green", "draft": "yellow"}.get(m.status, "dim")
        flags = " ".join(filter(None, [
            "[dim]prose-only[/dim]" if m.partial else "",
            f"[dim]{m.source}[/dim]" if m.source else "",
            "[dim](imported)[/dim]" if root and root.parent == imported_root() else "",
        ]))
        console.print(f"  [{colour}]{m.status:<10}[/{colour}] {pid}  {flags}")
    console.print(f"\n{len(ids)} pack(s). Only [green]active[/green] ones are readable "
                  f"by an agent or selectable for steering.")


@packs.command("check")
@click.argument("pack_id")
def packs_check(pack_id: str):
    """IP-3 — run the static gate (gate 3) on PACK_ID: sources, sourced sane ranges, formulas over roles, no alias
    collision, bound plays, goldens and datasets. Exits 1 on any finding. A pack that does not declare
    `anatomy: 1` is not held to it."""
    from aughor.packs.gate3 import applies, run_gate3
    from aughor.packs.loader import PacksError, load_pack
    from aughor.packs.roots import pack_dir

    folder = pack_dir(pack_id)
    if folder is None:
        console.print(f"[red]✗[/red] no pack {pack_id!r} in either pack root")
        sys.exit(1)
    try:
        pack = load_pack(folder)
    except PacksError as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)
    if not applies(pack):
        console.print(f"[yellow]{pack_id} does not declare anatomy: 1 — the static gate does not hold it[/yellow]")
        return
    report = run_gate3(pack)
    for line in report.lines():
        console.print(f"  [red]✗[/red] {line}")
    if not report.ok:
        console.print(f"\n[red]{len(report.findings)} finding(s)[/red] — gate 3 fails for {pack_id}")
        sys.exit(1)
    console.print(f"[green]✓[/green] gate 3 passes for {pack_id}: {len(pack.metrics)} metrics, "
                  f"{len(pack.playbooks)} plays, {len(pack.evals)} goldens, {len(pack.sources)} sources, "
                  f"{len(pack.datasets)} dataset(s)")


@packs.command("measure")
@click.argument("pack_id")
@click.option("--dataset", "dataset_id", default="", help="The dataset to measure on (default: the package's first).")
@click.option("--download", is_flag=True, help="Download the dataset into the cache if it is not there yet.")
@click.option("--write", is_flag=True, help="Store the receipt as measurements/<dataset>.json inside the package.")
def packs_measure(pack_id: str, dataset_id: str, download: bool, write: bool):
    """IP-3 — run gate 4 on PACK_ID: measure its recipes, goldens, detections and ontology claims on a named public
    dataset, with no model. Exits 1 on any finding."""
    import os

    # A measurement reads a public file; it records nothing in this deployment's stores.
    os.environ.setdefault("AUGHOR_KERNEL_EVENTS", "0")
    from aughor.packs.gate3 import applies, run_gate3
    from aughor.packs.gate4 import Gate4Error, run_gate4, write_receipt
    from aughor.packs.loader import PacksError, load_pack
    from aughor.packs.roots import pack_dir

    folder = pack_dir(pack_id)
    if folder is None:
        console.print(f"[red]✗[/red] no pack {pack_id!r} in either pack root")
        sys.exit(1)
    try:
        pack = load_pack(folder)
    except PacksError as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)
    if not applies(pack) or not run_gate3(pack).ok:
        console.print(f"[red]✗[/red] {pack_id} must pass gate 3 first: aughor packs check {pack_id}")
        sys.exit(1)
    try:
        report = run_gate4(pack, dataset_id, download=download)
    except Gate4Error as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)
    console.print(f"[bold]{pack_id}[/bold] on [bold]{report.dataset_id}[/bold] "
                  f"({', '.join(f'{t} {n:,}' for t, n in report.rows.items())})")
    for m in report.metrics:
        mark = "[green]✓[/green]" if m.in_range else "[red]✗[/red]"
        console.print(f"  {mark} {m.metric} = {m.value}  [dim]sane [{m.sane_min}, {m.sane_max}][/dim]")
    passed = sum(g.ok for g in report.goldens)
    console.print(f"  goldens: {passed} of {len(report.goldens)} reproduce their published figure")
    for g in report.goldens:
        if not g.ok:
            console.print(f"    [red]✗[/red] {g.question} — measured {g.measured}, published {g.expected}")
    for d in report.detections:
        console.print(f"  detection {d.play}: {d.count if d.error == '' else 'error — ' + d.error}")
    console.print(f"  claims: {report.claims_by_tier}")
    for line in report.findings:
        console.print(f"  [red]✗[/red] {line}")
    if write:
        console.print(f"[dim]receipt: {write_receipt(pack, report)}[/dim]")
    if not report.ok:
        sys.exit(1)
    console.print(f"[green]✓[/green] gate 4 passes for {pack_id}")


@packs.command("promote")
@click.argument("pack_id")
@click.option("--packs-dir", default=None, type=Path,
              help="Override the pack root. Defaults to both roots (authored, then imported).")
@click.option("--actor", default="", help="Who is promoting it. Recorded on the journal.")
def packs_promote(pack_id: str, packs_dir: Path, actor: str):
    """Make PACK_ID active — the point at which its prose can reach a prompt.

    The import gate runs again HERE, over the pack's prose, because this is the door the
    prose actually passes through: import is a copy onto disk, and a hand-placed pack
    never passed the importer at all.
    """
    from aughor.packs.promote import PromotionRefused, set_status

    try:
        pack = set_status(pack_id, "active", packs_dir=packs_dir, actor=actor)
    except PromotionRefused as exc:
        console.print(f"[red]refused[/red] {exc}")
        for f in exc.findings:
            if f.severity.value == "block":
                console.print(f"    [red]{f.rule}[/red] line {f.line}: {f.why}")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]✓ active[/green] {pack_id}")
    if pack.manifest.partial:
        console.print("[dim]This pack is prose only — it declares no entities or metrics, "
                      "so it can be READ by an agent but will never steer a plan.[/dim]")


@packs.command("demote")
@click.argument("pack_id")
@click.option("--packs-dir", default=None, type=Path,
              help="Override the pack root. Defaults to both roots (authored, then imported).")
@click.option("--status", type=click.Choice(["draft", "deprecated"]), default="draft",
              show_default=True)
@click.option("--actor", default="")
def packs_demote(pack_id: str, packs_dir: Path, status: str, actor: str):
    """Take PACK_ID out of service. `deprecated` is not a delete — its history stays."""
    from aughor.packs.promote import set_status

    try:
        set_status(pack_id, status, packs_dir=packs_dir, actor=actor)
    except Exception as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)
    console.print(f"[yellow]✓ {status}[/yellow] {pack_id}")


@cli.command()
@click.argument("choice", nargs=-1)
def industries(choice: tuple):
    """Which industry packages Aughor reads (IP-2) — the question the installer asked.

    With no argument, lists the shipped industries and the current choice. `aughor industries retail saas`
    keeps only those (numbers from the list and package names work too), `aughor industries all` keeps
    every one with each connection's industry detected, and `aughor industries none` keeps only the
    knowledge every industry shares. Settings > Organization changes the same choice.
    """
    from aughor.business_profile.metric_kb import refresh_profiles_for_choice
    from aughor.installer import Industry, parse_industries
    from aughor.packs.industry_choice import choice_path, describe, read_choice, shipped_industries, write_choice
    from aughor.packs.knowledge import packages

    shipped = shipped_industries()
    current = read_choice()
    if not choice:
        if not shipped:
            console.print("[yellow]No industry packages ship with this checkout.[/yellow]")
            return
        width = len(str(len(shipped)))
        for number, industry in enumerate(shipped, 1):
            kept = current.industries is None or industry.id in current.industries
            mark = "[green]✓[/green]" if kept else "[dim]·[/dim]"
            console.print(f"  {mark} {str(number).rjust(width)}  {industry.name}  [dim]{industry.id}[/dim]")
        console.print(f"\nIndustries: {describe(current)}"
                      + (f"  [dim]({current.source}, {current.updated_at})[/dim]" if current.source else ""))
        if current.ignored:
            console.print(f"[yellow]Ignored — no package carries: {', '.join(current.ignored)}[/yellow]")
        if current.problem:
            console.print(f"[yellow]{current.problem}[/yellow]")
        console.print(f"[dim]{choice_path()}[/dim]")
        return

    folders = {p.industry: p.pack_id for p in packages() if p.layer == "industry" and p.industry}
    options = [Industry(id=i.id, name=i.name, pack=folders.get(i.id, i.id)) for i in shipped]
    try:
        chosen = parse_industries(" ".join(choice), options)
        after = write_choice(chosen, source="cli")
    except ValueError as exc:   # an answer no package matches (UnknownIndustry is one too)
        console.print(f"[red]✗[/red] {exc} Industries are: {', '.join(i.id for i in shipped)} — or all, or none.")
        sys.exit(1)
    refreshed = 0
    if current.industries != after.industries:
        refreshed = refresh_profiles_for_choice(current.industries, after.industries)
    console.print(f"[green]✓[/green] Industries: {describe(after)}")
    if refreshed:
        console.print(f"[dim]{refreshed} business profile(s) resolved to a different package and will be "
                      f"rebuilt the next time their data is used.[/dim]")


@cli.group()
def skills():
    """Import third-party agent skills (SKILL.md) as packs."""


@skills.command("lint")
@click.argument("target", type=click.Path(exists=True, path_type=Path))
def skills_lint(target: Path):
    """Report what the import gate would say about TARGET. Writes nothing."""
    from aughor.skills.ingest import SkillIngestError, plan_pack

    files = _skill_files(target)
    if not files:
        console.print(f"[yellow]no SKILL.md under {target}[/yellow]")
        return
    blocked = 0
    for f in files:
        try:
            plan = plan_pack(f.read_text(), source_url=str(f))
        except SkillIngestError as exc:
            console.print(f"  [red]✗ unreadable[/red] {f}: {exc}")
            blocked += 1
            continue
        blocked += bool(plan.blocked)
        _render(plan, None, verbose=True)
    console.print(f"\n{len(files)} skill(s) · [red]{blocked} blocked[/red]")
    if blocked:
        sys.exit(1)


@skills.command("import")
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option("--packs-dir", default=None, type=Path,
              help="Override the pack root. Defaults to both roots (authored, then imported).")
@click.option("--namespace", default="",
              help="Prefix every pack id. Skill names in the wild are generic — a real "
                   "library here produced 'access' three times from three plugins.")
@click.option("--licence", default="",
              help="Licence of the source library. Recorded on every pack; a missing "
                   "one is a warning, because redistributed prose needs its terms known.")
@click.option("--source", default="", help="Name of the source library.")
@click.option("--source-url", default="",
              help="UPSTREAM base URL of the checkout, e.g. "
                   "https://github.com/google/skills/tree/main. Recorded per pack with the "
                   "file's path appended. Without it the provenance is a local path, which "
                   "is not attribution and is meaningless on any other machine.")
@click.option("--dry-run", is_flag=True, help="Show what would be created; write nothing.")
@click.option("--overwrite", is_flag=True, help="Replace packs that already exist.")
def skills_import(target: Path, packs_dir: Path, namespace: str, licence: str,
                  source: str, source_url: str, dry_run: bool, overwrite: bool):
    """Import SKILL.md files under TARGET as packs.

    TARGET is a path — a file or a directory. A URL is NOT accepted: fetching untrusted
    prose over the network is a materially different risk surface from reading a file
    the user already chose to put on their disk, and it wants its own allowlist and
    review path. `git clone` then point this at the checkout.

    Every pack lands `status: draft` and `partial: true`. Nothing imported reaches a
    prompt until someone promotes it.

    Writes to the UNTRACKED imported root by default, never into the tracked `packs/`
    directory: this repo is public, and redistributing a few dozen third-party documents
    inside it is a decision to take deliberately rather than as a side effect of running
    an importer. `--packs-dir` overrides that if you mean to.
    """
    from aughor.skills.ingest import DEFAULT_SOURCE, SkillIngestError, ingest_skill, plan_pack

    if packs_dir is None:
        from aughor.packs.roots import imported_root
        packs_dir = imported_root()
        packs_dir.mkdir(parents=True, exist_ok=True)

    files = _skill_files(target)
    if not files:
        console.print(f"[yellow]no SKILL.md under {target}[/yellow]")
        return
    console.print(f"[dim]writing to {packs_dir}[/dim]")

    root = target if target.is_dir() else target.parent

    def _origin(f: Path) -> str:
        """Where this skill came FROM, not where it happens to sit on this disk."""
        if not source_url:
            return str(f)
        try:
            rel = f.relative_to(root)
        except ValueError:
            rel = Path(f.name)
        return f"{source_url.rstrip('/')}/{rel}"

    wrote = blocked = failed = 0
    for f in files:
        kwargs = dict(source=source or DEFAULT_SOURCE, source_url=_origin(f),
                      licence=licence, namespace=namespace)
        try:
            if dry_run:
                _render(plan_pack(f.read_text(), **kwargs), None, verbose=True)
                continue
            path, plan = ingest_skill(f.read_text(), packs_dir,
                                      overwrite=overwrite, **kwargs)
        except SkillIngestError as exc:
            # A collision lands here, and it is the common case on a real library.
            console.print(f"  [red]✗ {f.parent.name}[/red]: {exc}")
            failed += 1
            continue
        blocked += bool(plan.blocked)
        wrote += path is not None
        _render(plan, path, verbose=False)

    if dry_run:
        console.print(f"\n[dim]dry run — nothing written.[/dim] {len(files)} skill(s) read.")
        return
    console.print(f"\n{len(files)} skill(s) · [green]{wrote} written[/green] · "
                  f"[red]{blocked} blocked[/red] · {failed} could not be written")
    if wrote:
        console.print("[dim]All imported packs are status=draft — promote one to make "
                      "it active.[/dim]")


if __name__ == "__main__":
    cli()
