"""Arc FA, FA-5 — act on each object a rule admits (ROADMAP §3.60; the user's calls, 2026-10-26).

A rule defines a population and, until this, nothing could act as an object entered it: ``entity_appears`` compares a
table's row count and largest key, so it cannot say WHICH objects arrived, and it cannot see an existing object enter
a rule at all. The ``objects_admitted`` trigger names an entity and a segment on it — a published rule's id, a declared
segment, or a promise's ``overdue_<noun>`` — and on each check lists the segment's KEYS, nothing else, through the
object door's own compiler (`semantic.object_query.compile_object_listing`) on the automation's connection.

Behind ``automations.objects_admitted`` (off; with it off the trigger is not offered, a save naming it is refused at
the door, and a stored one reads nothing and says so). Its laws, each the user's or the house's:

* **The first check records, and fires later** (the user's call 1). When the trigger first runs, or what it reads
  changes — the segment's definition, the entity's key, or the row policy it is listed under — the check records who
  is already in and says so ("25,051 already in, none new") without firing. Only objects that enter afterwards fire
  it. The definition is read from the declaration, never from the compiled SQL: an overdue segment's cutoff moves
  every time its promise is measured, and that is objects entering, not the rule changing.
* **Listed as the person who saved it** (the user's call 2). The listing runs under the row policy of the automation's
  owner — ``Automation.declared_by``, the principal the create doors record (OC-7 / ED-1) — so it can never see
  further than they may; rows that policy withholds are said in the policy's own words. An automation that records no
  one (identity off, or saved before HB-2) is listed as this install's operator, and the check says so.
* **Keys only, and capped.** At most ``MAX_TRACKED`` keys are tracked; above that the check says "too many to track
  (N)" and does not fire. The set is a sidecar of the automations store (`admitted_keys`), keyed per automation and
  target like ``probe_state``.
* **A fired tick hands the chain the keys that entered**, ``{admitted, count, left, said, entity, segment}``. More than
  ``MAX_FAN_OUT`` at once, or keys that read as personal data, and the list is WITHHELD: the count is said and the
  keys are not sent, and a For each over a withheld list is refused with its sentence (`dataflow.fan_items`) — never
  run as empty.
* **Arrivals are committed on a fired tick, departures on the check that sees them.** The probes' rule
  (`probes.py`): a change committed at probe time is swallowed whenever another ``all`` condition was false. So the
  keys handed to the chain join the set only after the tick fired (`commit_admitted`, from the engine), from what this
  check saw — never a second listing, which would swallow an object entering while the steps ran. A key that left is
  dropped at once: dropping can swallow nothing, and an object that comes back is new again.

No model is asked anything; the only warehouse statement is the keys listing (and a count, when there are too many).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from aughor.automations.models import Automation, Condition

logger = logging.getLogger(__name__)

FLAG = "automations.objects_admitted"
KIND = "objects_admitted"

#: The most keys a trigger tracks. Above it a check says how many there are and does not fire: a set this large is a
#: population, not a stream of arrivals a person acts on one by one.
MAX_TRACKED = 100_000

#: The prefix every target of this trigger carries in `probe_state` and `admitted_keys`.
PREFIX = "objects_admitted:"

#: What the keys listing is labelled in the connection's trail — platform plumbing, never shown to a reader.
_PROBE_ID = "__objects_admitted__"

#: The keys a check found newly admitted, held until the engine commits a fired tick: what THIS check saw, so the
#: commit adds exactly what the chain was handed. Process memory on purpose — a lost entry is a commit not made, and
#: the next check finds the same keys new again (at-least-once, never lost).
_STASH: dict[tuple[str, str], list[str]] = {}
_STASH_LOCK = threading.Lock()


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def target_of(cond: Condition, conn_id: str) -> str:
    """The probe-state key of one trigger: per connection, dataset, entity and segment, so moving any of them is a
    new watch — and the store drops the old one's record (`store._prune_admitted`)."""
    schema = str(cond.config.get("schema_name", "") or "")
    return f"{PREFIX}{conn_id}:{schema}:{cond.entity.strip().lower()}.{cond.segment.strip().lower()}"


