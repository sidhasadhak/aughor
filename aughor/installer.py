"""One-shot install for Aughor: the same steps and the same messages on every OS.

`install.sh` (macOS, Linux) and `install.ps1` (Windows) do only what a shell has to: find
the checkout and get `uv`. They then run this module on a uv-provided Python OUTSIDE the
project's `.venv`, and everything else happens here, once, for all three systems:

  1. Python dependencies    `uv sync --all-extras --locked`
  2. Node.js                the one on this computer when it is new enough; otherwise an
                            official nodejs.org build, checksum-verified, kept in `.aughor/node`
  3. Web app dependencies   `npm ci`, skipped while `web/package-lock.json` is unchanged
  4. The web app            `next build`, skipped while nothing it reads has changed
  5. Start                  hands over to `aughor up`

Each step is one line on the terminal. What the tools print goes to `.aughor/logs/`, and a
log's tail is shown only when its step fails — nobody needs 962 package names scrolling past
to learn that an install worked.

🔴 STANDARD LIBRARY ONLY. This module runs before any dependency exists. One convenience
`import rich` here breaks the first install on every fresh machine, and no developer would
notice, because theirs has rich installed. `tests/unit/test_installer.py` fails instead.

Why outside the `.venv`: `uv sync` sometimes has to recreate that environment, and on Windows
the `python.exe` inside it is locked while it runs — the installer would be deleting its own
interpreter. `aughor up` imports the web half from inside the venv, which is safe: those steps
only run node and npm.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence, Union

#: The Python a NEW `.venv` is created with — the version CI gates every pull request on.
#: An existing `.venv` keeps whatever version it has. Mirrored in install.sh and install.ps1.
PYTHON_VERSION = "3.11"
#: `engines.node` in web/package.json (Next.js 16's floor).
NODE_MIN = (20, 9, 0)
#: The Node.js line downloaded when this computer has none new enough: the Active LTS.
#: Bumped deliberately rather than followed automatically — a new major is a change to test.
NODE_LTS_MAJOR = 24
NODE_DIST = "https://nodejs.org/dist"
#: Where the API listens unless told otherwise; the web app's built-in default matches it.
DEFAULT_API_PORT = 8000

_RETRY = "Fix what the log shows, then run the installer again. It skips everything already done."
_OFFLINE = ("Check your internet connection, then run the installer again. "
            "It skips everything already done.")
_GET_NODE = "Install Node.js 20.9 or newer from https://nodejs.org, then run the installer again."

Label = Union[str, Callable[[], str]]


class InstallError(Exception):
    """A step that could not finish. Its message is written for the person at the terminal."""

    def __init__(self, message: str, *, log: Optional[Path] = None, hint: str = "") -> None:
        super().__init__(message)
        self.log = log
        self.hint = hint


# ── Where things go ──────────────────────────────────────────────────────────────

def runtime_dir(root: Path) -> Path:
    """`.aughor/` in the checkout: a downloaded Node.js and the logs. Gitignored, and deleting
    it costs a re-download, never data."""
    return root / ".aughor"


def log_dir(root: Path) -> Path:
    path = runtime_dir(root) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── The terminal ─────────────────────────────────────────────────────────────────

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_ASCII = "|/-\\"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


@functools.lru_cache(maxsize=None)
def _vt_enabled() -> bool:
    """ANSI colour works on every POSIX terminal; a Windows console has to be switched into
    virtual-terminal mode first, and an old one refuses."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        return False


