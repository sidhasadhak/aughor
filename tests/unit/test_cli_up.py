"""`aughor up` — arg surface, preflight, and the start sequence.

No real servers: every test either exercises argument parsing (CliRunner) or replaces the
port, install, spawn and wait helpers, so nothing binds a port, installs a package or
launches a server (except the _terminate tests, which spawn a sleeping python child on no port
at all and reap it). A test that runs the start sequence does it from a throwaway checkout,
so the logs folder it creates is never the repository's.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import aughor.cli as cli_mod
from aughor import installer

REPO = Path(__file__).resolve().parents[2]


def _must_not(what: str):
    def refuse(*args, **kwargs):
        raise AssertionError(f"up must not {what}")
    return refuse


def _checkout(root: Path) -> Path:
    (root / "pyproject.toml").write_text('[project]\nname = "aughor"\n')
    (root / "web").mkdir()
    return root


# ── Argument surface ──────────────────────────────────────────────────────────

def test_up_command_exists_with_expected_flags():
    r = CliRunner().invoke(cli_mod.cli, ["up", "--help"])
    assert r.exit_code == 0, r.output
    for flag in ("--api-port", "--web-port", "--dev", "--api-only", "--web-only", "--no-browser", "--verbose"):
        assert flag in r.output, f"missing {flag} in `aughor up --help`"


def test_up_api_only_and_web_only_are_mutually_exclusive():
    r = CliRunner().invoke(cli_mod.cli, ["up", "--api-only", "--web-only"])
    assert r.exit_code != 0
    assert "mutually exclusive" in r.output


def test_up_listed_in_group_help():
    r = CliRunner().invoke(cli_mod.cli, ["--help"])
    assert r.exit_code == 0
    assert "up" in r.output


# ── Backend choices (investigate) stay in sync with the provider ─────────────

def test_llm_backends_mirror_matches_provider():
    """cli.LLM_BACKENDS is a literal mirror (keeps --help import-light); this
    pins it to the canonical list so the two can never drift."""
    from aughor.llm.provider import BACKENDS
    assert tuple(cli_mod.LLM_BACKENDS) == tuple(BACKENDS)


def test_investigate_accepts_all_backends():
    r = CliRunner().invoke(cli_mod.cli, ["investigate", "--help"])
    assert r.exit_code == 0
    assert "gemini" in cli_mod.LLM_BACKENDS       # the newest backend is exposed on the CLI
    for backend in cli_mod.LLM_BACKENDS:
        assert backend in r.output, f"--backend missing choice {backend}"


# ── Port-busy preflight: report + exit 1, never kill, never spawn ────────────

def test_up_busy_port_exits_1_without_spawning(monkeypatch, tmp_path):
    monkeypatch.chdir(_checkout(tmp_path))
    monkeypatch.setattr(cli_mod, "_port_in_use", lambda port: True)
    monkeypatch.setattr(cli_mod, "_port_owner", lambda port: "uvicorn (pid 12345)")
    monkeypatch.setattr(cli_mod, "_aughor_answers", lambda port: False)
    monkeypatch.setattr(cli_mod, "_launch", _must_not("spawn anything when the port is busy"))
    monkeypatch.setattr(installer, "prepare_web", _must_not("install anything when the port is busy"))

    r = CliRunner().invoke(cli_mod.cli, ["up"])
    assert r.exit_code == 1
    assert "8000" in r.output
    assert "uvicorn (pid 12345)" in r.output
    assert "--api-port" in r.output
    assert "kill" in r.output.lower()  # says it won't kill the owner


def test_up_busy_web_port_reports_web_flag(monkeypatch, tmp_path):
    # API port free, web port busy → the message must point at --web-port.
    monkeypatch.chdir(_checkout(tmp_path))
    monkeypatch.setattr(cli_mod, "_port_in_use", lambda port: port == 3000)
    monkeypatch.setattr(cli_mod, "_port_owner", lambda port: "")
    monkeypatch.setattr(cli_mod, "_launch", _must_not("spawn anything when the port is busy"))
    monkeypatch.setattr(installer, "prepare_web", _must_not("install anything when the port is busy"))

    r = CliRunner().invoke(cli_mod.cli, ["up"])
    assert r.exit_code == 1
    assert "3000" in r.output
    assert "--web-port" in r.output


def test_a_second_up_says_aughor_is_already_running(monkeypatch, tmp_path):
    """Running the installer again while Aughor runs is the common case, and 'port 8000 is in
    use' reads like a clash with something else. Say what it is, and where to find it."""
    monkeypatch.chdir(_checkout(tmp_path))
    monkeypatch.setattr(cli_mod, "_port_in_use", lambda port: port == 8000)
    monkeypatch.setattr(cli_mod, "_port_owner", lambda port: "python3.11 (pid 82038)")
    monkeypatch.setattr(cli_mod, "_aughor_answers", lambda port: True)
    monkeypatch.setattr(cli_mod, "_launch", _must_not("spawn anything"))
    monkeypatch.setattr(installer, "prepare_web", _must_not("install anything"))

    r = CliRunner().invoke(cli_mod.cli, ["up"])
    assert r.exit_code == 1
    assert "Aughor is already running" in r.output
    assert "http://localhost:3000" in r.output
    assert "--api-port" in r.output


