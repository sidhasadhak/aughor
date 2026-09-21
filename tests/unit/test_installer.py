"""`aughor.installer` — the one-shot install every OS runs.

Hermetic: no network, no uv, no npm. Real child processes appear only where the behaviour
under test IS the child-process handling (output kept off the terminal, a failure's tail);
every download, package manager and build is replaced at its seam.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from aughor import installer

REPO = Path(__file__).resolve().parents[2]


@contextmanager
def _no_terminal():
    yield None


@pytest.fixture(autouse=True)
def _no_question_unless_a_test_scripts_one(tmp_path, monkeypatch):
    """IP-2 — `main()` asks which industries through /dev/tty, and the conftest's packs copy ships six. Run
    from a terminal, pytest would sit waiting for a person. Every test starts with no terminal and its own
    choice file; the tests about the question script a terminal of their own."""
    monkeypatch.setattr(installer, "_terminal", _no_terminal)
    monkeypatch.setenv("AUGHOR_INDUSTRIES_FILE", str(tmp_path / "state" / "industries.json"))
    monkeypatch.delenv("AUGHOR_INDUSTRIES", raising=False)


@pytest.fixture(autouse=True)
def _no_launcher_on_the_real_path(tmp_path, monkeypatch):
    """`main()` writes the `aughor` command into uv's command folder. Every test points that
    folder at a temp dir, so no test can put a launcher on the developer's real PATH."""
    monkeypatch.setattr(installer, "launcher_dir", lambda uv: tmp_path / "uv-bin")
    monkeypatch.delenv("AUGHOR_LAUNCHER", raising=False)


# ── It runs before anything is installed ─────────────────────────────────────────

def test_the_installer_imports_only_the_standard_library():
    """It runs on a bare interpreter BEFORE `uv sync`. A third-party import passes every test
    on a developer's machine — the package is installed there — and breaks the first install
    on every fresh one. Walks nested imports too: a lazy `import rich` inside the download
    path would not surface until a machine without Node.js ran it."""
    # `update.py` too: the installer imports it (relatively) to fast-forward an existing clone,
    # so a third-party import there would break every fresh install exactly as one here would.
    imported: set[str] = set()
    for tree in (ast.parse((REPO / "aughor" / name).read_text(encoding="utf-8"))
                 for name in ("installer.py", "update.py")):
      for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert {"subprocess", "urllib", "tarfile"} <= imported, "the import walk found nothing to check"
    outside = sorted(name for name in imported
                     if name != "__future__" and name not in sys.stdlib_module_names)
    assert not outside, f"aughor/installer.py imports {outside}, which a fresh machine does not have yet"


def test_the_installer_starts_with_no_site_packages_at_all():
    """The same property, observed rather than parsed: `-S` hides every installed package."""
    out = subprocess.run([sys.executable, "-S", "-m", "aughor.installer", "--help"],
                         cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "--no-start" in out.stdout


# ── One line per step ────────────────────────────────────────────────────────────

class _Terminal(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def test_a_step_keeps_the_tools_output_off_the_terminal(tmp_path, capsys):
    log = tmp_path / "step.log"
    installer.Steps().run(
        "Installing things", "Things installed",
        [sys.executable, "-c", "print('left-pad==1.3.0'); print('added 962 packages')"],
        cwd=tmp_path, log=log)
    out = capsys.readouterr().out
    assert "Things installed" in out
    assert "left-pad" not in out and "962" not in out, "package names belong in the log"
    assert "left-pad==1.3.0" in log.read_text()


def test_a_failed_step_shows_the_end_of_its_log_and_where_the_rest_is(tmp_path, capsys):
    log = tmp_path / "step.log"
    steps = installer.Steps()
    script = ("import sys\n"
              "for i in range(60): print(f'resolving {i}')\n"
              "print('npm error ERESOLVE could not resolve')\n"
              "sys.exit(3)")
    with pytest.raises(installer.InstallError) as caught:
        steps.run("Installing web app dependencies", "Web app dependencies installed",
                  [sys.executable, "-c", script], cwd=tmp_path, log=log, tool="npm")
    steps.failure(caught.value)
    out = capsys.readouterr().out
    assert "Installing web app dependencies failed" in out
    assert "npm exited with code 3." in out, "named for the tool, not the node running it"
    assert "npm error ERESOLVE could not resolve" in out, "the reason is in the tail"
    assert "resolving 0" not in out, "the tail, not the whole log"
    assert str(log) in out
    assert "Web app dependencies installed" not in out


def test_verbose_shows_the_output_and_still_logs_it(tmp_path, capsys):
    log = tmp_path / "step.log"
    installer.Steps(verbose=True).run("Building", "Built", [sys.executable, "-c", "print('route /chat')"],
                                      cwd=tmp_path, log=log)
    assert "route /chat" in capsys.readouterr().out
    assert "route /chat" in log.read_text()


def test_the_spinner_is_gone_before_the_result_line(tmp_path, monkeypatch):
    terminal = _Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    monkeypatch.setenv("NO_COLOR", "1")
    installer.Steps().run("Building the web app", "Web app built",
                          [sys.executable, "-c", "import time; time.sleep(0.3)"],
                          cwd=tmp_path, log=tmp_path / "build.log")
    text = terminal.getvalue()
    assert "\r" in text, "a live terminal gets a spinner redrawn in place"
    assert text.split("\r")[-1] == "  ✓ Web app built\n"


def test_a_step_that_had_nothing_to_do_is_silent_when_asked(capsys):
    installer.Steps(show_up_to_date=False).up_to_date("Web app up to date")
    assert capsys.readouterr().out == ""
    installer.Steps().up_to_date("Web app up to date")
    assert "Web app up to date" in capsys.readouterr().out


# ── Node.js ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("v24.14.1\n", (24, 14, 1)),
    ("v20.9.0", (20, 9, 0)),
    ("", None),
    ("node: command not found", None),
])
def test_parse_node_version(text, expected):
    assert installer.parse_node_version(text) == expected