def tolerate_narrow_output() -> None:
    """Let stdout and stderr write "?" for a character their encoding lacks, instead of raising.

    A stream redirected to a file or pipe on Windows encodes as the ANSI code page (cp1252),
    which has no "→". Measured on the Windows CI job: one in `aughor up`'s closing summary
    raised UnicodeEncodeError the moment both servers were up, and the cleanup that followed
    stopped them. A UTF-8 stream — every macOS and Linux terminal, and Windows' own console
    API — is left untouched.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if hasattr(stream, "reconfigure") and not stream.closed and not encoding.startswith("utf8"):
            stream.reconfigure(errors="replace")


def _format_seconds(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole}s" if whole < 60 else f"{whole // 60}m {whole % 60:02d}s"


class Steps:
    """One line per step, with a spinner while a step runs.

    `sys.stdout` is looked up on every write rather than captured once, so click's CliRunner
    and pytest's capture both see the output.
    """

    def __init__(self, *, verbose: bool = False, show_up_to_date: bool = True) -> None:
        #: Stream each command's output to the terminal as well as to its log.
        self.verbose = verbose
        #: Print a line for a step that had nothing to do. The installer does — its output is
        #: the report of what is in place. `aughor up` does not: it speaks only when it works.
        self.show_up_to_date = show_up_to_date
        self._lock = threading.RLock()
        self._drawn = 0  # length of the spinner text currently on screen

    # What the terminal can do.
    def interactive(self) -> bool:
        isatty = getattr(sys.stdout, "isatty", None)
        return bool(isatty and isatty()) and os.environ.get("TERM") != "dumb"

    def unicode(self) -> bool:
        encoding = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
        if not encoding.startswith("utf8"):
            return False
        if os.name == "nt":
            # Windows Terminal and VS Code draw these glyphs; the classic console's fonts do not.
            return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"))
        return True

    def _paint(self, text: str, sgr: str) -> str:
        if self.interactive() and not os.environ.get("NO_COLOR") and _vt_enabled():
            return f"\x1b[{sgr}m{text}\x1b[0m"
        return text

    def bold(self, text: str) -> str:
        return self._paint(text, "1")

    def dim(self, text: str) -> str:
        return self._paint(text, "2")

    def green(self, text: str) -> str:
        return self._paint(text, "32")

    def red(self, text: str) -> str:
        return self._paint(text, "31")

    @property
    def ellipsis(self) -> str:
        return "…" if self.unicode() else "..."

    def _write(self, text: str) -> None:
        with self._lock:
            stream = sys.stdout
            try:
                stream.write(text)
            except UnicodeEncodeError:
                stream.write(text.encode("ascii", "replace").decode("ascii"))
            stream.flush()

    # Lines.
    def header(self, title: str) -> None:
        self._write(f"\n  {self.bold(title)}\n\n")

    def line(self, text: str = "") -> None:
        self._write(f"  {text}\n" if text else "\n")

    def done(self, label: str, seconds: Optional[float] = None) -> None:
        self._result(self.green("✓" if self.unicode() else "+"), label, seconds)

    def up_to_date(self, label: str) -> None:
        if self.show_up_to_date:
            self.done(label)

    def _result(self, glyph: str, label: str, seconds: Optional[float]) -> None:
        if seconds is not None and seconds >= 1:
            self._write(f"  {glyph} {label.ljust(34)} {self.dim(_format_seconds(seconds))}\n")
        else:
            self._write(f"  {glyph} {label}\n")

    def _cross(self) -> str:
        return self.red("✗" if self.unicode() else "x")

    @contextmanager
    def working(self, label: str, done: Label) -> Iterator["_Spinner"]:
        """Show `label` with a spinner until the block ends, then the `done` line — a callable
        is evaluated at the end, for a result only known then. A failure prints its ✗ line
        here; the caller prints the details with :meth:`failure`."""
        spinner = _Spinner(self, label)
        spinner.start()
        try:
            yield spinner
        except KeyboardInterrupt:
            spinner.stop()
            self._result(self._cross(), f"{spinner.label} — stopped", None)
            raise
        except BaseException:
            spinner.stop()
            self._result(self._cross(), f"{spinner.label} failed", spinner.elapsed())
            raise
        spinner.stop()
        self.done(done() if callable(done) else done, spinner.elapsed())

    def run(self, label: str, done: Label, cmd: Sequence[Union[str, Path]], *, cwd: Path,
            log: Path, env: Optional[dict] = None, hint: str = _RETRY, tool: str = "") -> None:
        """Run one command as one step: its output to `log`, a spinner on the terminal (or,
        with `verbose`, the output as well). `tool` names the command in a failure message
        when the program is not it: npm and Next.js both run as `node <script>`, and "node
        exited with code 1" would send the reader looking in the wrong place."""
        argv = [str(part) for part in cmd]
        tool = tool or Path(argv[0]).name
        log.parent.mkdir(parents=True, exist_ok=True)
        with self.working(label, done):
            with open(log, "w", encoding="utf-8", errors="replace") as out:
                out.write(f"$ {' '.join(argv)}\n# in {cwd}\n\n")
                out.flush()
                try:
                    proc = subprocess.Popen(
                        argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE if self.verbose else out, stderr=subprocess.STDOUT)
                except OSError as exc:
                    raise InstallError(f"Could not run {argv[0]}: {exc}", hint=hint) from exc
                try:
                    if proc.stdout is not None:
                        for raw in proc.stdout:
                            text = raw.decode("utf-8", "replace")
                            out.write(text)
                            self._write(self.dim("    " + text.rstrip("\r\n")) + "\n")
                    code = proc.wait()
                except BaseException:
                    stop_process_tree(proc)
                    raise
            if code != 0:
                raise InstallError(f"{tool} exited with code {code}.", log=log, hint=hint)

    def failure(self, error: InstallError) -> None:
        """What went wrong, the end of the log that shows why, and what to do about it."""
        self.line()
        self.line(self.red(str(error)))
        if error.log is not None and error.log.is_file():
            tail = log_tail(error.log)
            if tail:
                self.line()
                for text in tail:
                    self.line("  " + self.dim(text))
            self.line()
            self.line(f"Full log: {error.log}")
        if error.hint:
            self.line(error.hint)
        self.line()

    # The spinner's drawing, kept here beside the lock that serialises every write.
    def _draw(self, frame: str, spinner: "_Spinner") -> None:
        text = f"{spinner.label}{self.ellipsis}"
        if spinner.detail:
            text += f"  {spinner.detail}"
        if spinner.elapsed() >= 2:
            text += f"  {_format_seconds(spinner.elapsed())}"
        # Never let the line wrap: a wrapped line cannot be redrawn in place.
        text = text[:max(shutil.get_terminal_size((80, 24)).columns - 5, 20)]
        with self._lock:
            self._write(f"\r  {self._paint(frame, '36')} {text}{' ' * max(self._drawn - len(text), 0)}")
            self._drawn = len(text)

    def _erase(self) -> None:
        with self._lock:
            if self._drawn:
                self._write("\r" + " " * (self._drawn + 4) + "\r")
                self._drawn = 0


