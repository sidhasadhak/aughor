"""
Persistence for exploration state and findings.

Keys in the ``exploration`` family store (KeyedJsonStore/Ledger facade — per-key
transactional, Postgres-capable behind AUGHOR_DB_URL):
    {connection_id}               # the bare connection run
    {connection_id}__{schema}     # a per-schema run
    canvas_{canvas_id}            # a canvas-scoped run

Legacy layout was one file per key (``data/exploration_{key}.json``); each key
imports on first touch and the file stays as the on-disk record until purge. This
state is what Phase 2's sliced execution resumes from, so it must be readable
across processes — a local file was the last single-process assumption here.
"""
from __future__ import annotations

import json
from typing import Optional

from aughor.db.paths import state_dir
from aughor.explorer.models import ExplorationPhase
from aughor.util.json_store import FileFamilyStore

# Honours AUGHOR_STATE_DIR — this store had NO override and the suite destroyed a real
# exploration_workspace.json (2026-07-21). See aughor/db/paths.py.
_DATA_DIR = state_dir()


def _family() -> FileFamilyStore:
    # Per call, not a module global: _DATA_DIR is the seam tests monkeypatch, and a
    # store captured at import would keep writing to the real one (db/paths.py trap).
    return FileFamilyStore(_DATA_DIR, "exploration_")


def _canvas_key(canvas_id: str) -> str:
    return f"canvas_{canvas_id}"


def _empty() -> dict:
    return {
        "schema_fingerprint": None,
        "phase": ExplorationPhase.PENDING.value,
        "null_meanings": {},        # {"table:column": {meaning, business_rule, ...}}
        "join_verifications": [],   # [{"key", "orphan_count", "verified", "cardinality", ...}]
        "lifecycle_maps": {},       # {"table": {status_column, states, terminal_states, ...}}
        "distributions": {},        # {"table:column": {shape, p25, p50, p75, ...}}
        "insights": [],             # [{id, domain, angle, finding, sql, novelty, ...}]
        "domain_budgets": {},       # {domain: queries_used}
        "domain_coverage": {},      # {domain: [angles_covered]}
    }


def load(connection_id: str) -> dict:
    try:
        entry = _family().get_entry(connection_id)
        if entry is not None:
            return entry
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "exploration state read is best-effort; empty state used on error", counter="explorer.store.read")
    return _empty()


def save(connection_id: str, state: dict) -> None:
    try:
        _family().put(connection_id, json.loads(json.dumps(state, default=str)))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "exploration state write is best-effort; next save retries", counter="explorer.store.write")


def has_state(store_key: str) -> bool:
    """Whether a run state exists under this key — the store-aware replacement for
    the ``exploration_{key}.json``.exists() checks routers used to make."""
    try:
        return _family().has_entry(store_key)
    except Exception:
        return False


def is_complete(connection_id: str, schema_fingerprint: str | None = None) -> bool:
    """True if exploration is marked complete (and optionally fingerprint matches)."""
    state = load(connection_id)
    if state.get("phase") != ExplorationPhase.COMPLETE.value:
        return False
    if schema_fingerprint is not None:
        return state.get("schema_fingerprint") == schema_fingerprint
    return True


def get_insights(connection_id: str, include_invalid: bool = False) -> list[dict]:
    ins = load(connection_id).get("insights", [])
    return ins if include_invalid else [i for i in ins if not i.get("invalid")]


def get_domain_insights(connection_id: str, include_invalid: bool = False) -> dict[str, list[dict]]:
    """Findings grouped by domain. Quarantined (invalid-flagged) ones
    are excluded by default — kept in the store for inspection, hidden from intel."""
    grouped: dict[str, list[dict]] = {}
    for ins in get_insights(connection_id, include_invalid=include_invalid):
        d = ins.get("domain", "General")
        grouped.setdefault(d, []).append(ins)
    return grouped


# ── 'All schemas' aggregate ───────────────────────────────────────────────────
# A multi-schema connection runs PER schema (state keyed {conn}__{schema}). These helpers
# merge those per-schema states into one connection-level view for the 'All schemas'
# selection — so the Briefing shows EVERY schema's findings together, while a specific
# schema selection still reads just that schema's (natively isolated) state.

