"""Freeze one connection's READ surface into a static recording the hosted UI can serve.

The demo pack froze the *answers*; this freezes the *API responses that carry them*, so a
statically-hosted frontend has something to talk to. Same thesis as `demo/pack.py` and
`ontology/context_graph_export` — "generation is paid once; consumption is free" — applied
one layer up.

**Why record rather than hand-author.** The UI reaches the backend through ~266 fetch sites
whose response shapes are defined by the live API, not by any document. Hand-authoring them
means guessing, and a wrong shape renders as an empty page — the exact symptom this exists to
fix, reintroduced silently. Recording takes the shapes from the thing that defines them.

**The scrub is a safety gate, not tidying.** `/connections` and `/workspaces` are
connection-LIST routes: they answer with every connection the local instance has ever had.
Recording them raw would publish the operator's whole estate. So every response is narrowed
to the demo connection, and a term scan runs over the finished recording — a hit ABORTS the
write rather than trimming, because a leak that gets trimmed silently is a leak that comes
back the next time the shape changes.

Deterministic given a running backend; no model call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

#: Recording format version, carried in the file so the reader can refuse a future one.
RECORDING_VERSION = 1

#: Routes the hosted demo serves. Explicit allowlist: a route not named here is refused at
#: serve time with the "connect your own backend" copy, which is the honest answer for
#: anything that would need a live engine.
#: Every query param here must be one the route actually DECLARES. FastAPI drops an
#: undeclared param silently and answers unfiltered, so a wrong name does not error — it
#: returns the whole estate and looks like a successful capture. Both mistakes were made
#: while writing this file: `/canvases?connection_id=` and
#: `/org-settings/effective?connection_id=` are each ignored, and both routes key on
#: `workspace_id`. Check `openapi.json` before adding a route here.
def _routes(conn: str, workspace: str = "",
            schemas: tuple[str, ...] = ()) -> list[tuple]:
    ws = f"?workspace_id={workspace}" if workspace else ""
    # The surfaces ask schema-qualified questions once a schema is selected — which is
    # immediately, because the briefing page mounts with the first schema chosen. The
    # serve-side matcher compares the EXACT query string with params sorted
    # alphabetically (`recordedKey` in web/app/demo-api/[...path]/route.ts), so every
    # multi-param path here must list its params in that order or the recording can
    # never be hit. The bare-path fallback does not save these: it only fires when the
    # RECORDED key has no query string at all.
    per_schema: list[tuple] = []
    for s in schemas:
        per_schema += [
            ("GET", f"/business-profile?connection_id={conn}&schema_name={s}", None),
            ("GET", f"/viz-configs?scope_key={conn}:{s}", None),
            # Generates on first record (cache key is `{conn}:{schema}`, distinct from
            # the conn-level one) — with `workspace_id` so org identity resolves to the
            # DEMO workspace's own declared settings, then serves from cache thereafter.
            ("POST", f"/exploration/{conn}/briefing?schema={s}&workspace_id={workspace}", None)
            if workspace else
            ("POST", f"/exploration/{conn}/briefing?schema={s}", None),
        ]
    return per_schema + [
        ("GET", "/connections", None),
        ("GET", "/workspaces", None),
        ("GET", "/capabilities", None),
        ("GET", "/org-settings", None),
        ("GET", f"/org-settings/effective{ws}", None),
        ("GET", f"/canvases{ws}", None),
        ("GET", f"/ontology?connection_id={conn}", None),
        ("GET", f"/ontology/metrics?connection_id={conn}", None),
        ("GET", f"/ontology/entities?connection_id={conn}", None),
        ("GET", f"/exploration/{conn}/status", None),
        ("GET", f"/exploration/{conn}/domains", None),
        ("GET", f"/exploration/{conn}/findings", None),
        ("GET", f"/exploration/{conn}/episodes", None),
        ("GET", f"/graph?connection_id={conn}", None),
        ("GET", "/investigations?limit=50", None),
        # Discovered by DRIVING the UI, not by grepping it. A static read of the fetch
        # sites missed ten routes and got the investigations list's parameter wrong — the
        # surfaces call it with `workspace_id`, not `limit`. The browser's network log is
        # the authority on what the app actually asks for; anything not recorded renders
        # as an error, not as an empty state.
        ("GET", f"/investigations{ws}", None),
        ("GET", f"/business-profile?connection_id={conn}", None),
        ("GET", f"/cards?scope=connection&scope_ref={conn}", None),
        ("GET", f"/exploration/{conn}/patterns", None),
        ("GET", "/org-intelligence", None),
        ("GET", f"/org-intelligence?connection_id={conn}", None),
        ("GET", "/actions/triggers", None),
        ("GET", f"/viz-configs?scope_key={conn}", None),
        ("GET", "/catalog/tree", None),
        ("GET", f"/connections/{conn}/causal-graph", None),
        # The briefing is generated through a POST that serves from cache; the demo needs
        # the cached narrative, so the POST is recorded like any other read.
        ("POST", f"/exploration/{conn}/briefing{ws}", None),
    ]


#: Terms that must never appear in a public recording. Deliberately broad — every other
#: dataset this instance has loaded, plus currency/domain tokens unique to them.
_FOREIGN = (
    "luxexperience", "beautycommerce", "creditcard", "swiss", "airline",
    "duty_eur", "gmv_eur", "refund_eur", "shipping_fee_eur",
    "o_orderkey", "o_custkey", "coupon_abuse",
)


class RecordingError(RuntimeError):
    """Refused to write a recording. Never raised for 'a route returned nothing'."""


def _key(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


def _scrub(path: str, payload: Any, conn: str, workspace: str,
           investigation_ids: Optional[list[str]] = None) -> Any:
    """Narrow a response to the demo connection. Returns the payload to record.

    Only the LIST routes need it — everything else is already scoped by the connection id
    in its own path or query. Those two are exactly the routes that would otherwise
    publish the operator's whole estate, so they are handled explicitly rather than by a
    generic rule that could quietly stop matching.
    """
    if path.startswith("/connections") and isinstance(payload, list):
        return [c for c in payload if (c or {}).get("id") == conn]
    if path.startswith("/workspaces") and isinstance(payload, list):
        keep = {workspace} if workspace else set()
        return [w for w in payload
                if (w or {}).get("id") in keep or (w or {}).get("connection_id") == conn]
    if path.startswith("/catalog/tree") and isinstance(payload, dict):
        # The catalog tree is the estate, laid out: every connection, every schema, every
        # table. Narrowed to the demo connection's entry, or it publishes the lot.
        return {
            **payload,
            "sections": [
                {**s, "entries": [e for e in (s.get("entries") or [])
                                  if (e or {}).get("conn_id") == conn]}
                for s in (payload.get("sections") or [])
            ],
        }
    if path.startswith("/org-intelligence") and isinstance(payload, list):
        # The bare route answers with every promotion the instance has ever made — in
        # practice a unit-test fixture row and other connections' findings, none of it
        # nameable by the term scan because none of it uses a banned term. Same narrowing
        # as the other list routes: the demo connection's own promotions or nothing.
        return [r for r in payload if (r or {}).get("connection_id") == conn]
    if path.startswith("/investigations") and isinstance(payload, list):
        # Connection scope is not enough here. The demo pack is CURATED — pre-fix runs and
        # the losing halves of duplicated pairs were deliberately dropped — and the list
        # route answers with every run on the connection (17, against the pack's 8). Left
        # unfiltered the excluded work returns through the list, exactly as it returned
        # through the graph's finding nodes. The allowlist is the pack's own.
        rows = [r for r in payload if (r or {}).get("connection_id") == conn]
        if investigation_ids is not None:
            allowed = set(investigation_ids)
            rows = [r for r in rows if (r or {}).get("id") in allowed]
        return rows
    return payload


def _substitute_org(routes: dict, workspace_key: str) -> None:
    """Answer `/org-settings` with the DEMO workspace's identity, not the operator's org.

    Not a scrub — a substitution, and it needs saying out loud. `/org-settings` takes no
    parameters and correctly returns whoever runs this instance (here: "LuxExperience",
    Munich, EUR). That is right for the app and wrong for a public recording, which must
    present the demo's own identity. The workspace-scoped `effective` answer is already
    exactly that (Superstore / United States / USD / Retail), so the substitution copies it
    rather than inventing values that could disagree with the artifacts.
    """
    effective = routes.get(workspace_key)
    if isinstance(effective, dict) and effective:
        routes["GET /org-settings"] = dict(effective)


def _contamination(recording: dict) -> list[str]:
    blob = json.dumps(recording).lower()
    return [t for t in _FOREIGN if t in blob]


def record(base_url: str, connection_id: str, out_path: str | Path, *,
           workspace_id: str = "", investigation_ids: Optional[list[str]] = None,
           pack_graph: Optional[dict] = None,
           schemas: tuple[str, ...] = ()) -> dict:
    """Capture the allowlisted routes and write the recording. Raises on contamination."""
    import urllib.error
    import urllib.request

    if not connection_id:
        raise RecordingError("connection_id is required — a recording carries ONE connection")

    def _call(method: str, path: str) -> tuple:
        req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            return e.code, None
        except Exception:
            return 0, None

    # The list route keys a `chat` row by its SESSION id, not its investigation id, so an
    # allowlist of investigation ids alone silently drops every quick ask — 8 curated runs
    # would surface as 3. Expand it to both keys rather than matching on one and assuming.
    allowlist: Optional[list[str]] = None
    if investigation_ids is not None:
        allowlist = list(investigation_ids)
        try:
            from aughor.db.history import get_investigation
            for inv_id in investigation_ids:
                sid = (get_investigation(inv_id) or {}).get("session_id")
                if sid:
                    allowlist.append(sid)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "session ids unavailable; the list falls back to id matching",
                     counter="demo_recording.session_ids")

    entries: dict = {}
    skipped: list[str] = []
    for method, path, _ in _routes(connection_id, workspace_id, schemas):
        status, body = _call(method, path)
        if status != 200 or body is None:
            skipped.append(f"{_key(method, path)} → {status or 'unreachable'}")
            continue
        entries[_key(method, path)] = _scrub(path, body, connection_id, workspace_id,
                                             allowlist)

    # Investigation detail, one entry per frozen run. Recorded from the same live surface
    # so the detail shape matches the list shape's expectations.
    for inv_id in (investigation_ids or []):
        for path in (f"/investigations/{inv_id}", f"/investigations/{inv_id}/receipt"):
            status, body = _call("GET", path)
            if status == 200 and body is not None:
                owner = (body or {}).get("connection_id")
                if owner and owner != connection_id:
                    raise RecordingError(
                        f"refusing to record {path}: it belongs to {owner!r}, not "
                        f"{connection_id!r}")
                entries[_key("GET", path)] = body

    _substitute_org(entries, _key("GET", f"/org-settings/effective"
                                  f"{('?workspace_id=' + workspace_id) if workspace_id else ''}"))

    # The live `/graph` answer is contaminated at source: the glossary projection scopes by
    # TABLE NAME, so a connection absorbs every other dataset's terms for any table whose
    # name it shares. The pack already carries a graph filtered against this connection's
    # real columns, so the recording serves THAT rather than re-publishing the leak.
    if pack_graph is not None:
        entries[_key("GET", f"/graph?connection_id={connection_id}")] = pack_graph
    else:
        entries.pop(_key("GET", f"/graph?connection_id={connection_id}"), None)
        skipped.append("GET /graph → dropped (no filtered pack graph supplied)")

    recording = {
        "version": RECORDING_VERSION,
        "connection_id": connection_id,
        "routes": entries,
    }
    leaks = _contamination(recording)
    if leaks:
        raise RecordingError(
            "refusing to write: the recording contains terms from another dataset — "
            + ", ".join(leaks) + ". Narrow the scrub before recording again.")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recording, indent=1, sort_keys=True) + "\n")
    recording["_skipped"] = skipped
    return recording


def summarise(recording: dict) -> str:
    routes = recording.get("routes") or {}
    lines = [f"{len(routes)} routes recorded for {recording.get('connection_id')!r}"]
    for k in sorted(routes):
        payload = routes[k]
        size = len(payload) if isinstance(payload, (list, dict)) else 1
        lines.append(f"  {k:<62} {type(payload).__name__}({size})")
    for s in recording.get("_skipped") or []:
        lines.append(f"  SKIPPED {s}")
    return "\n".join(lines)


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.\-]+$")


def route_is_allowlisted(recording: dict, method: str, path: str) -> bool:
    """Whether a request can be served from this recording — the serve-side contract."""
    return _key(method, path) in (recording.get("routes") or {})