class _Spinner:
    def __init__(self, steps: Steps, label: str) -> None:
        self.steps = steps
        self.label = label
        self.detail = ""
        self._started = time.monotonic()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def update(self, detail: str) -> None:
        """A short progress note after the label (`38%`). Drawn on a live terminal only — a
        CI log gains nothing from forty percentages."""
        self.detail = detail

    def start(self) -> None:
        steps = self.steps
        if steps.interactive() and not steps.verbose:
            self._thread = threading.Thread(target=self._spin, name="aughor-installer-spinner",
                                            daemon=True)
            self._thread.start()
        else:
            steps.line(f"{steps.dim('•' if steps.unicode() else '-')} {self.label}{steps.ellipsis}")

    def _spin(self) -> None:
        frames = _SPINNER if self.steps.unicode() else _SPINNER_ASCII
        tick = 0
        while True:
            self.steps._draw(frames[tick % len(frames)], self)
            tick += 1
            if self._stop.wait(0.08):
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
            self.steps._erase()


def log_tail(path: Path, lines: int = 20) -> list[str]:
    """The last lines of a log, without colour codes or the command header written above them."""
    rows = [_ANSI.sub("", row).rstrip()[:240] for row in _read_text(path).splitlines()]
    while rows and (not rows[0] or rows[0].startswith(("$ ", "# in "))):
        rows.pop(0)
    while rows and not rows[-1]:
        rows.pop()
    return rows[-lines:]