@pytest.mark.parametrize("system,machine,name", [
    ("Darwin", "arm64", "node-v24.21.0-darwin-arm64.tar.xz"),
    ("Darwin", "x86_64", "node-v24.21.0-darwin-x64.tar.xz"),
    ("Linux", "x86_64", "node-v24.21.0-linux-x64.tar.xz"),
    ("Linux", "aarch64", "node-v24.21.0-linux-arm64.tar.xz"),
    ("Windows", "AMD64", "node-v24.21.0-win-x64.zip"),
    ("Windows", "ARM64", "node-v24.21.0-win-arm64.zip"),
])
def test_node_archive_names_match_nodejs_org(system, machine, name):
    """Spelled as nodejs.org spells them in its SHASUMS256.txt — checked against the real
    listing for v24.21.0 when this test was written."""
    assert installer.node_dist_filename("v24.21.0", system, machine) == name


def test_a_python_without_lzma_downloads_the_gzip_archive():
    assert installer.node_dist_filename("v24.21.0", "Linux", "x86_64", xz=False) == \
        "node-v24.21.0-linux-x64.tar.gz"


def test_a_computer_nodejs_org_does_not_build_for_gets_a_clear_message():
    with pytest.raises(installer.InstallError, match="can't download Node.js") as caught:
        installer.node_dist_filename("v24.21.0", "FreeBSD", "amd64")
    assert "nodejs.org" in caught.value.hint


def test_a_download_whose_checksum_does_not_match_is_refused(tmp_path):
    archive = tmp_path / "node-v24.21.0-linux-x64.tar.xz"
    archive.write_bytes(b"not really node")
    listing = (f"{'1' * 64}  node-v24.21.0-win-x64.zip\n"
               f"{'0' * 64}  node-v24.21.0-linux-x64.tar.xz\n")
    wrong = installer.expected_sha256(listing, archive.name)
    assert wrong == "0" * 64, "picked the row for this file, not the first row"
    with pytest.raises(installer.InstallError, match="checksum"):
        installer.verify_sha256(archive, wrong)
    installer.verify_sha256(archive, hashlib.sha256(b"not really node").hexdigest())


def test_a_listing_without_the_file_is_an_error_not_a_skip():
    with pytest.raises(installer.InstallError, match="no checksum"):
        installer.expected_sha256(f"{'0' * 64}  something-else.zip\n", "node-v24.21.0-win-x64.zip")


def test_an_archive_entry_that_escapes_its_folder_is_refused(tmp_path):
    payload = tmp_path / "payload.txt"
    payload.write_text("x")
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tf:
        tf.add(payload, arcname="../escaped.txt")
    (tmp_path / "out").mkdir()
    with pytest.raises(installer.InstallError, match="outside"):
        installer.extract_archive(evil, tmp_path / "out" / "node")
    assert not (tmp_path / "out" / "escaped.txt").exists()


def test_zip_and_tar_archives_unpack(tmp_path):
    zipped = tmp_path / "node-v1.2.3-win-x64.zip"
    with zipfile.ZipFile(zipped, "w") as zf:
        zf.writestr("node-v1.2.3-win-x64/node.exe", "binary")
    installer.extract_archive(zipped, tmp_path / "zip")
    assert (tmp_path / "zip" / "node-v1.2.3-win-x64" / "node.exe").read_text() == "binary"

    binary = tmp_path / "node"
    binary.write_text("binary")
    tarred = tmp_path / "node-v1.2.3-linux-x64.tar.gz"
    with tarfile.open(tarred, "w:gz") as tf:
        tf.add(binary, arcname="node-v1.2.3-linux-x64/bin/node")
    installer.extract_archive(tarred, tmp_path / "tar")
    assert (tmp_path / "tar" / "node-v1.2.3-linux-x64" / "bin" / "node").read_text() == "binary"


