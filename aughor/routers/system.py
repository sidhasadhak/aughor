"""System endpoints — health, dev stats, suggestions, connector types."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from aughor.db.registry import BUILTIN_ID

router = APIRouter(tags=["system"])


def _llm_readiness() -> dict:
    """The active LLM binding + whether it can plausibly serve — resolved from
    config only, NO network call (health must stay instant). `key_present` is
    True when the backend needs no key (local: ollama/lmstudio) or a key is
    configured (Settings → Inference runtime config, or env). Never raises: a
    broken LLM config must degrade this field, not 500 the health probe.

    `ready` requires a model as well as a key. It used to mirror `key_present`
    alone, so the default Ollama binding — which needs no key — reported ready on
    an install with no model configured at all, and `aughor up` printed
    "ollama · ? · ready" right before the first question failed with
    NoModelConfigured. `reason` names which half is missing so the caller can say
    so; both are resolved from config, still without a network call."""
    out: dict = {"backend": None, "model": None, "key_present": False,
                 "ready": False, "reason": "no_backend"}
    try:
        from aughor.llm import provider
        backend, model, _base_url = provider.resolve_binding("coder")
        out["backend"], out["model"] = backend, model
        # provider._active_key is the same runtime-config→env key resolver the real
        # client builders use; reached as a module attribute (no private cross-import).
        key_present = backend not in provider.NEEDS_KEY or bool(provider._active_key(backend))
        out["key_present"] = key_present
        # Nothing ships a default model (provider.NoModelConfigured): an empty model id
        # means every request raises, which is the opposite of ready.
        out["ready"] = bool(key_present and model)
        out["reason"] = None if out["ready"] else ("no_key" if not key_present else "no_model")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "health: LLM readiness resolution failed", counter="health.llm")
    return out


@router.get("/health")
def health():
    from aughor.control_plane.object_store import TOKEN_ENV, available
    from aughor.demo.setup import fixture_db_path
    # Uploads are the one path whose durability is invisible from everywhere else.
    # A vended capability's files live under /tmp on a serverless instance and are
    # mirrored to Blob only when a token is configured; without one, mirror_up and
    # mirror_down are no-ops and every upload silently lasts until the instance is
    # recycled. Nothing reported that — not here, not /capabilities — so the failure
    # presented as files that uploaded fine and were gone later.
    # The ledger's startup quick_check (kernel/ledger.py). Three SIGBUS-corruptions in
    # three days were each found by accident, hours later, because every writer is
    # best-effort; this is where an operator (or the frontend's health poll) sees it.
    try:
        from aughor.kernel.ledger import Ledger
        ledger_error = Ledger.default().integrity_error
    except Exception as exc:
        ledger_error = f"{type(exc).__name__}: {exc}"
    # A store whose WAL index moved under a live mapping cannot be repaired in-process
    # (db/backend.check_wal_drift) — the only recovery is a restart, so this has to reach
    # an operator the same way a ledger integrity failure does, rather than sit in a log.
    try:
        from aughor.db.backend import wal_keepalive_report
        wal = wal_keepalive_report()
        wal_drifted = sorted(wal.get("drifted_paths") or [])
    except Exception as exc:
        wal_drifted = []
        wal = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "degraded" if (ledger_error or wal_drifted) else "ok",
        "ledger": {"ok": not ledger_error, "error": ledger_error},
        "stores": {
            "ok": not wal_drifted,
            "wal_drifted": wal_drifted,
            "held": wal.get("held"),
            "detail": (
                f"{len(wal_drifted)} store(s) lost their WAL index under a live mapping; "
                "this process is exposed to SIGBUS in walFindFrame — restart the server"
                if wal_drifted else "every store holds its WAL index"
            ),
        },
        "fixture_db": fixture_db_path().exists(),
        "llm": _llm_readiness(),
        "object_store": {
            "configured": available(),
            "env": TOKEN_ENV,
            "detail": (
                "durable: uploads mirror to Vercel Blob"
                if available()
                else f"ephemeral: {TOKEN_ENV} unset, uploads live only on the serving instance"
            ),
        },
    }


@router.get("/diagnostics/wal-keepalive")
def wal_keepalive_diagnostics():
    """What the store WAL keepalive holds, and whether anything has been stranded.

    The SIGBUS that ate the API for a week (#379, #383) leaves no traceback and names no
    file — a crash report describes the victim only as a 32 KB mapped region. This is the
    surface that can name it: every held store with the `-shm` inode recorded when we
    attached beside the one on disk now. `drifted` on any store means some actor moved
    that store's WAL index under a live mapping, which is the crash's precondition.
    """
    from aughor.db.backend import wal_keepalive_report
    return wal_keepalive_report()


@router.get("/capabilities")
def get_capabilities(request: Request, connection_id: str | None = None):
    """The active tier + the capabilities the caller can exercise, for the frontend to
    show/lock/upsell UI. Defaults to the `enterprise` tier (everything on) until a lower
    tier is assigned.

    The capability set is **role-aware** (RBAC P2): it's the tier's grant intersected
    with the caller's role ceiling, so a viewer's UI reflects its role — not just the
    org's plan. In localhost / identity-off mode this is exactly the tier set (unchanged).
    """
    from aughor.licensing import resolve_tier
    from aughor.rbac import effective_capabilities, resolve_roles
    from aughor.security.authz import get_principal, require_identity_enabled
    principal = get_principal(request)
    tier = resolve_tier(connection_id)
    caps = effective_capabilities(principal, connection_id)
    return {
        "tier": tier.value,
        "capabilities": sorted(c.value for c in caps),
        "roles": resolve_roles(principal),
        # Whether tenants are distinguishable at all. Per-org settings — BYOK keys
        # being the first — are meaningless without it: in localhost/identity-off
        # mode there is exactly one org, so an "org override" can only ever restate
        # the deployment config. The frontend uses this to hide such controls rather
        # than offer a second, identical place to configure the same thing.
        "multi_tenant": require_identity_enabled(),
    }


@router.get("/system/flags")
def get_system_flags():
    """Operator feature flags (runtime override > env). For Settings → System."""
    from aughor.kernel.flags import list_flags
    return list_flags()


class _FlagPatch(BaseModel):
    value: Optional[bool] = None
    state: Optional[str] = None      # "on" | "off" | "auto" — "auto" clears the override (follows env/Auto-mode)


@router.put("/system/flags/{name}")
def set_system_flag(name: str, body: _FlagPatch):
    from aughor.kernel.flags import FLAG_ENV, clear_flag, list_flags, set_flag
    if name not in FLAG_ENV:
        raise HTTPException(status_code=404, detail=f"unknown flag '{name}'")
    if body.state is not None:
        st = body.state.strip().lower()
        if st == "auto":
            clear_flag(name)              # drop the override → the env var / Auto-mode master decides
        elif st in ("on", "off"):
            set_flag(name, st == "on")
        else:
            raise HTTPException(status_code=422, detail=f"invalid state '{body.state}' (on|off|auto)")
    elif body.value is not None:
        set_flag(name, body.value)        # legacy binary path
    else:
        raise HTTPException(status_code=422, detail="provide `state` (on|off|auto) or `value`")
    return list_flags()[name]


@router.get("/dev/stats")
def get_dev_stats():
    """Return in-process stats counters."""
    from aughor.stats import stats
    return stats.snapshot()


@router.post("/dev/stats/reset")
def reset_dev_stats():
    """Reset all counters to zero."""
    from aughor.stats import stats
    stats.reset()
    return {"ok": True}


class _Suggestion(BaseModel):
    text: str
    mode: str   # "ask" | "investigate"


class _Suggestions(BaseModel):
    suggestions: list[_Suggestion]


@router.get("/suggestions")
async def get_suggestions(connection_id: str = BUILTIN_ID):
    """Return 6 starter questions tailored to the schema of the given connection."""
    from aughor.semantic.suggestions_cache import (
        schema_fingerprint, get_cached, store as cache_store, compute_once,
    )
    from aughor.db.connection import open_connection_for

    loop = asyncio.get_running_loop()

    try:
        db = open_connection_for(connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        schema_summary: str = await loop.run_in_executor(None, db.get_schema)
        db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    fingerprint = schema_fingerprint(schema_summary)

    # R13 — the named research-starter playbooks + per-space curated questions
    # (deterministic templates, no model). Computed before the cache check so they
    # ride cache hits too. Unconditional since flag endgame Wave 2 (2026-08-06,
    # receipt 3155c4d9de61 — deterministic payload, additive `starters` key).
    _starters: list[dict] | None = None
    try:
        from aughor.starters import starter_payload
        _starters = await loop.run_in_executor(
            None, lambda: starter_payload(connection_id))
    except Exception as _st_exc:
        from aughor.kernel.errors import tolerate
        tolerate(_st_exc, "starter library is best-effort",
                 counter="starters.library", conn_id=connection_id or None)
        _starters = []

    try:
        cached = get_cached(connection_id, fingerprint)
        if cached:
            out = {"suggestions": cached, "cached": True}
            if _starters is not None:
                out["starters"] = _starters
            return out
    except Exception as _c_exc:
        # A configured-but-down backend lands here on EVERY request, and the cost of
        # not knowing is a 40s+ model call each time. Degrade, but leave a trace —
        # this was silent, and silence is why it went unnoticed.
        from aughor.kernel.errors import tolerate
        tolerate(_c_exc, "suggestions cache read is best-effort; falling back to the model",
                 counter="suggestions.cache_read", conn_id=connection_id or None)

    enrichment = ""
    try:
        from aughor.explorer.store import render_exploration_annotations
        _ea = render_exploration_annotations(connection_id)
        if _ea:
            enrichment += f"\n\nEXPLORATION FINDINGS (interesting patterns already discovered):\n{_ea}"
    except Exception:
        pass
    try:
        from aughor.semantic.metrics import build_metrics_block
        _mb = build_metrics_block()
        if _mb:
            enrichment += f"\n\n{_mb}"
    except Exception:
        pass
    # R14 — what people actually query steers the starters toward the live tables.
    try:
        from aughor.sql.popularity import most_queried_block
        _pop = most_queried_block(connection_id)
        if _pop:
            enrichment += f"\n\n{_pop}"
    except Exception as _pop_exc:
            from aughor.kernel.errors import tolerate
            tolerate(_pop_exc, "popularity suggestions block is best-effort",
                     counter="obs.popularity", conn_id=connection_id or None)

    _system = (
        "You are a data analyst assistant. Given a database schema and any domain intelligence, "
        "produce exactly 6 starter questions a business user might ask. "
        "Mix question types: 4 should be simple analytical questions (mode='ask') and "
        "2 should be deeper diagnostic questions (mode='investigate'). "
        "Make every question specific to the actual table and column names provided — "
        "no generic placeholders. Keep each question concise (under 12 words)."
    )
    _user = f"Database schema:\n{schema_summary}{enrichment}\n\nReturn 6 starter questions."

    def _llm_work():
        from aughor.llm.provider import get_provider
        result: _Suggestions = get_provider("coder").complete(
            system=_system,
            user=_user,
            response_model=_Suggestions,
            temperature=0.4,
        )
        return [s.model_dump() for s in result.suggestions]

    try:
        # Single-flighted: concurrent requests for the same (connection, schema) share
        # one model call instead of each buying the identical answer.
        suggestions = await loop.run_in_executor(
            None, lambda: compute_once(connection_id, fingerprint, _llm_work))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        cache_store(connection_id, fingerprint, suggestions)
    except Exception as _s_exc:
        from aughor.kernel.errors import tolerate
        tolerate(_s_exc, "suggestions cache write is best-effort; the process-local "
                         "layer still holds it for this process",
                 counter="suggestions.cache_write", conn_id=connection_id or None)

    out = {"suggestions": suggestions, "cached": False}
    if _starters is not None:
        out["starters"] = _starters
    return out


@router.get("/connectors/types")
def list_connector_types():
    """Return all registered connector types with form field descriptors.

    Each type carries whether its driver is importable HERE. The registry defers
    driver imports to `connect()`, so without this the picker advertises fifteen
    tiles on a deployment that can serve about half of them, and the user finds out
    by filling in a form and getting an ImportError back. `available` is computed per
    request rather than cached: it is a `find_spec` call per type, and an install can
    change under a running process.
    """
    from aughor.connectors.registry import (
        CATEGORIES, DSN_PREVIEWS, FORM_FIELDS, REGISTRY, missing_drivers,
    )
    types = []
    for conn_type in ["duckdb", "postgres"] + REGISTRY.supported_types():
        missing = missing_drivers(conn_type)
        types.append({
            "type":        conn_type,
            "dsn_preview": DSN_PREVIEWS.get(conn_type, conn_type),
            "fields":      FORM_FIELDS.get(conn_type, []),
            "available":   not missing,
            "missing":     missing,
            "category":    CATEGORIES.get(conn_type, "built-in"),
        })
    return {"types": types}