# ── who the objects are listed for ─────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Owner:
    """The person an automation's listing reads as: the actor the request context is set to, the principal the row
    policy reads, and whether the automation recorded who saved it."""
    actor: str
    principal: str
    recorded: bool

    def words(self) -> str:
        if self.recorded:
            return f"{self.principal}, who saved it"
        return f"{self.principal}, this install's operator — the automation records no one who saved it"


def owner_of(automation: Automation) -> Owner:
    """Who saved the automation (`declared_by`, first writer wins at the store); else this install's operator, which
    is who every request acts for on an install without sign-in — said, never assumed silently."""
    declared = (automation.declared_by or "").strip()
    if declared:
        if declared.startswith("agent:"):
            return Owner(actor=declared, principal=declared, recorded=True)
        actor = declared[len("user:"):] if declared.startswith("user:") else declared
        return Owner(actor=actor, principal=f"user:{actor}", recorded=True)
    from aughor.security.authz import local_operator
    operator = local_operator()
    return Owner(actor=operator, principal=f"user:{operator}", recorded=False)


@contextmanager
def as_owner(owner: Owner) -> Iterator[None]:
    """Read as ``owner`` and no one else: the request's own person, an acting agent and a previewed group are set
    aside, and the statements are the object door's own (ED-1's gate leaves them to the compiler, which applies the
    row policy itself)."""
    from aughor.ontology.security import previewing, reset_acting_agent, set_acting_agent
    from aughor.ontology.security_sql import object_door
    from aughor.org.context import reset_actor, set_actor
    actor = set_actor(owner.actor)
    agent = set_acting_agent("")
    try:
        with previewing(""), object_door():
            yield
    finally:
        reset_acting_agent(agent)
        reset_actor(actor)


# ── what the trigger reads ─────────────────────────────────────────────────────────────────────────────────────────

def _graph_for(conn_id: str, cond: Condition):
    """The served ontology — the graph `GET /ontology` returns, the published release. A read, never a build."""
    from aughor.routers.ontology import served_ontology_graph
    return served_ontology_graph(conn_id, str(cond.config.get("schema_name", "") or "") or None)


def _open_for(conn_id: str, graph, cond: Condition):
    """The connection, scoped to the dataset the served graph was built for — the listing door's own scope."""
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.routers.ontology import resolve_effective_schema
    schema = graph.schema_name or resolve_effective_schema(
        conn_id, str(cond.config.get("schema_name", "") or "") or None)
    return open_connection_for_with_schema(conn_id, schema)


def _edits(conn_id: str) -> list:
    """The connection's accepted property edits — a rule over a property an action sets admits what the edit says."""
    from aughor.actions.overlay import accepted_object_edits
    return accepted_object_edits(conn_id)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def definition_of(graph, anchor, segment: str) -> dict:
    """What the segment says, read from its declaration in the order the compiler resolves it (`_Compiler.segment`):
    a declared segment's filter, then a rule's or a process's derived filters, then a promise's overdue segment —
    whose definition is the promise (`derived.promise_filters`), not the cutoff its measurement moment puts on it."""
    from aughor.ontology.derived import find_derived_segment, overdue_name, promise_filters
    low = (segment or "").strip().lower()
    for key, seg in (anchor.segments or {}).items():
        if low in (key.lower(), (seg.display_name or "").lower()):
            return {"segment": seg.id, "filter_sql": seg.filter_sql or ""}
    derived = find_derived_segment(graph, anchor, segment)
    if derived is not None:
        return {"derived": derived.name, "source": derived.source, "filters": list(derived.filters)}
    for process in (graph.processes or {}).values():
        for i, stage in enumerate(process.stages):
            if stage.promise is not None and overdue_name(stage).lower() == low:
                return {"overdue": process.id, "stage": stage.name, "promise": promise_filters(process, i)}
    return {"segment": segment}