# ── The start sequence ────────────────────────────────────────────────────────

class _FakeServer:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.pid = 4242

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def started(tmp_path, monkeypatch):
    """`aughor up` with every side effect replaced: ports free, the web app 'prepared', servers
    'launched' as fakes that answer at once, and Ctrl+C the moment it starts supervising."""
    root = _checkout(tmp_path)
    monkeypatch.chdir(root)
    for var in ("AUGHOR_INSTALLER", "AUGHOR_CORS_ORIGINS", "NEXT_PUBLIC_API_URL", "AUGHOR_API_BASE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli_mod, "_port_in_use", lambda port: False)

    prepared: dict = {}
    node = installer.Node(tmp_path / "node-bin" / "node", (24, 0, 0))

    def fake_prepare(root, steps, *, api_port, build):
        prepared.update(api_port=api_port, build=build)
        return node, installer.web_env(api_port)

    monkeypatch.setattr(installer, "prepare_web", fake_prepare)
    launched: list = []

    def fake_launch(cmd, *, cwd, env=None, log=None):
        launched.append({"cmd": [str(part) for part in cmd], "cwd": cwd, "env": env or {}, "log": log})
        return _FakeServer()

    monkeypatch.setattr(cli_mod, "_launch", fake_launch)
    monkeypatch.setattr(cli_mod, "_wait_for_health", lambda url, **kw: {
        "status": "ok", "fixture_db": False, "llm": {"backend": "ollama", "model": "m", "ready": True}})
    monkeypatch.setattr(cli_mod, "_wait_for_web", lambda port, **kw: True)
    opened: list = []
    monkeypatch.setattr(cli_mod, "_should_open_browser", lambda no_browser, dev: not (no_browser or dev))
    monkeypatch.setattr(cli_mod, "_open_browser", lambda url: opened.append(url) or True)

    def ctrl_c(procs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_mod, "_supervise", ctrl_c)
    return SimpleNamespace(root=root, prepared=prepared, launched=launched, opened=opened)


def test_up_serves_a_production_build_with_logs_in_files(started):
    r = CliRunner().invoke(cli_mod.cli, ["up"])
    assert r.exit_code == 0, r.output
    assert started.prepared == {"api_port": 8000, "build": True}
    api, web = started.launched
    assert api["cmd"][1:4] == ["-m", "uvicorn", "aughor.api:app"]
    assert "--reload" not in api["cmd"]
    assert web["cmd"][-3:] == ["start", "-p", "3000"]
    assert web["cmd"][1].endswith(str(Path("next") / "dist" / "bin" / "next")), "next's CLI under node, no npm"
    assert web["cwd"] == started.root / "web"
    assert api["log"] == started.root / ".aughor" / "logs" / "api.log"
    assert web["log"] == started.root / ".aughor" / "logs" / "web.log"
    assert api["env"]["PYTHONUNBUFFERED"] == "1", "a failure is read back from a current log"
    assert api["cmd"][api["cmd"].index("--timeout-graceful-shutdown") + 1] == "3", (
        "measured live: with a browser tab open, an unbounded shutdown waited on its event "
        "stream until Ctrl+C fell through to a kill")
    assert "Aughor started" in r.output
    assert "http://localhost:3000" in r.output
    assert "Aughor stopped" in r.output
    assert started.opened == ["http://localhost:3000"]


def test_dev_mode_hot_reloads_and_keeps_the_logs_in_the_terminal(started):
    r = CliRunner().invoke(cli_mod.cli, ["up", "--dev"])
    assert r.exit_code == 0, r.output
    assert started.prepared["build"] is False, "hot reload needs no production build"
    api, web = started.launched
    assert "--reload" in api["cmd"]
    assert web["cmd"][-3:] == ["dev", "-p", "3000"]
    assert api["log"] is None and web["log"] is None
    assert started.opened == [], "dev mode restarts all day; no new tab each time"


def test_moved_ports_are_wired_through_to_both_servers(started):
    r = CliRunner().invoke(cli_mod.cli, ["up", "--api-port", "8010", "--web-port", "3010", "--no-browser"])
    assert r.exit_code == 0, r.output
    api, web = started.launched
    assert api["cmd"][api["cmd"].index("--port") + 1] == "8010"
    assert "http://localhost:3010" in api["env"]["AUGHOR_CORS_ORIGINS"].split(","), \
        "without it the browser refuses every request the moved web app makes"
    assert web["cmd"][-2:] == ["-p", "3010"]
    assert web["env"]["NEXT_PUBLIC_API_URL"] == "http://localhost:8010"
    assert web["env"]["AUGHOR_API_BASE"] == "http://127.0.0.1:8010"
    assert started.opened == []


def test_a_cors_list_the_user_set_is_left_alone(started, monkeypatch):
    monkeypatch.setenv("AUGHOR_CORS_ORIGINS", "https://aughor.example.com")
    CliRunner().invoke(cli_mod.cli, ["up", "--web-port", "3010"])
    assert started.launched[0]["env"]["AUGHOR_CORS_ORIGINS"] == "https://aughor.example.com"


def test_api_only_installs_nothing_for_the_web(started, monkeypatch):
    monkeypatch.setattr(installer, "prepare_web", _must_not("prepare the web app for --api-only"))
    r = CliRunner().invoke(cli_mod.cli, ["up", "--api-only"])
    assert r.exit_code == 0, r.output
    assert len(started.launched) == 1
    assert "API started" in r.output


def test_an_api_that_dies_while_starting_shows_why(started, monkeypatch):
    def dying(cmd, *, cwd, env=None, log=None):
        if log is not None:
            log.write_text("Traceback (most recent call last):\nModuleNotFoundError: No module named 'duckdb'\n")
        return _FakeServer(returncode=1)

    monkeypatch.setattr(cli_mod, "_launch", dying)
    monkeypatch.setattr(cli_mod, "_wait_for_health", lambda url, **kw: None)
    r = CliRunner().invoke(cli_mod.cli, ["up", "--api-only"])
    assert r.exit_code == 1
    assert "The API stopped while starting (exit code 1)" in r.output
    assert "No module named 'duckdb'" in r.output, "the reason, from the end of its log"
    assert "api.log" in r.output


def test_a_failed_web_install_starts_nothing(started, monkeypatch):
    def broken(root, steps, **kw):
        raise installer.InstallError("npm exited with code 1.", hint="Fix what the log shows")

    monkeypatch.setattr(installer, "prepare_web", broken)
    monkeypatch.setattr(cli_mod, "_launch", _must_not("start a server after a failed install"))
    r = CliRunner().invoke(cli_mod.cli, ["up"])
    assert r.exit_code == 1
    assert "npm exited with code 1." in r.output


def test_a_server_that_stops_later_takes_the_rest_down_and_says_why(started, monkeypatch):
    monkeypatch.setattr(cli_mod, "_supervise", lambda procs: SimpleNamespace(returncode=137))
    r = CliRunner().invoke(cli_mod.cli, ["up", "--no-browser"])
    assert r.exit_code == 137
    assert "stopped unexpectedly (exit code 137)" in r.output


def test_the_browser_opens_only_where_a_person_can_see_it(monkeypatch):
    def decide(platform="darwin", tty=True, no_browser=False, dev=False, **env):
        for var in ("CI", "SSH_CONNECTION", "SSH_TTY", "DISPLAY", "WAYLAND_DISPLAY"):
            monkeypatch.delenv(var, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(cli_mod, "sys", SimpleNamespace(platform=platform,
                                                           stdout=SimpleNamespace(isatty=lambda: tty)))
        return cli_mod._should_open_browser(no_browser, dev)

    assert decide() is True
    assert decide(no_browser=True) is False
    assert decide(dev=True) is False
    assert decide(tty=False) is False
    assert decide(CI="true") is False
    assert decide(SSH_CONNECTION="10.0.0.1 50000 10.0.0.2 22") is False
    assert decide(platform="linux") is False, "no display: webbrowser would open a text browser here"
    assert decide(platform="linux", DISPLAY=":0") is True


def test_the_cors_defaults_mirror_the_api():
    """The mirror exists so a moved web port is ADDED to the API's defaults; a mirror that
    drifted would silently drop an origin the API itself accepts."""
    assert f'"{cli_mod._DEFAULT_CORS_ORIGINS}"' in (REPO / "aughor" / "api.py").read_text(encoding="utf-8")


def test_a_narrow_output_encoding_cannot_crash_the_summary():
    """Measured on the Windows CI job: output redirected to a file encodes as cp1252, which has
    no "→"; the summary raised UnicodeEncodeError the moment both servers were up, and the
    cleanup stopped them. Runs with and without the guard, so the test can fail."""
    script = ("import aughor.cli as cli, aughor.installer as installer\n"
              "{guard}"
              "cli._print_boot_summary({{'status': 'ok', 'llm': {{'ready': False, 'reason': 'no_model'}}}},"
              " 8000, 3000)\n")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "AUGHOR_SKIP_DOTENV": "1"}

    def run(guard: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", script.format(guard=guard)], cwd=REPO, env=env,
                              capture_output=True, text=True, encoding="cp1252", errors="replace",
                              timeout=120)

    unguarded = run("")
    assert unguarded.returncode != 0 and "UnicodeEncodeError" in unguarded.stderr, \
        "the reproduction no longer reproduces; the guard below proves nothing"
    guarded = run("installer.tolerate_narrow_output()\n")
    assert guarded.returncode == 0, guarded.stderr
    assert "Settings ? Models" in guarded.stdout


# ── Helper behaviours ─────────────────────────────────────────────────────────

def test_port_in_use_detects_a_real_listener():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))     # ephemeral port, closed on exit
        s.listen(1)
        port = s.getsockname()[1]
        assert cli_mod._port_in_use(port) is True
    assert cli_mod._port_in_use(port) is False