def stop_process_tree(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """Stop a child and whatever it started, then reap it.

    On Windows `terminate()` ends ONE process, so a server that npm or next started outlives it
    and keeps holding its port; `taskkill /T` ends the tree.
    """
    if proc.poll() is None:
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            except OSError:
                proc.kill()
        else:
            proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── Small file helpers ───────────────────────────────────────────────────────────

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _child_env(**extra: str) -> dict:
    env = dict(os.environ)
    # The bootstrap runs this module in a throwaway environment, which `uv run` exports as
    # VIRTUAL_ENV. Passed on, uv would warn on every sync that it is not the project's `.venv`.
    env.pop("VIRTUAL_ENV", None)
    env.update(extra)
    return env


# ── 1. Python dependencies ───────────────────────────────────────────────────────

def find_uv() -> Optional[str]:
    """`uv run` tells its children where uv is (`UV`); otherwise, PATH."""
    return os.environ.get("UV") or shutil.which("uv")


def sync_python(root: Path, steps: Steps) -> None:
    uv = find_uv()
    if not uv:
        raise InstallError("uv is not installed.",
                           hint="Run ./install.sh (install.cmd on Windows): it installs uv first.")
    venv = Path(os.environ.get("UV_PROJECT_ENVIRONMENT") or ".venv")
    fresh = not (venv if venv.is_absolute() else root / venv).exists()
    cmd = [uv, "sync", "--all-extras", "--locked"]
    # Pin the interpreter only when CREATING the environment. Passing --python to an existing
    # `.venv` on another version would delete it and build a new one.
    if fresh and not os.environ.get("UV_PYTHON"):
        cmd += ["--python", PYTHON_VERSION]
    log = log_dir(root) / "python-dependencies.log"

    def result() -> str:
        if fresh:
            return "Python dependencies installed"
        changed = re.search(r"^\s*(Installed|Uninstalled|Updated)\b", _read_text(log), re.MULTILINE)
        return "Python dependencies updated" if changed else "Python dependencies up to date"

    steps.run("Installing Python dependencies" if fresh else "Checking Python dependencies",
              result, cmd, cwd=root, log=log, env=_child_env())


# ── 2. Node.js ───────────────────────────────────────────────────────────────────

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def parse_node_version(text: str) -> Optional[tuple[int, int, int]]:
    found = _VERSION.search(text or "")
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


def node_version(exe: Union[str, Path]) -> Optional[tuple[int, int, int]]:
    """The version a Node.js binary reports, or None when it does not run."""
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_node_version(out.stdout) if out.returncode == 0 else None


@dataclass(frozen=True)
class Node:
    exe: Path
    version: tuple[int, int, int]
    downloaded: bool = False

    @property
    def version_text(self) -> str:
        return ".".join(map(str, self.version))

    def npm(self) -> list[str]:
        """How to run npm with THIS Node.js: its own `npm-cli.js` wherever it sits beside the
        binary (every official layout), so no `npm.cmd` shim and no `#!/usr/bin/env node`
        reaches for a different Node on PATH. Failing that, the `npm` on PATH (a version
        manager's shim)."""
        for exe in dict.fromkeys((self.exe, self.exe.resolve())):
            for cli in (exe.parent / "node_modules" / "npm" / "bin" / "npm-cli.js",          # Windows
                        exe.parent.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"):
                if cli.is_file():
                    return [str(self.exe), str(cli)]
        npm = shutil.which("npm")
        if npm:
            return [npm]
        raise InstallError(f"npm is missing from the Node.js at {self.exe}.", hint=_GET_NODE)

    def env(self, base: Optional[dict] = None) -> dict:
        """`base` with this Node.js first on PATH, for the scripts npm and Next.js start."""
        env = dict(_child_env() if base is None else base)
        env["PATH"] = str(self.exe.parent) + os.pathsep + env.get("PATH", "")
        return env


def _node_exe_name() -> str:
    return "node.exe" if os.name == "nt" else "node"


def _version_key(path: Path) -> tuple[int, int, int]:
    return parse_node_version(str(path)) or (0, 0, 0)


def _downloaded_nodes(root: Path) -> list[Path]:
    pattern = f"node-v*/{_node_exe_name()}" if os.name == "nt" else "node-v*/bin/node"
    return sorted((runtime_dir(root) / "node").glob(pattern), key=_version_key, reverse=True)


def node_candidates(root: Path) -> list[Path]:
    """Where a Node.js may be, most preferred first. PATH comes first: that is the one the user
    chose. Then the usual install locations a non-interactive shell does not have on PATH (nvm
    adds itself only in an interactive shell's profile), then one this installer downloaded."""
    found: list[Path] = []
    if os.environ.get("AUGHOR_NODE_DOWNLOAD"):
        # Ignore every installed Node.js — how CI exercises the download path on runners that
        # all ship one.
        return _downloaded_nodes(root)
    on_path = shutil.which("node")
    if on_path:
        found.append(Path(on_path))
    home = Path.home()
    nvm = Path(os.environ.get("NVM_DIR") or home / ".nvm") / "versions" / "node"
    found += sorted(nvm.glob(f"v*/bin/{_node_exe_name()}"), key=_version_key, reverse=True)
    found += [home / ".volta" / "bin" / _node_exe_name(),
              Path("/opt/homebrew/bin/node"), Path("/usr/local/bin/node")]
    if os.name == "nt":
        found += [Path(base) / "nodejs" / "node.exe"
                  for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))
                  if base]
    found += _downloaded_nodes(root)
    return [path for path in dict.fromkeys(found) if path.is_file()]


def find_node(root: Path) -> tuple[Optional[Node], Optional[tuple[int, int, int]]]:
    """The first usable Node.js, and the newest too-old one seen (so a message can say why)."""
    too_old: Optional[tuple[int, int, int]] = None
    downloaded = set(_downloaded_nodes(root))
    for exe in node_candidates(root):
        version = node_version(exe)
        if version is None:
            continue
        if version >= NODE_MIN:
            return Node(exe, version, downloaded=exe in downloaded), too_old
        too_old = max(too_old or version, version)
    return None, too_old


def ensure_node(root: Path, steps: Steps) -> Node:
    node, too_old = find_node(root)
    if node is not None:
        steps.up_to_date(f"Node.js {node.version_text}")
        return node
    if too_old is not None:
        why = f"Node.js {'.'.join(map(str, too_old))} is older than Aughor needs (20.9)"
    else:
        why = "Node.js isn't installed on this computer"
    steps.line(steps.dim(f"{why}, so Aughor will use its own copy."))
    return download_node(root, steps)