def _keys_sql(page_sql: str, dialect: str, limit: int) -> str:
    """The compiled page as a keys listing: its own FROM, segment, filters and row policy, without its order and page."""
    import sqlglot
    tree = sqlglot.parse_one(page_sql, read=dialect)
    tree.set("order", None)
    tree.set("offset", None)
    return tree.limit(limit).sql(dialect=dialect)


@dataclass
class Observed:
    """One check's reading of the segment."""
    entity: str                       # the entity's api name
    key: str
    keys: set[str] = field(default_factory=set)
    no_key: int = 0                   # objects listed with no key — they cannot be named, so they are not tracked
    too_many: Optional[str] = None    # "130,442" (or "more than 100,000") when over the cap
    cut: Optional[str] = None         # the connection stopped the read short of the cap — said, never tracked
    definition: str = ""
    reader: str = ""
    said: list[str] = field(default_factory=list)

    def listed_under(self, owner: Owner) -> str:
        return json.dumps({"definition": self.definition, "reader": self.reader, "key": self.key,
                           "owner": owner.principal}, sort_keys=True)


def _unavailable(message: str):
    from aughor.automations.engine import ProbeUnavailable
    return ProbeUnavailable(message)


def observe(cond: Condition, automation: Automation, owner: Owner) -> Observed:
    """List the segment's keys as ``owner`` — or raise `ProbeUnavailable` saying why the segment cannot be read."""
    from aughor.ontology.platform_objects import is_platform
    from aughor.ontology.security import row_condition
    from aughor.semantic.completeness import cut, policy_words
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_listing, find_object_type

    label = f"objects_admitted({cond.entity}.{cond.segment})"
    graph = _graph_for(automation.conn_id, cond)
    if graph is None or not graph.entities:
        raise _unavailable(f"{label}: no ontology is built for this connection — there is no segment to list")
    with as_owner(owner):
        try:
            anchor = find_object_type(graph, cond.entity)
        except ObjectQueryRefused as exc:
            raise _unavailable(f"{label}: {exc.reason}") from exc
        if is_platform(anchor):
            raise _unavailable(f"{label}: {anchor.id} is held by the platform, not read from a warehouse — this "
                               "trigger lists warehouse objects")
        b = anchor.backing
        key = (b.primary_key if b is not None else "") or anchor.identity_key
        if not key:
            raise _unavailable(f"{label}: {anchor.id} declares no key — the trigger names each object by its key")
        db = _open_for(automation.conn_id, graph, cond)
        try:
            dialect = (getattr(db, "dialect", "") or "duckdb").lower()
            try:
                compiled = compile_object_listing(
                    {"entity": cond.entity, "segment": cond.segment, "columns": [key], "limit": 1}, graph,
                    dialect=dialect, overlay=_edits(automation.conn_id))
            except ObjectQueryRefused as exc:
                raise _unavailable(f"{label}: {exc.reason}") from exc
            seen = Observed(entity=anchor.api_name, key=key,
                            definition=_hash(definition_of(graph, anchor, cond.segment)),
                            reader=_hash([owner.principal, row_condition(anchor, "t0") or ""]),
                            said=policy_words(graph, compiled.withheld))
            sql = _keys_sql(compiled.sql, dialect, MAX_TRACKED + 1)
            result = db.execute_bounded(_PROBE_ID, sql, MAX_TRACKED + 1, internal=True)
            if result is None or result.error:
                raise _unavailable(f"{label}: the keys could not be listed — "
                                   f"{getattr(result, 'error', '') or 'no result'}"[:400])
            rows = list(result.rows or [])
            if len(rows) > MAX_TRACKED:
                counted = db.execute_bounded(_PROBE_ID, compiled.count_sql, 2)
                n = (counted.rows or [[None]])[0][0] if counted is not None and not counted.error else None
                seen.too_many = f"{int(n):,}" if n not in (None, "", "NULL") else f"more than {MAX_TRACKED:,}"
                return seen
            if cut(result):
                seen.cut = (f"the connection returned {len(rows):,} of {int(result.row_count):,} keys — a set it "
                            "cuts short cannot be tracked")
                return seen
            for row in rows:
                value = row[0] if row else None
                if value is None or str(value) in ("", "NULL"):
                    seen.no_key += 1
                else:
                    seen.keys.add(str(value))
            return seen
        finally:
            try:
                db.close()
            except Exception as exc:  # noqa: BLE001 — the reading is taken; closing is best-effort
                from aughor.kernel.errors import tolerate
                tolerate(exc, "closing the keys listing's db handle is best-effort; the keys are read",
                         counter="automations.admitted.db_close")


