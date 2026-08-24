"""`uv.lock` has to agree with `pyproject.toml`, and CI is the wrong place to find out.

CI syncs with `uv sync --all-extras --locked`, which refuses a lockfile that no longer
matches the manifest. When PR #389 added `pyexasol` to `[warehouse]` and replaced `[crm]`'s
contents without relocking, both Python jobs died in the SYNC step in under 12 seconds —
before a single test ran — while `ruff` and the frontend typecheck passed, because neither
needs the lock. The failure was correct and its message was clear; what it cost was a
round trip that a local check would have saved.

Deliberately reads both FILES rather than shelling out to `uv lock --check`: this must hold
on a machine with no network and no uv on PATH, and the property worth asserting is that the
two files agree about what this project requires — not that a resolver would produce the
same output today.

Names only, not versions. A specifier bump is a real drift too, but comparing them here
would fail on every legitimate `uv lock` refresh; the add/remove/move case is the one that
breaks the build.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _normalise(name: str) -> str:
    """PEP 503 name normalisation — `PyMySQL`, `pymysql` and `py_mysql` are one package."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _manifest() -> dict[str, set[str]]:
    """{extra or '' : {normalised requirement names}} as pyproject declares them."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    out = {"": {_normalise(re.split(r"[<>=!~\[;\s]", r, 1)[0]) for r in data["dependencies"]}}
    for extra, reqs in (data.get("optional-dependencies") or {}).items():
        out[extra] = {_normalise(re.split(r"[<>=!~\[;\s]", r, 1)[0]) for r in reqs}
    return out


def _locked() -> dict[str, set[str]]:
    """The same shape, read off the lockfile's record of the root package."""
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    root = next((p for p in lock["package"] if p["name"] == "aughor"), None)
    assert root is not None, "uv.lock has no record of this project — the guard is blind"
    out: dict[str, set[str]] = {}
    for req in root.get("metadata", {}).get("requires-dist", []):
        marker = req.get("marker", "") or ""
        found = re.search(r"extra == '([^']+)'", marker)
        out.setdefault(found.group(1) if found else "", set()).add(_normalise(req["name"]))
    return out


def test_the_lockfile_and_the_manifest_agree_on_every_extra():
    manifest, locked = _manifest(), _locked()
    drift = {}
    for extra in sorted(set(manifest) | set(locked)):
        want, have = manifest.get(extra, set()), locked.get(extra, set())
        if want != have:
            label = extra or "(base dependencies)"
            drift[label] = {"in pyproject only": sorted(want - have),
                            "in uv.lock only": sorted(have - want)}
    assert not drift, (
        f"uv.lock no longer matches pyproject.toml: {drift}\n"
        f"Run `uv lock` and commit the result. CI syncs with `--locked` and will refuse "
        f"this before it runs a single test.\n"
        f"⚠️ `uv lock` writes the lockfile only — do NOT run `uv sync` if a dev server is "
        f"running out of this .venv.")


def test_the_manifest_reader_found_something_to_compare():
    """An empty parse passes the assertion above for free — the shape of nothing."""
    manifest = _manifest()
    assert len(manifest[""]) >= 10, "base dependencies came back near-empty"
    assert {"warehouse", "crm"} <= set(manifest), "the connector extras went missing"


@pytest.mark.parametrize("dist,extra", [("pyexasol", "warehouse"), ("requests", "crm")])
def test_the_two_that_were_missing_are_locked(dist, extra):
    """The specific pair this guard was written for. Both were declared in NO extra while
    the code imported them; `requests` resolved transitively, which is why it went years
    unnoticed."""
    assert dist in _locked().get(extra, set())