def test_repo_root_prefers_cwd_when_it_is_a_checkout(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "web").mkdir()
    monkeypatch.chdir(tmp_path)
    assert cli_mod._repo_root() == tmp_path


def test_repo_root_falls_back_to_package_parent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # bare dir: no pyproject.toml/web
    root = cli_mod._repo_root()
    assert (root / "aughor").is_dir()
    assert (root / "pyproject.toml").is_file()


def test_wait_for_health_short_circuits_when_process_dies():
    out = cli_mod._wait_for_health(
        "http://127.0.0.1:1/health", timeout=5.0, is_alive=lambda: False
    )
    assert out is None


def test_wait_for_health_returns_health_json(monkeypatch):
    import httpx

    class _Resp:
        status_code = 200
        def json(self):
            return {"status": "ok", "fixture_db": True, "llm": {"ready": True}}

    monkeypatch.setattr(httpx, "get", lambda url, timeout: _Resp())
    out = cli_mod._wait_for_health("http://127.0.0.1:1/health", timeout=5.0)
    assert out == {"status": "ok", "fixture_db": True, "llm": {"ready": True}}


def test_a_slow_api_start_is_reported_once():
    told: list = []
    out = cli_mod._wait_for_health("http://127.0.0.1:1/health", timeout=1.2,
                                   on_slow=lambda: told.append(1), slow_after=0.0)
    assert out is None
    assert told == [1]


