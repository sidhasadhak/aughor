"""`aughor up` — arg surface + preflight behaviours.

No real servers: every test either exercises argument parsing (CliRunner) or
monkeypatches the port/spawn helpers so nothing binds a port or launches a
process (except the _terminate test, which spawns a sleeping python child on
no port at all and reaps it).
"""
from __future__ import annotations

import subprocess
import sys

import pytest
from click.testing import CliRunner

import aughor.cli as cli_mod


# ── Argument surface ──────────────────────────────────────────────────────────

def test_up_command_exists_with_expected_flags():
    r = CliRunner().invoke(cli_mod.cli, ["up", "--help"])
    assert r.exit_code == 0, r.output
    for flag in ("--api-port", "--web-port", "--dev", "--api-only", "--web-only"):
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


def test_investigate_accepts_all_five_backends():
    r = CliRunner().invoke(cli_mod.cli, ["investigate", "--help"])
    assert r.exit_code == 0
    for backend in cli_mod.LLM_BACKENDS:
        assert backend in r.output, f"--backend missing choice {backend}"


# ── Port-busy preflight: report + exit 1, never kill, never spawn ────────────

def test_up_busy_port_exits_1_without_spawning(monkeypatch):
    monkeypatch.setattr(cli_mod, "_port_in_use", lambda port: True)
    monkeypatch.setattr(cli_mod, "_port_owner", lambda port: "uvicorn (pid 12345)")

    def _no_spawn(*a, **k):
        raise AssertionError("up must not spawn anything when the port is busy")

    monkeypatch.setattr(cli_mod, "_launch", _no_spawn)
    monkeypatch.setattr(cli_mod, "_ensure_web_deps", _no_spawn)

    r = CliRunner().invoke(cli_mod.cli, ["up"])
    assert r.exit_code == 1
    assert "8000" in r.output
    assert "uvicorn (pid 12345)" in r.output
    assert "--api-port" in r.output
    assert "kill" in r.output.lower()  # says it won't kill the owner


def test_up_busy_web_port_reports_web_flag(monkeypatch):
    # API port free, web port busy → the message must point at --web-port.
    monkeypatch.setattr(cli_mod, "_port_in_use", lambda port: port == 3000)
    monkeypatch.setattr(cli_mod, "_port_owner", lambda port: "")

    def _no_spawn(*a, **k):
        raise AssertionError("up must not spawn anything when the port is busy")

    monkeypatch.setattr(cli_mod, "_launch", _no_spawn)
    monkeypatch.setattr(cli_mod, "_ensure_web_deps", _no_spawn)

    r = CliRunner().invoke(cli_mod.cli, ["up"])
    assert r.exit_code == 1
    assert "3000" in r.output
    assert "--web-port" in r.output


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
                "key_present": False, "ready": False},
    }
    cli_mod._print_boot_summary(health, 8000, 3000)
    out = capsys.readouterr().out
    assert "Settings → Inference in the web UI, or set AUGHOR_BACKEND/key envs in .env" in out
    assert "groq" in out


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


@pytest.mark.parametrize("health", [None, {"status": "ok"}])
def test_boot_summary_degrades_on_missing_fields(health, capsys):
    cli_mod._print_boot_summary(health, 8000, None)  # must not raise
    out = capsys.readouterr().out
    assert "http://localhost:8000" in out
