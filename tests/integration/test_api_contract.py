"""K4 wiring contract — every frontend API path must exist in the backend.

The blank-canvas class taught us that wiring drift (renamed/removed endpoints,
calls to paths that never existed) fails silently at runtime. This test parses
every `${getApiBase()}/...` template in the frontend, normalises `${param}` segments to
wildcards, and asserts each path matches a route in the live OpenAPI schema —
so drift becomes a CI failure, not a blank panel.

(Scope: web/lib only — the typed-client generation that would also cover
response shapes is the K4 follow-up; this kills the path-drift class first.)
"""
import re
from pathlib import Path


WEB = Path(__file__).parent.parent.parent / "web"

# Every frontend API call goes through `getApiBase()`. It used to be a const imported
# under three different aliases (`${BASE}`, `${API_BASE}`, `${BASE_API}`), which meant this
# regex had to know all three or go blind to whole files; the base became a function call
# when it was made runtime-configurable, and one spelling is now the only spelling.
# Example: `${getApiBase()}/exploration/${encodeURIComponent(id)}/...`
_CALL_RE = re.compile(r"\$\{getApiBase\(\)\}(/[^\s`\"']*)")

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


_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def test_operation_ids_are_unique(client):
    """Layer 0.3 — the #269 class as a fast local failure. A dual-method
    `api_route(["GET", "POST"])` emits the SAME operationId twice; the generated TS
    client then carries the identifier twice and web typecheck/build/codegen-drift
    fail NONDETERMINISTICALLY, far from the cause. Until now the only protections
    were the CI drift gate and a memory rule."""
    schema = client.get("/openapi.json").json()
    seen: dict[str, str] = {}
    duplicates = []
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if method not in _HTTP_METHODS:
                continue
            where = f"{method.upper()} {path}"
            oid = op.get("operationId")
            assert oid, f"{where} has no operationId — the TS codegen needs one per operation"
            if oid in seen:
                duplicates.append(f"{oid!r}: {seen[oid]} and {where}")
            seen[oid] = where
    assert not duplicates, (
        "Colliding operationIds (split each route into single-method handlers):\n  "
        + "\n  ".join(duplicates)
    )


def test_every_route_declares_a_single_method(client):
    """The structural rule behind the operationId guarantee: one route function, one
    HTTP method. FastAPI derives operationIds per handler, so a multi-method
    `api_route` is a collision by construction even before the spec is dumped."""
    from fastapi.routing import APIRoute

    from aughor.api import app   # imported through the client fixture's isolation

    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = set(route.methods or ()) - {"HEAD", "OPTIONS"}
        if len(methods) > 1:
            offenders.append(f"{route.path} declares {sorted(methods)}")
    assert not offenders, (
        "Multi-method route declarations (each emits colliding operationIds):\n  "
        + "\n  ".join(offenders)
    )