def _file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def test_the_first_new_enough_node_wins(tmp_path, monkeypatch):
    old, new, newer = (_file(tmp_path / name / "node") for name in ("old", "new", "newer"))
    versions = {old: (18, 19, 0), new: (20, 9, 0), newer: (24, 0, 0)}
    monkeypatch.setattr(installer, "node_candidates", lambda root: [old, new, newer])
    monkeypatch.setattr(installer, "node_version", versions.get)
    node, _ = installer.find_node(tmp_path)
    assert node is not None and node.exe == new, "preference order, not the highest version"
    assert not node.downloaded


def test_when_every_node_is_too_old_the_newest_is_named(tmp_path, monkeypatch):
    a, b = _file(tmp_path / "a" / "node"), _file(tmp_path / "b" / "node")
    versions = {a: (16, 0, 0), b: (18, 19, 0)}
    monkeypatch.setattr(installer, "node_candidates", lambda root: [a, b])
    monkeypatch.setattr(installer, "node_version", versions.get)
    assert installer.find_node(tmp_path) == (None, (18, 19, 0))


def test_no_usable_node_means_aughor_downloads_its_own(tmp_path, monkeypatch, capsys):
    fetched = installer.Node(tmp_path / "node", (24, 21, 0), downloaded=True)
    monkeypatch.setattr(installer, "find_node", lambda root: (None, (18, 0, 0)))
    monkeypatch.setattr(installer, "download_node", lambda root, steps: fetched)
    assert installer.ensure_node(tmp_path, installer.Steps()) is fetched
    assert "Node.js 18.0.0 is older than Aughor needs" in capsys.readouterr().out


def test_forcing_the_download_ignores_every_installed_node(tmp_path, monkeypatch):
    """CI's switch for exercising the download path on runners that all ship a Node.js."""
    fake = _file(tmp_path / "bin" / "node")
    monkeypatch.setattr(installer.shutil, "which", lambda name: str(fake))
    monkeypatch.setenv("AUGHOR_NODE_DOWNLOAD", "1")
    assert installer.node_candidates(tmp_path) == []
    downloaded = _file(tmp_path / ".aughor" / "node" / "node-v24.21.0-linux-x64" / "bin" / "node")
    if sys.platform != "win32":
        assert installer.node_candidates(tmp_path) == [downloaded]


