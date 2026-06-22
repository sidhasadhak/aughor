"""Learned skills — agent procedural memory.

A "skill" is a reusable, governed `OntologyAction` (origin='learned') crystallized from a
finished investigation: its grounded, read-only SQL — conservatively parameterized so a
WHERE literal becomes a `{param}` — saved so the planner can re-run that analysis instead of
re-deriving it. Skills live in their own `{conn}:{schema}`-keyed store so they survive ontology
rebuilds; they re-enter the live graph via `ontology.store._overlay_learned_actions` (structural
actions win on id collision). Persistence is manual-confirm by default (propose → confirm → save,
EXPLAIN-gated); auto-promotion is reserved for an earned autonomy level that isn't built yet.

Replaces the inert stubs. The call sites + contracts are in `routers/ontology.py`,
`ontology/store.py`, and the investigation stream (`routers/investigations.py`).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from aughor.util.json_store import KeyedJsonStore

logger = logging.getLogger(__name__)

# {conn}:{schema} -> {action_id: OntologyAction.model_dump()}. Ledger-backed (transactional),
# survives ontology rebuilds (the structural fingerprint cache never bakes these in).
_STORE = KeyedJsonStore("data/learned_actions.json")

_MAX_PARAMS = 4   # a skill with more free parameters than this isn't a clean reusable template


def _key(connection_id: str, schema_name: str) -> str:
    return f"{connection_id}:{schema_name or 'default'}"


def resolve_active_schema(connection_id: str) -> str:
    """The schema key skills are stored under — the schema of this connection's most-recently
    built ontology, so a saved skill keys to the SAME schema the planner overlays from. Falls
    back to 'default' when no ontology exists yet."""
    try:
        from aughor.ontology.store import load_latest_ontology
        g = load_latest_ontology(connection_id, None)
        if g is not None and getattr(g, "schema_name", ""):
            return g.schema_name
    except Exception as exc:
        logger.debug("resolve_active_schema(%s) fell back to default: %s", connection_id, exc)
    return "default"


# ── load / persist ────────────────────────────────────────────────────────────────

def load_learned_actions(connection_id: str, schema_name: str) -> dict[str, Any]:
    """Map of learned `OntologyAction`s by id for this {conn}:{schema}. Deserialized from the
    store; a row that can't be parsed is skipped (never breaks the ontology overlay)."""
    from aughor.ontology.models import OntologyAction
    out: dict[str, Any] = {}
    try:
        raw = _STORE.get(_key(connection_id, schema_name), {}) or {}
    except Exception as exc:
        logger.debug("load_learned_actions(%s) store read failed: %s", connection_id, exc)
        return {}
    for aid, dump in raw.items():
        try:
            out[aid] = OntologyAction(**dump)
        except Exception as exc:
            logger.debug("learned skill %s skipped (unparseable): %s", aid, exc)
    return out


def _persist(connection_id: str, schema_name: str, actions: dict[str, Any]) -> None:
    _STORE.put(_key(connection_id, schema_name), {aid: a.model_dump() for aid, a in actions.items()})