def schema_run_keys(connection_id: str) -> list[str]:
    """Store keys ({conn}__{schema}) of this connection's per-schema runs, or [] if none."""
    return _family().keys_with_prefix(f"{connection_id}__")


def _agg_phase(phases: list[str]) -> str:
    """The connection's phase, from its per-schema phases.

    FAILED is terminal, but terminal is not success. Collapsing every terminal
    phase to COMPLETE answered "has it stopped running?" when the caller asked
    "did it work?" — so a connection whose schemas had ALL failed reported a
    healthy completion, and the only trace was `per_schema`, which nothing
    surfaced. Reported as: status healthy, `error: null`, most schemas failed.

    A mixed run still reports COMPLETE, which is honest — those schemas really
    did finish and their findings are real. The failures in that case are named
    by the `error` field instead (see `routers/exploration.py`), because a phase
    is one word and cannot say which schemas fell over.
    """
    terminal = {ExplorationPhase.COMPLETE.value, ExplorationPhase.FAILED.value}
    if phases and all(p in terminal for p in phases):
        if all(p == ExplorationPhase.FAILED.value for p in phases):
            return ExplorationPhase.FAILED.value      # nothing succeeded
        return ExplorationPhase.COMPLETE.value
    for p in phases:                      # any schema still running → report its live phase
        if p not in terminal:
            return p
    return ExplorationPhase.PENDING.value


def load_aggregate(connection_id: str) -> dict:
    """Merge every per-schema run into one connection-level state. Falls back to the bare
    connection state when there are no per-schema runs.

    The bare state's CONTENT is merged in too (fix-saved findings and pre-schema-era
    data land there), but its phase is ignored — an empty bare file must not report
    a completed multi-schema exploration as 'pending'."""
    keys = schema_run_keys(connection_id)
    if not keys:
        return load(connection_id)
    agg = _empty()
    phases: list[str] = []
    per_schema: dict[str, str] = {}
    q = tt = 0
    for k in [connection_id, *keys]:
        st = load(k)
        agg["insights"].extend(st.get("insights", []) or [])
        agg["join_verifications"].extend(st.get("join_verifications", []) or [])
        for sect in ("null_meanings", "distributions", "lifecycle_maps",
                     "domain_budgets", "domain_coverage"):
            agg[sect].update(st.get(sect, {}) or {})
        if k == connection_id:
            continue  # content only — the bare state carries no run phase/counters
        schema = k.split("__", 1)[1] if "__" in k else k
        per_schema[schema] = st.get("phase", "pending")
        phases.append(st.get("phase", "pending"))
        q += int(st.get("queries_executed", 0) or 0)
        tt += int(st.get("tables_total", 0) or 0)
    agg["phase"] = _agg_phase(phases)
    agg["queries_executed"] = q
    agg["tables_total"] = tt
    agg["per_schema"] = per_schema          # {schema: phase} — lets the UI show per-schema progress
    return agg


def get_aggregate_domain_insights(connection_id: str, include_invalid: bool = False) -> dict[str, list[dict]]:
    """by_domain findings merged across all per-schema runs of a connection. Each one is
    tagged with its `source_schema` so the briefing can keep UNRELATED businesses apart
    (a beauty-ecommerce finding and a bakery finding must not be synthesized as one story)."""
    grouped: dict[str, list[dict]] = {}
    for k in schema_run_keys(connection_id):
        sch = k.split("__", 1)[1] if "__" in k else ""
        for d, ins in get_domain_insights(k, include_invalid=include_invalid).items():
            for i in ins:
                if sch:
                    i.setdefault("source_schema", sch)
            grouped.setdefault(d, []).extend(ins)
    return grouped


def extend_domain_budget(connection_id: str, domain: str, extra: int = 5) -> int:
    """Add `extra` queries to a domain's budget cap. Returns the new cap value."""
    state = load(connection_id)
    key = f"{domain}__cap"
    current = state.get("domain_budgets", {}).get(key, 15)
    new_cap = current + extra
    state.setdefault("domain_budgets", {})[key] = new_cap
    save(connection_id, state)
    return new_cap