@pytest.mark.parametrize("layout", ["posix", "windows"])
def test_npm_runs_with_the_same_node(tmp_path, layout):
    """Through that Node's own npm-cli.js — not an `npm` shim that picks a Node off PATH."""
    if layout == "posix":
        exe = _file(tmp_path / "bin" / "node")
        cli = _file(tmp_path / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
    else:
        exe = _file(tmp_path / "node.exe")
        cli = _file(tmp_path / "node_modules" / "npm" / "bin" / "npm-cli.js")
    assert installer.Node(exe, (24, 0, 0)).npm() == [str(exe), str(cli)]


def test_the_node_in_use_comes_first_on_path(tmp_path):
    exe = tmp_path / "bin" / "node"
    env = installer.Node(exe, (24, 0, 0)).env({"PATH": "/usr/bin"})
    assert env["PATH"].split(installer.os.pathsep)[0] == str(exe.parent)


# ── Python dependencies ──────────────────────────────────────────────────────────

def test_python_dependencies_come_from_the_lock_with_every_extra(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(installer.Steps, "run",
                        lambda self, label, done, cmd, **kw: calls.append((label, list(cmd), kw["env"])))
    monkeypatch.setenv("UV", "/fake/uv")
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/throwaway-installer-env")
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)

    installer.sync_python(tmp_path, installer.Steps())
    label, cmd, env = calls[-1]
    assert cmd[:4] == ["/fake/uv", "sync", "--all-extras", "--locked"]
    assert cmd[-2:] == ["--python", installer.PYTHON_VERSION], "a NEW environment gets the version CI tests"
    assert label == "Installing Python dependencies"
    assert "VIRTUAL_ENV" not in env, "uv would warn that the installer's own env is not .venv"

    (tmp_path / ".venv").mkdir()
    installer.sync_python(tmp_path, installer.Steps())
    assert "--python" not in calls[-1][1], "an existing .venv is never rebuilt onto another Python"
    assert calls[-1][0] == "Checking Python dependencies"


# ── The web app ──────────────────────────────────────────────────────────────────

def _web(root: Path) -> Path:
    web = root / "web"
    web.mkdir()
    (web / "package.json").write_text("{}")
    (web / "package-lock.json").write_text('{"lockfileVersion": 3}')
    return web


def test_web_dependencies_install_once_per_lockfile(tmp_path, monkeypatch):
    web = _web(tmp_path)
    runs: list = []

    def fake_run(self, label, done, cmd, **kw):
        runs.append(list(cmd))
        assert kw.get("tool") == "npm", "a failure must name npm, not the node that ran it"
        (web / "node_modules").mkdir(exist_ok=True)

    monkeypatch.setattr(installer.Steps, "run", fake_run)
    monkeypatch.setattr(installer.Node, "npm", lambda self: ["npm"])
    node, steps = installer.Node(tmp_path / "node", (24, 0, 0)), installer.Steps()

    assert installer.ensure_web_deps(tmp_path, node, steps) is True
    assert runs[-1] == ["npm", "ci", "--no-audit", "--no-fund"], "`ci` never rewrites the lockfile"
    assert installer.ensure_web_deps(tmp_path, node, steps) is False, "same lockfile, nothing to do"
    (web / "package-lock.json").write_text('{"lockfileVersion": 3, "packages": {"new": {}}}')
    assert installer.ensure_web_deps(tmp_path, node, steps) is True
    assert len(runs) == 2


def test_the_build_fingerprint_follows_what_the_build_reads_and_nothing_else(tmp_path):
    web = _web(tmp_path)
    (web / "page.tsx").write_text("export default 1")
    env = {"PATH": "/usr/bin"}
    first = installer.build_fingerprint(tmp_path, env)
    assert installer.build_fingerprint(tmp_path, env) == first

    for generated in (".next/BUILD_ID", "node_modules/next/index.js", "next-env.d.ts"):
        _file(web / generated).write_text("generated")
    assert installer.build_fingerprint(tmp_path, env) == first, "build output and packages are not inputs"
    assert installer.build_fingerprint(tmp_path, {**env, "AUGHOR_API_BASE": "x"}) == first, \
        "a value read at run time needs no rebuild"
    assert installer.build_fingerprint(tmp_path, {**env, "NEXT_PUBLIC_API_URL": "http://localhost:8010"}) != first, \
        "NEXT_PUBLIC_* is baked into the bundle"

    (web / ".env.local").write_text("NEXT_PUBLIC_DEMO_PACK=1")
    assert installer.build_fingerprint(tmp_path, env) != first, "gitignored, but still a build input"
    (web / ".env.local").unlink()
    (web / "page.tsx").write_text("export default 2")
    assert installer.build_fingerprint(tmp_path, env) != first


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_in_a_checkout_the_fingerprint_skips_what_gitignore_skips(tmp_path):
    web = _web(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (web / ".gitignore").write_text("/generated-by-build/\n")
    (web / "page.tsx").write_text("a")
    first = installer.build_fingerprint(tmp_path, {})
    _file(web / "generated-by-build" / "chunk.js").write_text("output")
    assert installer.build_fingerprint(tmp_path, {}) == first
    (web / "new-component.tsx").write_text("uncommitted, but real")
    assert installer.build_fingerprint(tmp_path, {}) != first, "an untracked source still counts"


def test_the_web_app_builds_only_when_its_inputs_change(tmp_path, monkeypatch):
    web = _web(tmp_path)
    (web / "page.tsx").write_text("a")
    builds: list = []

    def fake_build(self, label, done, cmd, **kw):
        builds.append([str(part) for part in cmd])
        _file(web / ".next" / "BUILD_ID").write_text("id")

    monkeypatch.setattr(installer.Steps, "run", fake_build)
    node, steps = installer.Node(tmp_path / "node", (24, 0, 0)), installer.Steps()
    env = installer.web_env(8000, base={})

    assert installer.ensure_web_build(tmp_path, node, steps, env) is True
    assert builds[-1][-1] == "build" and builds[-1][1].endswith("next")
    assert installer.ensure_web_build(tmp_path, node, steps, env) is False
    (web / "page.tsx").write_text("b")
    assert installer.ensure_web_build(tmp_path, node, steps, env) is True
    shutil.rmtree(web / ".next")
    assert installer.ensure_web_build(tmp_path, node, steps, env) is True, "a deleted build is rebuilt"
    assert installer.ensure_web_build(tmp_path, node, steps, installer.web_env(8010, base={})) is True, \
        "a moved API port changes the bundle"


def test_a_moved_api_port_reaches_the_bundle_and_the_chat_proxy():
    moved = installer.web_env(8010, base={})
    assert moved["NEXT_PUBLIC_API_URL"] == "http://localhost:8010"      # web/lib/config.ts, build time
    assert moved["AUGHOR_API_BASE"] == "http://127.0.0.1:8010"          # web/lib/chatProxy.ts, run time
    assert moved["NEXT_TELEMETRY_DISABLED"] == "1"
    default = installer.web_env(8000, base={})
    assert "NEXT_PUBLIC_API_URL" not in default and "AUGHOR_API_BASE" not in default
    mine = installer.web_env(8010, base={"NEXT_PUBLIC_API_URL": "https://api.example.com",
                                         "NEXT_TELEMETRY_DISABLED": "0"})
    assert mine["NEXT_PUBLIC_API_URL"] == "https://api.example.com", "the user's own value wins"
    assert mine["NEXT_TELEMETRY_DISABLED"] == "0"


# ── The whole run ────────────────────────────────────────────────────────────────

def test_the_next_time_hint_names_what_this_terminal_is_missing(monkeypatch):
    """Measured on the `curl | sh` path: the clone lands in ./aughor while the terminal stays in
    the parent, where a bare `uv run aughor up` fails. And a just-installed uv is on PATH only
    in a new terminal."""
    monkeypatch.delenv("AUGHOR_UV_INSTALLED", raising=False)
    monkeypatch.delenv("AUGHOR_CHECKOUT_DIR", raising=False)
    assert installer.start_command_hint() == "Next time, start Aughor with:  uv run aughor up"
    monkeypatch.setenv("AUGHOR_CHECKOUT_DIR", "/home/me/aughor")
    assert installer.start_command_hint() == "Next time, go to /home/me/aughor and run:  uv run aughor up"
    monkeypatch.setenv("AUGHOR_UV_INSTALLED", "1")
    assert installer.start_command_hint() == \
        "Next time, open a new terminal, go to /home/me/aughor and run:  uv run aughor up"
    assert "&&" not in installer.start_command_hint(), "Windows PowerShell 5.1 has no &&"


def _checkout(root: Path) -> Path:
    (root / "pyproject.toml").write_text('[project]\nname = "aughor"\n')
    _web(root)
    return root


def test_install_only_does_every_step_and_does_not_start(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_checkout(tmp_path))
    order: list = []
    monkeypatch.setattr(installer, "sync_python", lambda root, steps: order.append("python"))
    monkeypatch.setattr(installer, "prepare_web", lambda root, steps, **kw: order.append(("web", kw)))
    monkeypatch.setattr(installer, "_hand_off", lambda root, args: pytest.fail("--no-start must not start"))
    assert installer.main(["--no-start", "--api-port", "8010"]) == 0
    assert order == ["python", ("web", {"api_port": 8010, "build": True})]
    assert "Aughor is installed" in capsys.readouterr().out


def test_the_installer_hands_its_options_to_aughor_up(tmp_path, monkeypatch):
    monkeypatch.chdir(_checkout(tmp_path))
    monkeypatch.setattr(installer, "sync_python", lambda root, steps: None)
    monkeypatch.setattr(installer, "prepare_web", lambda root, steps, **kw: None)
    handed: dict = {}
    monkeypatch.setattr(installer, "_hand_off", lambda root, args: handed.update(args=list(args)) or 0)
    assert installer.main(["--web-port", "3010", "--no-browser"]) == 0
    assert handed["args"] == ["--web-port", "3010", "--no-browser"]


def test_dev_mode_installs_without_a_production_build(tmp_path, monkeypatch):
    monkeypatch.chdir(_checkout(tmp_path))
    seen: dict = {}
    monkeypatch.setattr(installer, "sync_python", lambda root, steps: None)
    monkeypatch.setattr(installer, "prepare_web", lambda root, steps, **kw: seen.update(kw))
    assert installer.main(["--no-start", "--dev"]) == 0
    assert seen["build"] is False


def test_a_failed_step_stops_the_install_with_its_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_checkout(tmp_path))

    def broken(root, steps):
        raise installer.InstallError("uv exited with code 2.", hint="Check your internet connection")

    monkeypatch.setattr(installer, "sync_python", broken)
    monkeypatch.setattr(installer, "prepare_web", lambda *a, **k: pytest.fail("nothing runs after a failure"))
    monkeypatch.setattr(installer, "_hand_off", lambda *a: pytest.fail("a failed install must not start"))
    assert installer.main([]) == 1
    out = capsys.readouterr().out
    assert "uv exited with code 2." in out and "Check your internet connection" in out


def test_outside_a_checkout_the_installer_says_where_to_run_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert installer.main(["--no-start"]) == 1
    assert "is not an Aughor checkout" in capsys.readouterr().out


# ── The `aughor` command ─────────────────────────────────────────────────────────

def _fake_uv(folder: Path) -> Path:
    """A `uv` that reports where it ran and what it was asked, instead of running anything."""
    folder.mkdir(parents=True, exist_ok=True)
    uv = folder / "uv"
    uv.write_text('#!/bin/sh\necho "$PWD|$*"\n')
    uv.chmod(0o755)
    return uv


@pytest.mark.skipif(os.name == "nt", reason="runs the POSIX launcher; CI runs the Windows one")
def test_the_aughor_command_starts_aughor_from_any_folder(tmp_path, monkeypatch):
    root = tmp_path / "home" / "aughor"
    root.mkdir(parents=True)
    _checkout(root)
    uv = _fake_uv(tmp_path / "uv-home")
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(installer, "launcher_dir", lambda uv: bin_dir)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), str(uv.parent), "/usr/bin", "/bin"]))
    assert installer.install_launcher(root, str(uv)) == "ready"

    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()

    def aughor(*args):
        return subprocess.run([str(bin_dir / "aughor"), *args], cwd=elsewhere,
                              capture_output=True, text=True, timeout=30)

    where, _, asked = aughor().stdout.strip().partition("|")
    assert Path(where).resolve() == root.resolve(), "runs from the checkout, not the terminal's folder"
    assert asked == "run --quiet aughor up", "no arguments starts Aughor"
    assert aughor("seed").stdout.strip().endswith("|run --quiet aughor seed")

    shutil.rmtree(root)
    gone = aughor()
    assert gone.returncode == 1 and "no longer in" in gone.stderr