def save_skill(
    connection_id: str,
    schema_name: str,
    action: Any,
    validator: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Persist a confirmed learned skill. Gated: when a `validator` is given (a read-only
    EXPLAIN dry-run), the skill's SQL — with its `{param}` placeholders substituted by their
    declared defaults — must validate, else it is NOT saved (a skill that can't run is worse
    than none). Returns True on save. Best-effort on the store write."""
    if action is None or not getattr(action, "id", ""):
        return False
    if validator is not None:
        concrete = _materialize(getattr(action, "sql_template", "") or "", getattr(action, "parameters", []) or [])
        try:
            if not concrete or not validator(concrete):
                logger.info("learned skill %s rejected: SQL did not validate", action.id)
                return False
        except Exception as exc:
            logger.info("learned skill %s rejected: validator error %s", action.id, exc)
            return False
    try:
        actions = load_learned_actions(connection_id, schema_name)
        action.origin = "learned"
        actions[action.id] = action
        _persist(connection_id, schema_name, actions)
        return True
    except Exception as exc:
        logger.warning("save_skill(%s) failed: %s", getattr(action, "id", "?"), exc)
        return False


def record_skill_use(connection_id: str, schema_name: str, action_id: str) -> int:
    """Increment a skill's `usage_count` (feeds per-skill reuse signal). Returns the new count,
    or 0 when the skill isn't found."""
    try:
        actions = load_learned_actions(connection_id, schema_name)
        a = actions.get(action_id)
        if a is None:
            return 0
        a.usage_count = int(getattr(a, "usage_count", 0) or 0) + 1
        _persist(connection_id, schema_name, actions)
        return a.usage_count
    except Exception as exc:
        logger.debug("record_skill_use(%s) failed: %s", action_id, exc)
        return 0


def delete_skill(connection_id: str, schema_name: str, action_id: str) -> bool:
    """Delete a learned skill. Returns True if one was removed."""
    try:
        actions = load_learned_actions(connection_id, schema_name)
        if action_id not in actions:
            return False
        del actions[action_id]
        _persist(connection_id, schema_name, actions)
        return True
    except Exception as exc:
        logger.debug("delete_skill(%s) failed: %s", action_id, exc)
        return False


# ── crystallization: a finished investigation → a candidate skill ───────────────────

_MUTATING_RE = re.compile(r"\b(insert|update|delete|drop|create|alter|truncate|merge|copy|grant|revoke)\b", re.I)


def _is_read_only(sql: str) -> bool:
    s = (sql or "").strip().lower()
    return bool(s) and (s.startswith("select") or s.startswith("with")) and not _MUTATING_RE.search(s)


def _primary_sql(inv: dict) -> str:
    """The investigation's representative SQL: the report's headline query, else the last
    successful query in the history."""
    report = inv.get("report") or {}
    cand = (report.get("sql") or "").strip() if isinstance(report, dict) else ""
    if cand:
        return cand
    for q in reversed(inv.get("query_history") or []):
        if isinstance(q, dict) and (q.get("sql") or "").strip() and not q.get("error"):
            return q["sql"].strip()
    return ""


def _finding_text(inv: dict) -> str:
    r = inv.get("report") or {}
    if isinstance(r, dict):
        for k in ("headline", "verdict", "summary", "answer"):
            v = r.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _primary_table(sql: str) -> str:
    try:
        import sqlglot
        from sqlglot import exp
        t = sqlglot.parse_one(sql, read="duckdb").find(exp.Table)
        return t.name if t else ""
    except Exception:
        return ""


def _infer_action_type(sql: str) -> str:
    s = (sql or "").lower()
    if re.search(r"\b(sum|avg|count|min|max)\s*\(|\bgroup\s+by\b", s):
        return "aggregate"
    if re.search(r"\bwhere\b", s):
        return "filter"
    return "compute"


def _skill_id(question: str, table: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (question or table or "").lower()).strip("_")[:48]
    return f"learned_{base or 'skill'}"


def _parameterize_sql(sql: str, dialect: str = "duckdb"):
    """Turn top-level ``col = <literal>`` WHERE predicates into ``{param}`` placeholders so the
    skill is reusable, returning (templated_sql, [ActionParameter]). Conservative: equality on a
    string/number literal only, ≤4 params, fail-open to (sql, []) on anything it can't prove."""
    from aughor.ontology.models import ActionParameter
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql, []
    if not isinstance(tree, exp.Select):
        return sql, []
    where = tree.args.get("where")
    if where is None:
        return sql, []

    def _conjuncts(node):
        if isinstance(node, exp.Paren):
            return _conjuncts(node.this)
        if isinstance(node, exp.And):
            return _conjuncts(node.left) + _conjuncts(node.right)
        return [node]

    params: list = []
    used: set = set()
    for eq in _conjuncts(where.this):
        if not isinstance(eq, exp.EQ):
            continue
        col = lit = None
        if isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Literal):
            col, lit = eq.left, eq.right
        elif isinstance(eq.right, exp.Column) and isinstance(eq.left, exp.Literal):
            col, lit = eq.right, eq.left
        if col is None:
            continue
        name, base, i = col.name.lower(), col.name.lower(), 1
        while name in used:
            name, i = f"{base}_{i}", i + 1
        used.add(name)
        params.append(ActionParameter(
            name=name, display_name=col.name,
            data_type=("VARCHAR" if lit.is_string else "INTEGER"),
            required=True, default_value=str(lit.this),
            description=f"Filter value for {col.name}"))
        lit.replace(exp.column(f"__PARAM_{name}__"))
        if len(params) >= _MAX_PARAMS:
            break
    if not params:
        return sql, []
    templated = tree.sql(dialect=dialect)
    for p in params:
        templated = templated.replace(f"__PARAM_{p.name}__", "{" + p.name + "}")
    return templated, params