def test_wait_for_web_sees_a_listener():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        assert cli_mod._wait_for_web(s.getsockname()[1], timeout=5.0) is True


def test_wait_for_web_stops_waiting_when_the_server_dies():
    assert cli_mod._wait_for_web(1, timeout=5.0, is_alive=lambda: False) is False


def test_terminate_stops_children():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        cli_mod._terminate([proc], grace=5.0)
        assert proc.poll() is not None, "child still running after _terminate"
    finally:
        if proc.poll() is None:  # safety net if the assertion above failed
            proc.kill()
            proc.wait()


def test_terminate_tolerates_already_exited_children():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    cli_mod._terminate([proc])  # must not raise


# ── Boot summary: LLM readiness messaging ─────────────────────────────────────

def test_boot_summary_points_at_settings_when_llm_not_ready(capsys):
    health = {
        "status": "ok",
        "fixture_db": True,
        "llm": {"backend": "groq", "model": "llama-3.3-70b-versatile",
                "key_present": False, "ready": False, "reason": "no_key"},
    }
    cli_mod._print_boot_summary(health, 8000, 3000)
    out = capsys.readouterr().out
    assert "API key missing" in out
    assert "Settings → Models" in out, "the settings tab is called Models (web/app/page.tsx)"
    assert "groq" in out