def test_someone_elses_aughor_command_is_never_overwritten(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    theirs = bin_dir / ("aughor.cmd" if os.name == "nt" else "aughor")
    theirs.write_text("echo their own aughor\n")
    monkeypatch.setattr(installer, "launcher_dir", lambda uv: bin_dir)
    root = tmp_path / "aughor"
    root.mkdir()
    _checkout(root)
    assert installer.install_launcher(root, str(tmp_path / "uv")) == ""
    assert theirs.read_text() == "echo their own aughor\n"


def test_a_launcher_beside_a_just_installed_uv_works_in_the_next_terminal(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(installer, "launcher_dir", lambda uv: bin_dir)
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))  # this terminal: not yet
    root = tmp_path / "aughor"
    root.mkdir()
    _checkout(root)
    monkeypatch.setenv("AUGHOR_UV_INSTALLED", "1")
    assert installer.install_launcher(root, str(bin_dir / "uv")) == "new-terminal"
    monkeypatch.delenv("AUGHOR_UV_INSTALLED")
    assert installer.install_launcher(root, str(tmp_path / "brew" / "uv")) == "", \
        "a folder no terminal has on PATH gets the checkout's own command instead"


def test_the_windows_command_is_a_plain_cmd_script():
    text = installer.launcher_script(Path("C:/Users/you/aughor"), "C:/Users/you/.local/bin/uv.exe",
                                     windows=True)
    assert text.startswith("@echo off\r\n")
    assert "\n" not in text.replace("\r\n", ""), "cmd.exe needs CRLF line endings"
    assert installer.LAUNCHER_MARK in text
    assert '"%AUGHOR_UV%" run --quiet aughor up' in text
    assert '"%AUGHOR_UV%" run --quiet aughor %*' in text
    assert "(" not in text, "a ( ) block breaks on a folder name with a bracket in it"