def _materialize(template: str, params: list) -> str:
    """Substitute each ``{param}`` with its declared default (a type-appropriate dummy when
    absent) so the templated SQL is a concrete, EXPLAIN-able query for the save-time gate."""
    out = template or ""
    for p in params:
        name = getattr(p, "name", None) or (p.get("name") if isinstance(p, dict) else "")
        dt = (getattr(p, "data_type", None) or (p.get("data_type") if isinstance(p, dict) else "") or "VARCHAR").upper()
        dv = getattr(p, "default_value", None) if not isinstance(p, dict) else p.get("default_value")
        numeric = dt in ("INTEGER", "BIGINT", "NUMERIC", "DECIMAL", "DOUBLE", "FLOAT", "REAL")
        if dv is None or dv == "":
            lit = "0" if numeric else "'x'"
        else:
            lit = str(dv) if numeric else "'" + str(dv).replace("'", "''") + "'"
        out = out.replace("{" + str(name) + "}", lit)
    return out


def propose_skill_from_investigation(
    inv_id: str, table_to_entity: Optional[dict[str, str]] = None
) -> Optional[Any]:
    """Crystallize a candidate learned skill from a finished investigation: take its grounded,
    read-only SQL, parameterize the WHERE literals, and shape a learned `OntologyAction`. Returns
    the CANDIDATE (not saved — the UI confirms, then POSTs to save_skill), or None when the run
    has no reusable read-only query."""
    from aughor.ontology.models import OntologyAction
    try:
        from aughor.db.history import get_investigation
        inv = get_investigation(inv_id)
    except Exception as exc:
        logger.debug("propose_skill: load %s failed: %s", inv_id, exc)
        return None
    if not inv:
        return None
    sql = _primary_sql(inv)
    if not sql or not _is_read_only(sql):
        return None
    question = (inv.get("question") or "").strip()
    table = _primary_table(sql)
    t2e = table_to_entity or {}
    entity = t2e.get(table) or t2e.get(table.split(".")[-1]) or (table.split(".")[-1].rstrip("s").title() if table else "")
    templated, params = _parameterize_sql(sql)
    try:
        return OntologyAction(
            id=_skill_id(question, table),
            display_name=(question[:80] or (f"Analysis on {table}" if table else "Saved analysis")),
            description=(_finding_text(inv) or question or "Reusable analysis")[:300],
            entity=entity or "",
            action_type=_infer_action_type(sql),
            sql_template=templated,
            parameters=params,
            business_rules_enforced=[],
            returns=(f"Result of: {question[:120]}" if question else "Query result rows"),
            source_table=table,
            origin="learned",
            usage_count=0,
        )
    except Exception as exc:
        logger.debug("propose_skill: build candidate failed for %s: %s", inv_id, exc)
        return None


def _autonomy_level(connection_id: str) -> int:
    """Earned autonomy 0–3 for a connection. The L0–L3 ladder isn't built yet, so every
    connection is L0 (manual-confirm). Centralized here so auto-promotion turns on the day the
    ladder lands without touching the crystallizer."""
    return 0


def auto_crystallize(inv_id: str, connection_id: str) -> None:
    """Auto-promote a skill-worthy run into a saved learned skill — but ONLY at an earned
    autonomy level (L2+). At L0 (the only level today) this is a deliberate no-op: a strong run
    is left as a candidate for the UI to confirm, never silently persisted (ungoverned auto-save
    is exactly what the manual-confirm gate exists to prevent)."""
    if _autonomy_level(connection_id) < 2:
        return None
    # Reserved for the autonomy ladder: propose → EXPLAIN-gate → save under the active schema.
    return None