def test_boot_summary_names_a_missing_model_rather_than_blaming_the_key(capsys):
    """The shipped default. Ollama needs no key and no model ships, so the summary used
    to say "ready"; once it stopped, the hardcoded reason blamed a key that was never
    required. Name the half that is actually missing, and say where to set it."""
    health = {
        "status": "ok",
        "fixture_db": False,
        "llm": {"backend": "ollama", "model": "", "key_present": True,
                "ready": False, "reason": "no_model"},
    }
    cli_mod._print_boot_summary(health, 8000, 3000)
    out = capsys.readouterr().out
    assert "no model configured" in out
    assert "API key missing" not in out, "ollama needs no key — do not blame one"
    assert "AUGHOR_CODER_MODEL" in out


def test_boot_summary_treats_absent_demo_data_as_normal(capsys):
    """Nothing seeds on boot, so no demo data is the default state — the summary must
    report it plainly and name the opt-in, not warn about a failure."""
    health = {"status": "ok", "fixture_db": False,
              "llm": {"backend": "ollama", "model": "m", "key_present": True,
                      "ready": True, "reason": None}}
    cli_mod._print_boot_summary(health, 8000, 3000)
    out = capsys.readouterr().out
    assert "no demo data" in out
    assert "aughor seed" in out
    assert "not seeded yet" not in out, "absence is the default, not a problem to flag"


def test_boot_summary_reports_ready_llm(capsys):
    health = {
        "status": "ok",
        "fixture_db": True,
        "llm": {"backend": "ollama", "model": "qwen2.5-coder:14b",
                "key_present": True, "ready": True},
    }
    cli_mod._print_boot_summary(health, 8000, 3000)
    out = capsys.readouterr().out
    assert "ready" in out
    assert "http://localhost:8000" in out
    assert "http://localhost:3000" in out


def test_boot_summary_says_where_the_logs_are_and_how_to_start_again(capsys, tmp_path):
    cli_mod._print_boot_summary({"status": "ok"}, 8000, 3000, logs=tmp_path / "logs",
                                next_time="Next time, start Aughor with:  uv run aughor up")
    out = capsys.readouterr().out
    assert str(tmp_path / "logs") in out
    assert "uv run aughor up" in out
    assert "Ctrl+C" in out


@pytest.mark.parametrize("health", [None, {"status": "ok"}])
def test_boot_summary_degrades_on_missing_fields(health, capsys):
    cli_mod._print_boot_summary(health, 8000, None)  # must not raise
    out = capsys.readouterr().out
    assert "http://localhost:8000" in out