def test_next_time_is_one_command_where_the_launcher_reaches(monkeypatch):
    monkeypatch.setenv("AUGHOR_CHECKOUT_DIR", "/home/me/aughor")
    monkeypatch.setenv("AUGHOR_LAUNCHER", "ready")
    assert installer.start_command_hint() == "Next time, start Aughor with:  aughor"
    monkeypatch.setenv("AUGHOR_LAUNCHER", "new-terminal")
    assert installer.start_command_hint() == "Next time, open a new terminal and run:  aughor"
    monkeypatch.setenv("AUGHOR_LAUNCHER", "")
    assert installer.start_command_hint().endswith("uv run aughor up")


def test_the_installer_leaves_the_aughor_command_behind(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(_checkout(tmp_path))
    monkeypatch.setattr(installer, "sync_python", lambda root, steps: None)
    monkeypatch.setattr(installer, "prepare_web", lambda root, steps, **kw: None)
    placed: list = []
    monkeypatch.setattr(installer, "install_launcher", lambda root, uv: placed.append(root) or "ready")
    assert installer.main(["--no-start"]) == 0
    assert placed == [tmp_path]
    assert "Next time, start Aughor with:  aughor" in capsys.readouterr().out


# ── Which industries (IP-2) ──────────────────────────────────────────────────────

def _industry_pack(packs: Path, folder: str, industry: str, name: str, *, status: str = "active",
                   curated: bool = True) -> None:
    d = packs / folder
    d.mkdir(parents=True)
    (d / "pack.yaml").write_text(f"id: {folder}\nname: {name}\ndescription: >\n  A package.\n"
                                 f"layer: industry\nindustry: {industry}\nstatus: {status}\n")
    if curated:
        (d / "industry.json").write_text("{}")


@pytest.fixture()
def two_industries(tmp_path, monkeypatch):
    packs = tmp_path / "packs"
    _industry_pack(packs, "food-delivery", "food_delivery", "Food delivery")
    _industry_pack(packs, "retail", "retail", "Retail and e-commerce")
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(packs))
    (tmp_path / "checkout").mkdir()
    monkeypatch.chdir(_checkout(tmp_path / "checkout"))
    return installer.shipped_industries(Path.cwd())