def get_lifecycle_maps(connection_id: str) -> dict:
    return load(connection_id).get("lifecycle_maps", {})


def get_null_meanings(connection_id: str) -> dict:
    return load(connection_id).get("null_meanings", {})


_NULL_MEANING_LABELS: dict[str, str] = {
    "pending":                  "event not yet occurred",
    "not_applicable_terminal":  "entity in terminal state — will never occur",
    "missing":                  "data quality issue — value should exist",
    "mixed":                    "pattern varies by status (check lifecycle)",
    "not_applicable":           "always populated (null rate ≈ 0)",
    "unknown":                  "meaning unclear",
}


def render_exploration_annotations(connection_id: str) -> str:
    """
    Return a formatted intelligence block for injection into the schema context.

    Only includes sections that have data.  Returns "" when exploration has not
    yet produced any findings (pending / failed phase, or no data written yet).
    """
    # Aggregate across per-schema runs — reading only the bare state silently
    # returned "" for every multi-schema connection, starving the ADA planner
    # and the ontology overlay of the explorer's verified intelligence.
    state = load_aggregate(connection_id)
    phase = state.get("phase", "pending")
    if phase in ("pending", "failed"):
        return ""

    sections: list[str] = []

    # ── Null semantics ────────────────────────────────────────────────────────
    null_meanings: dict = state.get("null_meanings", {})
    meaningful = {k: v for k, v in null_meanings.items()
                  if v.get("meaning") not in ("not_applicable", "unknown")}
    if meaningful:
        lines = [
            "NULL SEMANTICS (verified — NULL in these columns carries business meaning):"
        ]
        for key, nm in meaningful.items():
            col_label = key.replace(":", ".")
            label = _NULL_MEANING_LABELS.get(nm.get("meaning", ""), nm.get("meaning", ""))
            rate = nm.get("null_rate", 0)
            line = f"  {col_label}: NULL = {label}  ({rate:.0%} null rate)"
            if nm.get("business_rule"):
                line += f"\n    rule: {nm['business_rule']}"
            lines.append(line)
        sections.append("\n".join(lines))

    # ── Entity lifecycle ───────────────────────────────────────────────────────
    lifecycle_maps: dict = state.get("lifecycle_maps", {})
    if lifecycle_maps:
        lines = ["ENTITY LIFECYCLE (verified state machines):"]
        for table, lm in lifecycle_maps.items():
            col = lm.get("status_column", "?")
            active   = lm.get("active_states", [])
            terminal = lm.get("terminal_states", [])
            active_str   = ", ".join(active)   if active   else "—"
            terminal_str = ", ".join(terminal) if terminal else "—"
            lines.append(f"  {table}.{col}")
            lines.append(f"    active:   {active_str}")
            lines.append(f"    terminal: {terminal_str}")
            if terminal:
                tl = ", ".join(f"'{s}'" for s in terminal)
                lines.append(f"    active filter: {col} NOT IN ({tl})")
        sections.append("\n".join(lines))

    # ── Join verification ──────────────────────────────────────────────────────
    join_verifications: list = state.get("join_verifications", [])
    broken = [j for j in join_verifications if not j.get("verified") and j.get("orphan_count", 0) > 0]
    if broken:
        lines = ["JOIN INTEGRITY (caution — orphaned FK rows detected):"]
        for j in broken:
            lines.append(
                f"  {j['from_table']}.{j['from_col']} → {j['to_table']}.{j['to_col']}"
                f"  ({j['orphan_count']:,} orphan rows)"
            )
        sections.append("\n".join(lines))

    # ── Domain intelligence findings ──────────────────────────────────────────
    insights: list = state.get("insights", [])
    if insights:
        # Group by domain for the schema context block
        by_domain: dict[str, list] = {}
        for ins in insights:
            d = ins.get("domain", "General")
            by_domain.setdefault(d, []).append(ins)
        lines = ["BUSINESS INTELLIGENCE (domain-level findings, autonomously discovered):"]
        for domain, dins in by_domain.items():
            lines.append(f"  [{domain}]")
            for ins in dins[:4]:
                lines.append(f"    • {ins.get('finding', '')}")
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = (
        "EXPLORATION INTELLIGENCE"
        f" [{ExplorationPhase(phase).name if phase in ExplorationPhase._value2member_map_ else phase}]"  # type: ignore[attr-defined]
        " — background cartography, treat as authoritative:"
    )
    return header + "\n\n" + "\n\n".join(sections)


