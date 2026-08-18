"""Measure the install footprint the README quotes — reproducibly.

Three different figure-sets for "how big is Aughor" had accumulated across the README,
`pyproject.toml` and `tests/unit/test_serving_footprint.py`, disagreeing by up to 2x
because none of them said WHICH size they meant. They are not the same measurement:

  venv on disk     the size of every file under the venv after `uv sync` — what a
                   contributor sees, and what a size-limited deployment pays for. A few
                   percent under `du -sh`, which counts allocated blocks rather than
                   file sizes.
  import closure   the third-party packages `import aughor.api` actually loads. Far
                   smaller, and the number the extras split was designed around; the
                   ratchet in tests/unit/test_serving_footprint.py guards it.

This script prints both for the CURRENT environment, so a doc number can be re-derived
instead of remembered. Sizes are platform- and interpreter-specific; the README says
which platform its figures came from, and so does this output.

Usage:
    uv run python scripts/measure_footprint.py            # this venv
    uv run python scripts/measure_footprint.py --compare  # also build a serving-core
                                                          # venv in a temp dir and
                                                          # measure it (slow: it syncs)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import subprocess
import sys
import sysconfig
import tempfile
import textwrap


def _dir_bytes(path: pathlib.Path) -> int:
    """Bytes on disk under `path`, counting each inode once.

    uv hardlinks from its cache, so the same file can appear under several venvs; `du`
    counts a link once per traversal, which is what we want — this is what the directory
    costs in the tree being measured.
    """
    seen: set[tuple[int, int]] = set()
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue          # raced with a delete — not worth failing a measurement
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += st.st_size
    return total


def _mb(n: int) -> str:
    return f"{n / 1_000_000:,.0f} MB"


def _import_closure_bytes(python: str) -> tuple[int, int]:
    """(bytes, package count) of third-party top-level packages `aughor.api` imports.

    Measured in a SUBPROCESS: this process has already imported much of the codebase,
    so an in-process diff would measure the measurer. Mirrors the method in
    tests/unit/test_serving_footprint.py so the two cannot drift apart.
    """
    code = textwrap.dedent("""
        import json, pathlib, sys, sysconfig
        before = set(sys.modules)
        import aughor.api  # noqa: F401
        site = pathlib.Path(sysconfig.get_paths()["purelib"])
        tops = set()
        for name in set(sys.modules) - before:
            mod = sys.modules.get(name)
            f = getattr(mod, "__file__", None) or ""
            if str(site) in f:
                tops.add(name.split(".")[0])
        print(json.dumps(sorted(tops)))
    """)
    proc = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise SystemExit(f"could not import aughor.api:\n{proc.stderr[-800:]}")
    tops = json.loads(proc.stdout.strip().splitlines()[-1])
    site = pathlib.Path(sysconfig.get_paths()["purelib"])
    total = sum(_dir_bytes(site / t) for t in tops if (site / t).is_dir())
    return total, len(tops)


def _serving_core_bytes() -> int:
    """Build a serving-core venv (`uv sync`, no extras) in a temp dir and measure it.

    Uses UV_PROJECT_ENVIRONMENT so the caller's own .venv is left alone.
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = pathlib.Path(tmp) / "core-venv"
        env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(target)}
        proc = subprocess.run(["uv", "sync", "-q"], env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"uv sync failed:\n{proc.stderr[-800:]}")
        return _dir_bytes(target)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compare", action="store_true",
                    help="also build and measure a serving-core venv (slow — it syncs)")
    args = ap.parse_args()

    venv = pathlib.Path(sys.prefix)
    print(f"platform          {platform.system().lower()}-{platform.machine()} · "
          f"CPython {platform.python_version()}")
    print(f"venv              {venv}")
    print(f"  on disk         {_mb(_dir_bytes(venv))}   (file sizes; du -sh reads a few % higher)")

    closure_bytes, n = _import_closure_bytes(sys.executable)
    print(f"  import closure  {_mb(closure_bytes)}   ({n} third-party packages "
          f"loaded by `import aughor.api`)")

    if args.compare:
        print("\nbuilding a serving-core venv (uv sync, no extras)…")
        print(f"  serving core    {_mb(_serving_core_bytes())}   (on disk)")


if __name__ == "__main__":
    main()