# ── the check ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _ordered(keys) -> list[str]:
    """Keys in their natural order — numbers as numbers — so a list reads the way a person counts."""
    keys = list(keys)
    if all(k.lstrip("-").isdigit() for k in keys):
        return sorted(keys, key=int)
    return sorted(keys)


def _changed(before: Optional[str], under: str) -> Optional[str]:
    """Why the record must be taken again, or None when what the keys are listed under is what was recorded."""
    if before is None:
        return "first check"
    if before == under:
        return None
    try:
        was, now = json.loads(before), json.loads(under)
    except (TypeError, ValueError):
        return "its record could not be read"
    if was.get("definition") != now.get("definition"):
        return "its segment's definition changed"
    if was.get("key") != now.get("key"):
        return "its entity's key changed"
    return "who it is listed for changed — the row policy or the person it reads as"


def _stash(automation_id: str, target: str, keys: Optional[list[str]]) -> None:
    with _STASH_LOCK:
        if keys:
            _STASH[(automation_id, target)] = keys
        else:
            _STASH.pop((automation_id, target), None)


def evaluate_admitted_condition(cond: Condition, automation: Automation) -> tuple[bool, str, dict]:
    """(fired, detail, payload) — fires once for the objects the segment admits that the last record did not hold."""
    from aughor.automations.dataflow import MAX_FAN_OUT, withheld_list
    from aughor.automations.store import drop_admitted, get_admitted_keys, get_probe_baseline, record_admitted

    label = f"objects_admitted({cond.entity}.{cond.segment})"
    if not enabled():
        return False, f"{label}: off on this deployment ({FLAG}) — nothing was read", {}
    owner = owner_of(automation)
    target = target_of(cond, automation.conn_id)
    seen = observe(cond, automation, owner)
    listed = f"listed as {owner.words()}" + (f"; {'; '.join(seen.said)}" if seen.said else "")
    if seen.too_many is not None:
        _stash(automation.id, target, None)
        return False, (f"{label}: too many to track ({seen.too_many}) — at most {MAX_TRACKED:,} objects are tracked, "
                       f"so nothing fired · {listed}"), {}
    if seen.cut is not None:
        _stash(automation.id, target, None)
        return False, f"{label}: {seen.cut}, so nothing fired · {listed}", {}
    n = len(seen.keys)
    unnamed = f"; {seen.no_key:,} without a key, not tracked" if seen.no_key else ""
    under = seen.listed_under(owner)
    why = _changed(get_probe_baseline(automation.id, target), under)
    if why is not None:
        # The user's call 1: who is already in is recorded and said — none of them is new.
        record_admitted(automation.id, target, _ordered(seen.keys), under)
        _stash(automation.id, target, None)
        return False, (f"{label}: {why} — {n:,} already in, none new; recorded, not fired{unnamed} · {listed}"), {}

    known = get_admitted_keys(automation.id, target)
    new = _ordered(seen.keys - known)
    left = known - seen.keys
    drop_admitted(automation.id, target, _ordered(left))
    gone = f", {len(left):,} left" if left else ""
    if not new:
        _stash(automation.id, target, None)
        return False, f"{label}: none new ({n:,} in{gone}{unnamed}) · {listed}", {}

    _stash(automation.id, target, new)
    noun = f"{seen.entity} object{'' if len(new) == 1 else 's'}"
    said = f"{len(new):,} {noun} entered {cond.segment}" + (f" ({'; '.join(seen.said)})" if seen.said else "")
    if len(new) > MAX_FAN_OUT:
        admitted: Any = withheld_list(len(new), (
            f"{len(new):,} {noun} entered {cond.segment} — more than the {MAX_FAN_OUT} a step runs once per, so "
            "their keys are withheld and only the count is sent"))
    elif _reads_as_personal(seen.key, new):
        admitted = withheld_list(len(new), (
            f"{len(new):,} {noun} entered {cond.segment} — their keys read as personal data, so they are withheld "
            "and only the count is sent"))
    else:
        admitted = new
    payload = {"entity": seen.entity, "segment": cond.segment, "admitted": admitted, "count": len(new),
               "left": len(left), "said": said}
    return True, f"{label}: {len(new):,} newly admitted ({n:,} in{gone}{unnamed}) · {listed}", payload