# ── Canvas-scoped variants ────────────────────────────────────────────────────

def load_canvas(canvas_id: str) -> dict:
    return load(_canvas_key(canvas_id))


def save_canvas(canvas_id: str, state: dict) -> None:
    save(_canvas_key(canvas_id), state)


def canvas_ids_with_state() -> list[str]:
    """Every canvas id that has exploration state — store keys and legacy files."""
    return [k[len("canvas_"):] for k in _family().keys_with_prefix("canvas_")]


def purge_connection_state(connection_id: str) -> int:
    """Drop the bare + every per-schema run for a connection (store rows AND legacy
    files), counted once per key. The seam db/purge.py calls — deletion semantics
    live here, next to the naming they must match, not as globs in the cascade."""
    return _family().purge_entries(exact=[connection_id], key_prefix=f"{connection_id}__")


def purge_schema_state(connection_id: str, schema: str) -> int:
    """Drop one schema's run AND the stale bare aggregate; sibling schemas stay."""
    return _family().purge_entries(exact=[f"{connection_id}__{schema}", connection_id])


def get_insights_canvas(canvas_id: str, include_invalid: bool = False) -> list[dict]:
    ins = load_canvas(canvas_id).get("insights", [])
    return ins if include_invalid else [i for i in ins if not i.get("invalid")]


def get_domain_insights_canvas(canvas_id: str, include_invalid: bool = False) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for ins in get_insights_canvas(canvas_id, include_invalid=include_invalid):
        d = ins.get("domain", "General")
        grouped.setdefault(d, []).append(ins)
    return grouped


def extend_domain_budget_canvas(canvas_id: str, domain: str, extra: int = 5) -> int:
    state = load_canvas(canvas_id)
    key = f"{domain}__cap"
    current = state.get("domain_budgets", {}).get(key, 15)
    new_cap = current + extra
    state.setdefault("domain_budgets", {})[key] = new_cap
    save_canvas(canvas_id, state)
    return new_cap


def promote_insight(canvas_id: str, insight_id: str) -> bool:
    """Mark a canvas finding as promoted to Org intelligence. Returns True on success."""
    state = load_canvas(canvas_id)
    for ins in state.get("insights", []):
        if ins.get("id") == insight_id:
            ins["promoted_to_org"] = True
            ins["promotion_confidence"] = ins.get("confidence", 0.0)
            save_canvas(canvas_id, state)
            return True
    return False


def _find_insight_state(connection_id: str, insight_id: str):
    """Locate the store key + state + finding for an id, searching the bare
    connection state AND every per-schema run ({conn}__{schema}).

    Multi-schema connections store findings per schema, but the promote/dismiss
    endpoints receive only the connection id — looking in the bare file alone
    made those buttons 404 on every per-schema finding (a dead button)."""
    for key in [connection_id, *schema_run_keys(connection_id)]:
        state = load(key)
        for ins in state.get("insights", []):
            if ins.get("id") == insight_id:
                if "__" in key:
                    ins.setdefault("source_schema", key.split("__", 1)[1])
                return key, state, ins
    return None, None, None


def promote_insight_conn(connection_id: str, insight_id: str) -> Optional[dict]:
    """Mark a connection-scoped insight as promoted to Org intelligence.

    Returns the promoted insight dict on success, None if the insight is not found.
    Mirrors promote_insight() but operates on connection-scoped exploration state
    (bare or per-schema) so Briefing/Hub findings that live at the connection
    level — not just canvas insights — can be promoted org-wide.
    """
    key, state, ins = _find_insight_state(connection_id, insight_id)
    if ins is None:
        return None
    ins["promoted_to_org"] = True
    ins["promotion_confidence"] = ins.get("confidence", 0.0)
    save(key, state)
    return ins


