"""K4 wiring contract — every frontend API path must exist in the backend.

The blank-canvas class taught us that wiring drift (renamed/removed endpoints,
calls to paths that never existed) fails silently at runtime. This test parses
every `${BASE}/...` template in web/lib/*.ts, normalises `${param}` segments to
wildcards, and asserts each path matches a route in the live OpenAPI schema —
so drift becomes a CI failure, not a blank panel.

(Scope: web/lib only — the typed-client generation that would also cover
response shapes is the K4 follow-up; this kills the path-drift class first.)
"""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent.parent / "web"

# Frontend API calls reach the backend through several base constants — `${BASE}`,
# `${API_BASE}` (lib/api.ts), and `${BASE_API}` (CatalogScreen). Match all of them
# so the contract isn't blind to whole files (CatalogScreen/ActionHub) just because
# they picked a different alias. `${BASE}/exploration/${encodeURIComponent(id)}/...`
_CALL_RE = re.compile(r"\$\{(?:BASE|API_BASE|BASE_API)\}(/[^\s`\"']*)")

# Scan lib AND components: a fetch that drifts to a removed route is the
# blank-canvas bug class, and components call the API directly too (the original
# scan only covered web/lib, leaving every component fetch unguarded).
_SOURCES = sorted(WEB.glob("lib/*.ts")) + sorted(WEB.glob("components/*.ts")) + sorted(WEB.glob("components/*.tsx"))


def _frontend_paths():
    paths = set()
    for ts in _SOURCES:
        for m in _CALL_RE.finditer(ts.read_text()):
            raw = m.group(1).split("?")[0].rstrip("/")
            # An unterminated `${` means the regex cut mid-template (e.g. a
            # conditional query-string expression) — trim to the literal part.
            if "${" in raw and "}" not in raw.split("${", 1)[1]:
                raw = raw.split("${", 1)[0]
            if not raw or raw == "/":
                continue
            # ${anything} → {param}
            norm = re.sub(r"\$\{[^}]*\}", "{param}", raw)
            # `subscriptions${q}` — a query-string variable glued to the last
            # segment is not a path param; drop it.
            norm = re.sub(r"(?<=[A-Za-z0-9_-])\{param\}$", "", norm).rstrip("/")
            paths.add((norm, ts.name))
    return sorted(paths)


def _matches(frontend: str, backend: str) -> bool:
    f, b = frontend.split("/"), backend.split("/")
    if len(f) != len(b):
        return False
    for fs, bs in zip(f, b):
        if fs == "{param}" or (bs.startswith("{") and bs.endswith("}")):
            continue
        if fs != bs:
            return False
    return True


def test_every_frontend_path_has_a_backend_route(client):
    schema = client.get("/openapi.json").json()
    backend = list(schema["paths"].keys())
    missing = []
    for path, src in _frontend_paths():
        if not any(_matches(path, b) for b in backend):
            missing.append(f"{src}: {path}")
    assert not missing, (
        "Frontend calls with NO matching backend route (wiring drift):\n  "
        + "\n  ".join(missing)
    )


def test_contract_scanner_finds_calls():
    """The scanner itself must not silently match nothing (a regex rot guard)."""
    paths = _frontend_paths()
    assert len(paths) > 40, f"only {len(paths)} frontend paths parsed — scanner broken?"