def node_dist_filename(version: str, system: str, machine: str, *, xz: bool = True) -> str:
    """nodejs.org's archive name for `version` (like `v24.21.0`) on this OS and CPU."""
    os_part = {"darwin": "darwin", "linux": "linux", "windows": "win"}.get(system.lower())
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine.lower())
    if os_part is None or arch is None:
        raise InstallError(f"Aughor can't download Node.js for this computer ({system} {machine}).",
                           hint=_GET_NODE)
    if os_part == "linux" and any(Path("/lib").glob("ld-musl-*")):
        raise InstallError("Aughor can't download Node.js for a musl-based Linux (Alpine).",
                           hint=_GET_NODE)
    extension = "zip" if os_part == "win" else ("tar.xz" if xz else "tar.gz")
    return f"node-{version}-{os_part}-{arch}.{extension}"


def expected_sha256(shasums: str, filename: str) -> str:
    for row in shasums.splitlines():
        parts = row.split()
        if len(parts) == 2 and parts[1] == filename:
            return parts[0].lower()
    raise InstallError(f"nodejs.org lists no checksum for {filename}.", hint=_GET_NODE)


def verify_sha256(path: Path, expected: str) -> None:
    if _sha256_file(path) != expected.lower():
        raise InstallError("The Node.js download was corrupted (its checksum does not match), "
                           "so it was discarded.", hint=_OFFLINE)


def extract_archive(archive: Path, dest: Path) -> None:
    """Unpack a .zip or .tar.* into `dest`, refusing any entry that would land outside it."""
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()

    def inside(name: str) -> None:
        target = (base / name).resolve()
        if target != base and base not in target.parents:
            raise InstallError(f"Refused to unpack {archive.name}: {name!r} points outside the "
                               "folder it belongs in.", hint=_GET_NODE)

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                inside(name)
            zf.extractall(dest)
        return
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        for member in members:
            inside(member.name)
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, filter="data")  # also refuses links that leave `dest`
        else:  # Python < 3.11.4; every name was checked above
            tf.extractall(dest, members=members)


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "aughor-installer"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _download(url: str, dest: Path, progress: Callable[[int, int], None]) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "aughor-installer"})
    with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        for chunk in iter(lambda: response.read(1 << 16), b""):
            out.write(chunk)
            got += len(chunk)
            if total:
                progress(got, total)


def latest_node_release(major: int = NODE_LTS_MAJOR) -> str:
    releases = json.loads(_fetch(f"{NODE_DIST}/index.json"))  # newest first
    for release in releases:
        version = str(release.get("version", ""))
        if version.startswith(f"v{major}."):
            return version
    raise InstallError(f"nodejs.org lists no Node.js {major} release.", hint=_GET_NODE)


def download_node(root: Path, steps: Steps) -> Node:
    """Fetch an official Node.js build into `.aughor/node`, verified against nodejs.org's
    published SHA-256 before a single file is unpacked."""
    home = runtime_dir(root) / "node"
    home.mkdir(parents=True, exist_ok=True)
    # .tar.xz is half the size of .tar.gz, but a Python built without lzma cannot open it.
    xz = importlib.util.find_spec("lzma") is not None
    found: dict[str, Path] = {}
    with steps.working("Downloading Node.js", lambda: f"Node.js {found['version']} downloaded") as live:
        try:
            version = latest_node_release()
            filename = node_dist_filename(version, platform.system(), platform.machine(), xz=xz)
            live.label = f"Downloading Node.js {version[1:]}"
            want = expected_sha256(_fetch(f"{NODE_DIST}/{version}/SHASUMS256.txt").decode(), filename)
            # ignore_cleanup_errors: on Windows a virus scanner can hold a just-unpacked file for
            # a moment, and failing to delete the EMPTIED temp folder must not turn a finished
            # download into a reported failure.
            with tempfile.TemporaryDirectory(dir=home, ignore_cleanup_errors=True) as tmp:
                archive = Path(tmp) / filename
                _download(f"{NODE_DIST}/{version}/{filename}", archive,
                          lambda got, total: live.update(f"{got * 100 // total}%"))
                live.update("checking")
                verify_sha256(archive, want)
                live.update("unpacking")
                folder = re.sub(r"\.(zip|tar\.xz|tar\.gz)$", "", filename)
                extract_archive(archive, Path(tmp) / "unpacked")
                final = home / folder
                if final.exists():
                    shutil.rmtree(final)
                os.replace(Path(tmp) / "unpacked" / folder, final)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise InstallError(f"Could not download Node.js: {exc}", hint=_OFFLINE) from exc
        exe = final / _node_exe_name() if os.name == "nt" else final / "bin" / "node"
        installed = node_version(exe)
        if installed is None:
            raise InstallError("The downloaded Node.js does not run on this computer.", hint=_GET_NODE)
        found["version"] = ".".join(map(str, installed))
    return Node(exe, installed, downloaded=True)


# ── 3 and 4. The web app ─────────────────────────────────────────────────────────