def _scripted(answers: str, transcript: list):
    @contextmanager
    def terminal():
        reader, writer = io.StringIO(answers), io.StringIO()
        try:
            yield reader, writer
        finally:
            transcript.append(writer.getvalue())
    return terminal


def _recorded() -> object:
    path = Path(os.environ["AUGHOR_INDUSTRIES_FILE"])
    return json.loads(path.read_text(encoding="utf-8"))["industries"] if path.exists() else "nothing"


def test_the_installer_offers_the_industries_the_api_ships():
    from aughor.packs.industry_choice import shipped_industries

    offered = installer.shipped_industries(REPO)
    assert [(i.id, i.name) for i in offered] == [(i.id, i.name) for i in shipped_industries()]
    assert len(offered) == 6


def test_the_installer_writes_the_choice_where_and_how_the_api_reads_it(tmp_path, monkeypatch):
    from aughor.packs import industry_choice

    monkeypatch.delenv("AUGHOR_INDUSTRIES_FILE")
    monkeypatch.delenv("AUGHOR_STATE_DIR", raising=False)
    assert installer.industries_file(tmp_path) == tmp_path / industry_choice.choice_path()   # data/ in the checkout
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    assert installer.industries_file(tmp_path) == industry_choice.choice_path()
    monkeypatch.setenv("AUGHOR_INDUSTRIES_FILE", str(tmp_path / "elsewhere.json"))
    assert installer.industries_file(tmp_path) == industry_choice.choice_path()

    installer.write_industries(industry_choice.choice_path(), ["saas", "retail"])
    choice = industry_choice.read_choice()
    assert (choice.industries, choice.source) == (("retail", "saas"), "installer")


@pytest.mark.parametrize("answer, chosen", [
    ("", None), ("  ", None), ("all", None), ("ALL", None),
    ("none", []),
    ("2", ["retail"]),
    ("1, 2", ["food_delivery", "retail"]),
    ("retail food_delivery", ["food_delivery", "retail"]),
    ("food-delivery", ["food_delivery"]),
    ("Retail and e-commerce, 1", ["food_delivery", "retail"]),
])
def test_an_answer_takes_numbers_ids_folders_and_names(two_industries, answer, chosen):
    assert installer.parse_industries(answer, two_industries) == chosen


@pytest.mark.parametrize("answer", ["3", "banking", "retail, bank"])
def test_an_answer_that_names_no_industry_is_refused(two_industries, answer):
    with pytest.raises(ValueError, match="No industry package is called"):
        installer.parse_industries(answer, two_industries)


def test_a_deprecated_or_uncurated_package_is_not_offered(tmp_path, monkeypatch):
    monkeypatch.delenv("AUGHOR_PACKS_DIR", raising=False)     # the checkout's own packs/ folder
    packs = tmp_path / "packs"
    _industry_pack(packs, "airline", "airline", "Airline", status="deprecated")
    _industry_pack(packs, "rail", "rail", "Rail", curated=False)
    _industry_pack(packs, "saas", "saas", "SaaS")
    (packs / "finance").mkdir()
    (packs / "finance" / "pack.yaml").write_text("id: finance\nlayer: function\n")
    assert [i.id for i in installer.shipped_industries(tmp_path)] == ["saas"]


def test_a_draft_package_is_not_offered_until_it_is_active(tmp_path, monkeypatch):
    """§3.17 gate 6: the API does not read a draft, so the installer does not offer one."""
    monkeypatch.delenv("AUGHOR_PACKS_DIR", raising=False)
    packs = tmp_path / "packs"
    _industry_pack(packs, "banking", "banking", "Banking", status="draft")
    _industry_pack(packs, "saas", "saas", "SaaS")
    assert [i.id for i in installer.shipped_industries(tmp_path)] == ["saas"]


def test_a_comment_is_not_part_of_a_manifest_value(tmp_path, monkeypatch):
    monkeypatch.delenv("AUGHOR_PACKS_DIR", raising=False)
    rail = tmp_path / "packs" / "rail"
    rail.mkdir(parents=True)
    (rail / "pack.yaml").write_text('id: rail\nname: "Rail # freight"\nlayer: industry  # one industry\n'
                                    "industry: rail  # the id the API scopes by\nstatus: active  # reviewed\n")
    (rail / "industry.json").write_text("{}")
    assert installer.shipped_industries(tmp_path) == [installer.Industry(id="rail", name="Rail # freight", pack="rail")]


def test_the_question_comes_before_the_slow_steps_and_is_recorded(two_industries, monkeypatch, capsys):
    transcript: list = []
    order: list = []
    monkeypatch.setattr(installer, "_terminal", _scripted("2\n", transcript))
    monkeypatch.setattr(installer, "sync_python", lambda root, steps: order.append(("python", _recorded())))
    monkeypatch.setattr(installer, "prepare_web", lambda root, steps, **kw: order.append("web"))
    assert installer.main(["--no-start"]) == 0
    assert order == [("python", ["retail"]), "web"]
    assert "Which industries is Aughor for?" in transcript[0] and "2  Retail and e-commerce" in transcript[0]
    assert "Industries: Retail and e-commerce" in capsys.readouterr().out