def _log_dismissal(scope: str, insight: dict, reason: str) -> None:
    """Append a dismissal to data/finding_dismissals.jsonl. User reasons are signal
    for new guards / eval fixtures — the dismiss-with-reason feedback loop."""
    try:
        rec = {
            "scope": scope, "id": insight.get("id"), "reason": reason,
            "finding": insight.get("finding"), "sql": insight.get("sql"),
            "domain": insight.get("domain"), "angle": insight.get("angle"),
        }
        with (_DATA_DIR / "finding_dismissals.jsonl").open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "dismissal-log append is best-effort feedback signal; dismissal itself still applied", counter="explorer.store.dismissal_log")


def _dismiss(state: dict, insight_id: str, reason: str, scope: str) -> Optional[dict]:
    for ins in state.get("insights", []):
        if ins.get("id") == insight_id:
            # Reuse the quarantine flag: hidden from intel (the read path filters
            # `invalid`), KEPT in the store, reversible. Never deletes.
            ins["invalid"] = True
            ins["invalid_reason"] = f"dismissed by user: {reason}" if reason else "dismissed by user"
            _log_dismissal(scope, ins, reason)
            return ins
    return None


def dismiss_insight_conn(connection_id: str, insight_id: str, reason: str = "") -> Optional[dict]:
    """User-dismiss a connection insight with a reason. Returns the insight or None.
    Searches per-schema runs too — same lookup as promote (the dismiss button was
    equally dead on multi-schema findings)."""
    key, state, found = _find_insight_state(connection_id, insight_id)
    if found is None:
        return None
    ins = _dismiss(state, insight_id, reason, key)
    if ins is not None:
        save(key, state)
    return ins


def dismiss_insight_canvas(canvas_id: str, insight_id: str, reason: str = "") -> Optional[dict]:
    state = load_canvas(canvas_id)
    ins = _dismiss(state, insight_id, reason, f"canvas:{canvas_id}")
    if ins is not None:
        save_canvas(canvas_id, state)
    return ins


def canvas_has_state(canvas_id: str) -> bool:
    return has_state(_canvas_key(canvas_id))


#: The phases an exploration does not come back from. Derived from the enum, never
#: spelled: a renamed member would otherwise stop matching silently, and a boot check
#: that quietly stops matching re-runs every exploration on every restart.
TERMINAL_PHASES: tuple[str, ...] = (ExplorationPhase.COMPLETE.value,
                                    ExplorationPhase.FAILED.value)


def is_unfinished(state: dict) -> bool:
    """Does this saved exploration state have work left?

    A MISSING phase counts as unfinished, which is the safe direction: an unrecognised
    state might be mid-run, and resuming one that was done costs a re-run while skipping
    one that was not loses the work outright.
    """
    return str((state or {}).get("phase", "")) not in TERMINAL_PHASES


def canvas_needs_resume(canvas_id: str) -> bool:
    """Should a boot resume this canvas's explorer?

    Boot recovery exists for the exploration a previous process INTERRUPTED — one whose
    saved phase is still mid-run. A `complete` or `failed` canvas has already reached its
    end; re-spawning it is not recovery, it is a fresh exploration nobody asked for, and
    (measured 2026-08-30) `spawn_explorer` waves it through because its own guard only
    refuses an exploration that is *currently running*. Two canvases in that state meant
    two full re-explorations on every single restart, each one spending model tokens.

    The connection path already worked this way — `_kernel_boot_recovery` skips a
    terminal aggregate phase, with a comment saying recovery "kept re-spawning explorers
    for explorations that had already completed". The canvas path never got the same
    check. This is that check, in one place both paths read.

    A `failed` exploration is restartable on demand (`POST /exploration/{id}/start`);
    what it must not be is retried forever, with no backoff and no cap, by the act of
    restarting the server.
    """
    return canvas_has_state(canvas_id) and is_unfinished(load_canvas(canvas_id))