def _platform_tag() -> str:
    return f"{sys.platform}-{platform.machine().lower()}"


def ensure_web_deps(root: Path, node: Node, steps: Steps) -> bool:
    """`npm ci` unless `node_modules` was installed from this exact lockfile, on this platform.
    `ci` rather than `install`: it never rewrites `package-lock.json`, so running the app never
    leaves a diff behind. Returns whether it installed anything."""
    web = root / "web"
    stamp = web / "node_modules" / ".aughor-install.json"
    want = {"package_lock_sha256": _sha256_file(web / "package-lock.json"), "platform": _platform_tag()}
    if _read_json(stamp) == want:
        steps.up_to_date("Web app dependencies up to date")
        return False
    fresh = not (web / "node_modules").is_dir()
    steps.run("Installing web app dependencies" if fresh else "Updating web app dependencies",
              "Web app dependencies installed" if fresh else "Web app dependencies updated",
              node.npm() + ["ci", "--no-audit", "--no-fund"], cwd=web,
              log=log_dir(root) / "web-dependencies.log",
              env=node.env(_child_env(npm_config_update_notifier="false")), tool="npm")
    _write_json(stamp, want)
    return True


#: Directories under web/ that hold installed packages or build output, never source.
_NOT_SOURCE = {"node_modules", ".next", "out", "build", "coverage", ".git", ".turbo", ".vercel"}
#: Build inputs that web/.gitignore ignores on purpose (`.env*`) but that `next build` inlines.
_ENV_FILES = (".env", ".env.local", ".env.production", ".env.production.local")