def test_a_recorded_answer_is_not_asked_again(two_industries, monkeypatch, capsys):
    installer.write_industries(Path(os.environ["AUGHOR_INDUSTRIES_FILE"]), ["food_delivery"])
    monkeypatch.setattr(installer, "_terminal", lambda: pytest.fail("an answered question is not asked again"))
    installer.choose_industries(Path.cwd(), installer.Steps())
    assert "Industries: Food delivery" in capsys.readouterr().out


def test_enter_keeps_every_industry_and_records_that(two_industries, monkeypatch, capsys):
    monkeypatch.setattr(installer, "_terminal", _scripted("\n", []))
    installer.choose_industries(Path.cwd(), installer.Steps())
    assert _recorded() is None
    assert "Industries: every industry, detected per connection" in capsys.readouterr().out


def test_a_wrong_answer_is_asked_again(two_industries, monkeypatch):
    transcript: list = []
    monkeypatch.setattr(installer, "_terminal", _scripted("banking\nretail\n", transcript))
    installer.choose_industries(Path.cwd(), installer.Steps())
    assert _recorded() == ["retail"]
    assert "No industry package is called banking." in transcript[0]


def test_three_wrong_answers_or_a_closed_terminal_record_nothing(two_industries, monkeypatch, capsys):
    for answers in ("x\ny\nz\nretail\n", ""):
        monkeypatch.setattr(installer, "_terminal", _scripted(answers, []))
        installer.choose_industries(Path.cwd(), installer.Steps())
        assert _recorded() == "nothing"
        assert "The next install asks again." in capsys.readouterr().out


@pytest.mark.parametrize("ci, windows, window, names", [
    ("true", False, False, None),                       # a CI job never waits for a person
    ("1", True, True, None),
    ("", True, False, None),                            # GitHub's Windows runner: a console, no window (PR #518)
    ("", True, True, ("CONIN$", "CONOUT$")),
    ("false", False, False, ("/dev/tty", "/dev/tty")),
    ("", False, False, ("/dev/tty", "/dev/tty")),
])
def test_the_question_is_asked_only_where_a_person_can_answer(monkeypatch, ci, windows, window, names):
    monkeypatch.setenv("CI", ci)
    monkeypatch.delenv("TF_BUILD", raising=False)
    monkeypatch.setattr(installer, "_windows", lambda: windows)
    monkeypatch.setattr(installer, "_console_window", lambda: window)
    assert installer._terminal_names() == names


def test_azure_pipelines_counts_as_unattended(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TF_BUILD", "True")
    assert installer._terminal_names() is None


def test_without_a_terminal_nothing_is_asked_or_recorded(two_industries, capsys):
    installer.choose_industries(Path.cwd(), installer.Steps())
    assert _recorded() == "nothing"
    assert "Industries" not in capsys.readouterr().out


def test_the_flag_or_the_environment_answers_without_asking(two_industries, monkeypatch):
    monkeypatch.setattr(installer, "_terminal", lambda: pytest.fail("a given answer is not asked for"))
    monkeypatch.setattr(installer, "sync_python", lambda root, steps: None)
    monkeypatch.setattr(installer, "prepare_web", lambda root, steps, **kw: None)
    assert installer.main(["--no-start", "--industries", "retail,food-delivery"]) == 0
    assert _recorded() == ["food_delivery", "retail"]
    monkeypatch.setenv("AUGHOR_INDUSTRIES", "none")
    assert installer.main(["--no-start"]) == 0
    assert _recorded() == []


def test_an_unknown_industry_stops_the_install_before_anything_slow(two_industries, monkeypatch, capsys):
    monkeypatch.setattr(installer, "sync_python", lambda *a: pytest.fail("nothing slow runs after a refusal"))
    assert installer.main(["--no-start", "--industries", "banking"]) == 1
    out = capsys.readouterr().out
    assert "No industry package is called banking." in out and "food_delivery, retail" in out
    assert _recorded() == "nothing"


def test_the_industries_option_is_not_handed_to_aughor_up(two_industries, monkeypatch):
    monkeypatch.setattr(installer, "sync_python", lambda root, steps: None)
    monkeypatch.setattr(installer, "prepare_web", lambda root, steps, **kw: None)
    handed: dict = {}
    monkeypatch.setattr(installer, "_hand_off", lambda root, args: handed.update(args=list(args)) or 0)
    assert installer.main(["--industries", "retail", "--no-browser", "--industries=all"]) == 0
    assert handed["args"] == ["--no-browser"]