def _reads_as_personal(key: str, keys: list[str]) -> bool:
    """Whether the keys a chain would be handed read as personal data. The listing is read as the platform's own (it
    never leaves the process), so what does leave passes the scanner the connection's door runs on every answer."""
    from aughor.security.pii import PiiScanner
    return PiiScanner.has_pii([key], [[k] for k in keys])


def commit_admitted(automation: Automation) -> None:
    """After a FIRED tick: add the keys each `objects_admitted` check handed the chain to what it has seen. Called by
    the engine only after a fired tick, never in a preview or on a resume (the tick that parked committed them).
    Best-effort per trigger: a failed commit means the same keys fire again next check, never that they are lost."""
    conds = [c for c in automation.conditions if c.kind == KIND]
    if not conds:
        return
    from aughor.automations.store import add_admitted
    for cond in conds:
        target = target_of(cond, automation.conn_id)
        with _STASH_LOCK:
            keys = _STASH.pop((automation.id, target), None)
        if not keys:
            continue
        try:
            add_admitted(automation.id, target, keys)
        except Exception as exc:  # noqa: BLE001 — at-least-once: the keys fire again rather than vanish
            from aughor.kernel.errors import tolerate
            tolerate(exc, "objects_admitted commit is best-effort; uncommitted keys fire again next check",
                     counter="automations.admitted.commit")


# ── the doors' questions ───────────────────────────────────────────────────────────────────────────────────────────

def listing_problem(conn_id: str, cond: Condition) -> str:
    """Why the save door refuses this trigger, or "" — it compiles the keys listing once, runs nothing. Read as the
    person saving, so a segment they cannot read is refused in the compiler's words."""
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_listing, find_object_type
    graph = _graph_for(conn_id, cond)
    if graph is None or not graph.entities:
        return f"no ontology is built for connection '{conn_id}' — there is no segment to watch"
    try:
        anchor = find_object_type(graph, cond.entity)
        b = anchor.backing
        key = (b.primary_key if b is not None else "") or anchor.identity_key
        compile_object_listing({"entity": cond.entity, "segment": cond.segment, "columns": [key] if key else [],
                                "limit": 1}, graph)
    except ObjectQueryRefused as exc:
        return exc.reason
    return ""


def watchable_segments(conn_id: Optional[str]) -> int:
    """How many segments this connection's cached graph holds that the trigger could watch — the palette's
    prerequisite. A read of the cache, never a build."""
    from aughor.ontology.derived import derived_for, find_overdue_segment, overdue_derivations
    from aughor.ontology.store import load_latest_ontology
    graph = load_latest_ontology(conn_id, None) if conn_id else None
    if graph is None:
        return 0
    n = 0
    for entity in graph.entities.values():
        n += sum(1 for s in (entity.segments or {}).values() if s.verified)
        n += sum(1 for d in derived_for(graph, entity).segments if d.usable)
    for process in (graph.processes or {}).values():
        for d in overdue_derivations(process):
            entity = graph.entities.get(d.entity)
            if d.usable and entity is not None and find_overdue_segment(graph, entity, d.name) is not None:
                n += 1
    return n