def _web_sources(web: Path) -> list[str]:
    """Every file `next build` reads from web/, relative to it. Git's own list when this is a
    checkout — it already knows what is generated, because .gitignore says so — and a walk that
    skips the known output folders when it is not (a downloaded archive, or no git)."""
    files: list[str] = []
    git = shutil.which("git")
    if git:
        try:
            out = subprocess.run([git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                 cwd=str(web), capture_output=True, timeout=60)
            if out.returncode == 0:
                files = [name for name in out.stdout.decode("utf-8", "replace").split("\0") if name]
        except (OSError, subprocess.SubprocessError):
            files = []  # git could not run: the walk below covers it
    if not files:
        for folder, subfolders, names in os.walk(web):
            subfolders[:] = [name for name in subfolders if name not in _NOT_SOURCE]
            for name in names:
                if name == "next-env.d.ts" or name.endswith(".tsbuildinfo"):
                    continue
                files.append(Path(os.path.relpath(Path(folder) / name, web)).as_posix())
    files += [name for name in _ENV_FILES if (web / name).is_file()]
    return sorted(set(files))


def build_fingerprint(root: Path, env: dict) -> str:
    """One hash over everything a production build depends on: every source file under web/,
    and the `NEXT_PUBLIC_*` values Next.js bakes into the bundle."""
    web = root / "web"
    hasher = hashlib.sha256()
    for name in _web_sources(web):
        path = web / name
        if path.is_file():  # tracked but deleted in the working tree
            hasher.update(f"{name}\0{_sha256_file(path)}\n".encode())
    for key in sorted(k for k in env if k.startswith("NEXT_PUBLIC_")):
        hasher.update(f"{key}={env[key]}\n".encode())
    return hasher.hexdigest()


def next_bin(root: Path) -> Path:
    """Next.js's own CLI script. Run with `node` directly — no npm layer that swallows signals,
    no `.cmd` shim on Windows."""
    return root / "web" / "node_modules" / "next" / "dist" / "bin" / "next"


def ensure_web_build(root: Path, node: Node, steps: Steps, env: dict) -> bool:
    """`next build` unless the current build was made from these exact inputs. Returns whether
    it built."""
    web = root / "web"
    stamp = web / ".next" / ".aughor-build.json"
    if (web / ".next" / "BUILD_ID").is_file() and _read_json(stamp) == {
            "fingerprint": build_fingerprint(root, env)}:
        steps.up_to_date("Web app up to date")
        return False
    steps.run("Building the web app", "Web app built", [node.exe, next_bin(root), "build"],
              cwd=web, log=log_dir(root) / "web-build.log", env=node.env(env), tool="next build")
    # Measured AFTER the build, so a file the build itself touches cannot force a rebuild on
    # every start.
    _write_json(stamp, {"fingerprint": build_fingerprint(root, env)})
    return True


def web_env(api_port: int = DEFAULT_API_PORT, base: Optional[dict] = None) -> dict:
    """The environment `next build` and the web server run with.

    Only a non-default API port adds anything. The browser's default API URL is baked into the
    bundle at BUILD time (`web/lib/config.ts`), and the server-side chat proxy reads its own at
    RUN time (`web/lib/chatProxy.ts`), so both are pointed at the same port. A value the user set
    themselves wins.
    """
    env = _child_env() if base is None else dict(base)
    # Next.js's anonymous usage telemetry stays off unless the user switched it on: Aughor's
    # posture is that nothing leaves the machine by default.
    env.setdefault("NEXT_TELEMETRY_DISABLED", "1")
    if api_port != DEFAULT_API_PORT:
        env.setdefault("NEXT_PUBLIC_API_URL", f"http://localhost:{api_port}")
        env.setdefault("AUGHOR_API_BASE", f"http://127.0.0.1:{api_port}")
    return env


def prepare_web(root: Path, steps: Steps, *, api_port: int = DEFAULT_API_PORT,
                build: bool = True) -> tuple[Node, dict]:
    """Everything the web app needs before it can start: Node.js, its packages and — for the
    production server — a build that matches the sources. Returns the Node.js to run it with
    and the environment to run it in."""
    if not (root / "web" / "package.json").is_file():
        raise InstallError(f"There is no web app at {root / 'web'}. Is this an Aughor checkout?")
    node = ensure_node(root, steps)
    ensure_web_deps(root, node, steps)
    env = web_env(api_port)
    if build:
        ensure_web_build(root, node, steps, env)
    return node, env


# ── The `aughor` command ─────────────────────────────────────────────────────────

#: In every launcher this installer writes, so a later install recognises its own file and never
#: overwrites someone else's `aughor`.
LAUNCHER_MARK = "Written by the Aughor installer"


def launcher_dir(uv: str) -> Optional[Path]:
    """uv's folder for commands (`uv tool dir --bin`): the one uv's own installer puts on PATH,
    and the one UV_TOOL_BIN_DIR moves."""
    try:
        out = subprocess.run([uv, "tool", "dir", "--bin"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    folder = out.stdout.strip()
    return Path(folder) if out.returncode == 0 and folder else None


def launcher_script(root: Path, uv: str, windows: bool) -> str:
    """The `aughor` command. With no arguments it starts Aughor; anything else goes to its CLI
    (`aughor seed`, `aughor up --dev`). It runs from the checkout, whatever folder the terminal
    is in, and says so plainly if the checkout has been moved or deleted."""
    if windows:
        # Labels and gotos rather than ( ) blocks: cmd expands %AUGHOR_ROOT% before it parses a
        # block, so a folder with a bracket in its name would break one.
        return "\r\n".join([
            "@echo off",
            f"rem {LAUNCHER_MARK}.",
            "rem `aughor` starts Aughor; `aughor seed`, `aughor up --dev` and the rest go to its CLI.",
            "setlocal",
            f'set "AUGHOR_ROOT={root}"',
            'if exist "%AUGHOR_ROOT%\\pyproject.toml" goto found',
            "echo Aughor is no longer in %AUGHOR_ROOT%. Run the installer again. 1>&2",
            "exit /b 1",
            ":found",
            'set "AUGHOR_UV=uv"',
            f'where uv >nul 2>nul || set "AUGHOR_UV={uv}"',
            'pushd "%AUGHOR_ROOT%"',
            'if "%~1"=="" goto start',
            '"%AUGHOR_UV%" run --quiet aughor %*',
            "goto done",
            ":start",
            '"%AUGHOR_UV%" run --quiet aughor up',
            ":done",
            'set "AUGHOR_CODE=%ERRORLEVEL%"',
            "popd",
            "exit /b %AUGHOR_CODE%",
            "",
        ])
    return "\n".join([
        "#!/bin/sh",
        f"# {LAUNCHER_MARK}.",
        "# `aughor` starts Aughor; `aughor seed`, `aughor up --dev` and the rest go to its CLI.",
        f"root={shlex.quote(str(root))}",
        'if [ ! -f "$root/pyproject.toml" ]; then',
        '  echo "Aughor is no longer in $root. Run the installer again." >&2',
        "  exit 1",
        "fi",
        '[ "$#" -eq 0 ] && set -- up',
        f"uv=$(command -v uv 2>/dev/null || echo {shlex.quote(uv)})",
        'cd "$root" && exec "$uv" run --quiet aughor "$@"',
        "",
    ])


def _same_path(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def install_launcher(root: Path, uv: Optional[str]) -> str:
    """Put the `aughor` command where a terminal finds it, and say how the next-time hint should
    read: "ready" (this terminal already finds it), "new-terminal" (the next one will: the
    bootstrap just installed uv, and uv's installer put that folder on PATH), or "" (no
    terminal will — the hint falls back to the checkout's own command)."""
    if not uv:
        return ""
    folder = launcher_dir(uv)
    if folder is None:
        return ""
    windows = os.name == "nt"
    target = folder / ("aughor.cmd" if windows else "aughor")
    try:
        if target.exists() and LAUNCHER_MARK not in _read_text(target):
            return ""  # someone else's `aughor`: never overwrite it
        folder.mkdir(parents=True, exist_ok=True)
        target.write_text(launcher_script(root, uv, windows), encoding="utf-8", newline="")
        if not windows:
            target.chmod(0o755)
    except OSError:
        return ""  # a read-only folder costs the shortcut, never the install
    found = shutil.which("aughor")
    if found:
        return "ready" if _same_path(Path(found), target) else ""
    if os.environ.get("AUGHOR_UV_INSTALLED") and _same_path(Path(uv).parent, folder):
        return "new-terminal"
    return ""


# ── 5. Hand over to `aughor up` ──────────────────────────────────────────────────

def start_command_hint() -> str:
    """How to start Aughor next time. One word wherever the installer could put the `aughor`
    command on PATH; otherwise the checkout's own command, from a terminal that may lack two
    things the installer had:
    uv on PATH (a uv the bootstrap just installed reaches PATH only in NEW terminals), and the
    checkout as its folder (`curl | sh` clones into a sub-folder). Worded as steps rather than
    `cd … && …`, which Windows PowerShell 5.1 cannot run."""
    launcher = os.environ.get("AUGHOR_LAUNCHER")
    if launcher == "ready":
        return "Next time, start Aughor with:  aughor"
    if launcher == "new-terminal":
        return "Next time, open a new terminal and run:  aughor"
    first = []
    if os.environ.get("AUGHOR_UV_INSTALLED"):
        first.append("open a new terminal")
    if os.environ.get("AUGHOR_CHECKOUT_DIR"):
        first.append(f"go to {os.environ['AUGHOR_CHECKOUT_DIR']}")
    if not first:
        return "Next time, start Aughor with:  uv run aughor up"
    return f"Next time, {', '.join(first)} and run:  uv run aughor up"


def _hand_off(root: Path, args: Sequence[str]) -> int:
    uv = find_uv() or "uv"
    cmd = [uv, "run", "--no-sync", "aughor", "up", *args]
    env = _child_env(AUGHOR_INSTALLER="1")
    sys.stdout.flush()
    if os.name != "nt":
        os.chdir(root)
        os.execvpe(cmd[0], cmd, env)  # becomes `aughor up`: its Ctrl-C, its exit code
    # Windows has no real exec — os.exec* starts a new process and returns to the prompt while
    # it runs. Wait for it instead, and leave Ctrl-C to the child, which shares the console.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    return subprocess.call(cmd, cwd=str(root), env=env)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install", allow_abbrev=False,
        description="Install everything Aughor needs, then start it and open it in your browser. "
                    "Safe to run again: it only redoes what changed.")
    parser.add_argument("--no-start", action="store_true", help="install everything, but don't start Aughor")
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT, help="port for the API (default 8000)")
    parser.add_argument("--web-port", type=int, default=3000, help="port for the web app (default 3000)")
    parser.add_argument("--dev", action="store_true", help="development mode: hot reload, logs in this terminal")
    parser.add_argument("--api-only", action="store_true", help="install and start only the API")
    parser.add_argument("--web-only", action="store_true", help="start only the web app")
    parser.add_argument("--no-browser", action="store_true", help="don't open the web app in a browser")
    parser.add_argument("--verbose", "-v", action="store_true", help="show everything the tools print")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    tolerate_narrow_output()
    args = list(sys.argv[1:] if argv is None else argv)
    options = _parser().parse_args(args)
    root = Path.cwd()
    steps = Steps(verbose=options.verbose, show_up_to_date=True)
    if not os.environ.get("AUGHOR_BOOTSTRAP"):
        steps.header("Aughor installer")
    try:
        if not ((root / "pyproject.toml").is_file() and (root / "web" / "package.json").is_file()):
            raise InstallError(f"{root} is not an Aughor checkout.",
                               hint="Run the installer from the folder Aughor was cloned into.")
        sync_python(root, steps)
        if not options.api_only:
            prepare_web(root, steps, api_port=options.api_port, build=not options.dev)
    except InstallError as error:
        steps.failure(error)
        return 1
    except KeyboardInterrupt:
        steps.line()
        return 130
    # One command for next time. Put in the environment so `aughor up`, which prints the closing
    # hint after the hand-over, reads the same answer.
    os.environ["AUGHOR_LAUNCHER"] = install_launcher(root, find_uv())
    if options.no_start:
        steps.line()
        steps.line(steps.bold("Aughor is installed."))
        steps.line(start_command_hint())
        steps.line()
        return 0
    return _hand_off(root, [arg for arg in args if arg != "--no-start"])


if __name__ == "__main__":
    sys.exit(main())
