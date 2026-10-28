"""Versions for automations and monitors, and a run that names the one it ran under (Arc TC, TC-3).

**The premise, measured 2026-10-26 before this was written.** A save replaced the definition in
place — ``upsert_automation`` and ``upsert_monitor`` are both "full replace by id" — so the platform
could not say what an automation was last Tuesday. A run named the conditions that fired, not the
definition it ran under nor what started it. Three things the arc's prose assumed were already
true, or were not:

* The engine HAS a dry-run seam (B2, ``run_automation(dry_run=True)``): it dispatches nothing,
  writes nothing, emits no span and commits no baseline. A replay is that seam handed the run's own
  version and its kept trigger — it needed one argument, not a second walker.
* A monitor has no runs of its own. Since the flag endgame every monitor runs through the engine as
  a virtual automation (``monitor:<id>``, ``adopt.monitor_as_automation``), so a monitor's run IS an
  automation run, and it names the MONITOR's version.
* A webhook's request body is ignored on purpose (``routers/hooks.py``: untrusted data never
  reaches the chain). So "the trigger payload as received" is what the chain received — the tick,
  who asked, each condition's verdict and the payload a trigger handed the chain — never the body.

**No new store.** A version is a kernel artifact (``Ledger.artifact_write``): the next version for
a natural key, the one before stamped ``superseded_by`` — supersede, never delete — with lineage
and a tenant. A Briefing and a dashboard keep their versions the same way. A run's stamp is a
sidecar row beside the run in the automations store (``automation_run_stamps``), so the run row and
its model stay exactly what they were before versions began.

**A version is a change of the definition**, not an act of saving: saving the same chain twice
keeps one version. The definition is what was authored — its conditions, steps, logic, retries,
clock and the agent it runs as. Lifecycle state (on or off, muted, its expiry, probation, the MCP
switch, its run summary) is not part of it: pausing an automation is not a new version of it.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: How much of a trigger's payload a run keeps. Larger is kept as its size and its keys, and the
#: replay refuses it by that name — a replay on a partial payload would answer a question nobody
#: asked. 16 KB is far above what a payload-bearing trigger hands a chain today (a promise's
#: breach rate and a finding's id are a few hundred bytes).
TRIGGER_CAP_BYTES = 16_384

AUTOMATION_KIND = "automation_version"
MONITOR_KIND = "monitor_version"

#: How a version came to be kept — said on every version, so none reads as a save it was not.
SAVED = "saved"
BEFORE_VERSIONS = "in place when versions began"
KEPT_AT_RUN = "kept when it ran"

#: The id prefixes of virtual automations (``adopt.py``), read here without importing it.
_MONITOR_PREFIX = "monitor:"
_UNVERSIONED = {"brief:": "a Briefing's delivery", "agent_alert:": "an agent alert rule's check"}

#: Lifecycle, not definition. Changing one of these is not a new version.
AUTOMATION_LIFECYCLE = frozenset({
    "id", "enabled", "paused_until", "expires_at", "probation", "exposed_as_tool",
    "declared_by", "workspace_id", "created_at", "updated_at", "last_run_at", "last_status",
})
MONITOR_LIFECYCLE = frozenset({"id", "enabled", "created_at", "updated_at"})


class VersionNotKept(RuntimeError):
    """A save refused because its version could not be kept. The store never holds a definition
    whose version was not kept."""


class NotReplayable(Exception):
    """A replay refused, by name: what was not kept, and why."""


# ── definitions ──────────────────────────────────────────────────────────────────

def automation_definition(automation: Any) -> dict:
    return {k: v for k, v in automation.model_dump(mode="json").items()
            if k not in AUTOMATION_LIFECYCLE}


def monitor_definition(monitor: Any) -> dict:
    return {k: v for k, v in monitor.model_dump(mode="json").items()
            if k not in MONITOR_LIFECYCLE}


def _canonical(definition: dict) -> str:
    return json.dumps(definition or {}, sort_keys=True, default=str)


def automation_key(automation_id: str) -> str:
    return f"{AUTOMATION_KIND}:{automation_id}"


def monitor_key(monitor_id: str) -> str:
    return f"{MONITOR_KIND}:{monitor_id}"


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _actor() -> str:
    from aughor.org.context import current_actor
    who = (current_actor() or "").strip()
    return f"user:{who}" if who else ""


def asked_by() -> str:
    """Who asked for the run in flight — the person (or agent, or service principal) the request acts for, as a
    principal; "" outside a request: a tick, a schedule. Kept on a run's start record (``trigger.by``)."""
    from aughor.org.context import current_actor
    who = (current_actor() or "").strip()
    if not who:
        return ""
    return who if who.startswith(("user:", "agent:", "service:")) else f"user:{who}"


def _keep(kind: str, key: str, definition: dict, *, conn_id: str, saved_by: str,
          source: str, saved_at: str) -> dict:
    """Keep ``definition`` as the next version of ``key`` unless it already is the latest.
    Returns ``{"version", "version_id", "kept"}`` — ``kept`` False when nothing was written."""
    led = _ledger()
    latest = led.artifact_latest(key)
    if latest is not None:
        held = (latest.get("payload") or {}).get("definition") or {}
        if _canonical(held) == _canonical(definition):
            return {"version": int(latest.get("version") or 0),
                    "version_id": str(latest.get("id") or ""), "kept": False}
    payload = {"definition": definition, "saved_by": saved_by, "saved_at": saved_at,
               "source": source}
    art_id = led.artifact_write(
        kind, key, payload, conn_id=conn_id or None,
        lineage=[("supersedes", str(latest["id"]), source)] if latest is not None else None)
    return {"version": int(latest.get("version") or 0) + 1 if latest is not None else 1,
            "version_id": art_id, "kept": True}


def _keep_on_save(kind: str, key: str, *, prior_definition: Optional[dict], prior_saved_at: str,
                  definition: dict, conn_id: str, saved_at: str) -> None:
    """The save hook both stores share. The definition being replaced is kept first when nothing
    kept it yet — "every save keeps the earlier definition" holds for a chain saved before
    versions began too — and then the new one. Any failure refuses the save."""
    try:
        if prior_definition is not None and _ledger().artifact_latest(key) is None \
                and _canonical(prior_definition) != _canonical(definition):
            _keep(kind, key, prior_definition, conn_id=conn_id, saved_by="",
                  source=BEFORE_VERSIONS, saved_at=prior_saved_at)
        _keep(kind, key, definition, conn_id=conn_id, saved_by=_actor(), source=SAVED,
              saved_at=saved_at)
    except Exception as exc:  # noqa: BLE001 — every failure is the same refusal, said
        raise VersionNotKept(
            f"the save was refused: its version could not be kept ({type(exc).__name__}: {exc})"
        ) from exc


def keep_automation_version(automation: Any) -> None:
    """Called by ``upsert_automation`` before it replaces the row."""
    from aughor.automations.store import get_automation
    prior = get_automation(automation.id)
    _keep_on_save(AUTOMATION_KIND, automation_key(automation.id),
                  prior_definition=automation_definition(prior) if prior is not None else None,
                  prior_saved_at=(prior.updated_at or "") if prior is not None else "",
                  definition=automation_definition(automation), conn_id=automation.conn_id,
                  saved_at=automation.updated_at or "")


def keep_monitor_version(monitor: Any) -> None:
    """Called by ``upsert_monitor`` before it replaces the row."""
    from aughor.monitors.store import get_monitor
    prior = get_monitor(monitor.id)
    _keep_on_save(MONITOR_KIND, monitor_key(monitor.id),
                  prior_definition=monitor_definition(prior) if prior is not None else None,
                  prior_saved_at=(prior.updated_at or "") if prior is not None else "",
                  definition=monitor_definition(monitor), conn_id=monitor.conn_id,
                  saved_at=monitor.updated_at or "")


# ── a run names its version ──────────────────────────────────────────────────────

def version_for_run(automation: Any) -> dict:
    """The version this run runs under — ``{"version", "version_id", "why_not"}``.

    A definition no save kept (saved before versions were kept) is kept now, said as such. Never
    raises: a run is an event that happened, and one whose version could not be kept says why
    on its stamp rather than not running.
    """
    from aughor.util.time import now_iso_z
    try:
        aid = str(automation.id or "")
        if aid.startswith(_MONITOR_PREFIX):
            from aughor.monitors.store import get_monitor
            monitor = get_monitor(aid[len(_MONITOR_PREFIX):])
            if monitor is None:
                return {"version": None, "version_id": "",
                        "why_not": "its monitor is gone, so its definition could not be read"}
            kept = _keep(MONITOR_KIND, monitor_key(monitor.id), monitor_definition(monitor),
                         conn_id=monitor.conn_id, saved_by="", source=KEPT_AT_RUN,
                         saved_at=now_iso_z())
        elif (what := next((w for p, w in _UNVERSIONED.items() if aid.startswith(p)), "")):
            # Read as an automation, defined in a store of its own that this wave does not version.
            return {"version": None, "version_id": "",
                    "why_not": f"versions are kept for automations and monitors; this run is {what}"}
        else:
            kept = _keep(AUTOMATION_KIND, automation_key(aid), automation_definition(automation),
                         conn_id=automation.conn_id, saved_by="", source=KEPT_AT_RUN,
                         saved_at=now_iso_z())
        return {"version": kept["version"], "version_id": kept["version_id"], "why_not": ""}
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a run's version could not be kept; the run goes ahead and its stamp says why",
                 counter="automations.versions.run_version")
        return {"version": None, "version_id": "",
                "why_not": f"its version could not be kept ({type(exc).__name__}: {exc})"[:300]}


def keep_run(run: Any, kept: dict) -> None:
    """Write the run's stamp: its version and its trigger, the payload capped and the cap said.
    Never raises — the run already happened, and a missing stamp reads as "not kept"."""
    try:
        from aughor.automations.store import put_run_stamp
        trigger = dict(kept.get("trigger") or {})
        data = trigger.get("data") or {}
        raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        capped = len(raw) > TRIGGER_CAP_BYTES
        if capped:
            trigger["data"] = {}
            trigger["data_keys"] = sorted(str(k) for k in data)[:50]
        version = kept.get("version") or {}
        put_run_stamp(run_id=run.id, automation_id=run.automation_id, conn_id=run.conn_id,
                      version=version.get("version"), version_id=version.get("version_id", ""),
                      why_not=version.get("why_not", ""), trigger=trigger,
                      trigger_bytes=len(raw), trigger_capped=capped)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a run's stamp could not be kept; the run row stands without it",
                 counter="automations.versions.run_stamp")


# ── reading ──────────────────────────────────────────────────────────────────────

def _rows(key: str, limit: int) -> list[dict]:
    from aughor.security.authz import tenant_scope
    rows = _ledger().artifact_versions(key, limit=limit)
    # The organisation first, as a Briefing's history reads: a key is read by its text alone.
    org = tenant_scope()
    return rows if org is None else [r for r in rows if not r.get("org_id") or r.get("org_id") == org]


def _version_view(row: dict) -> dict:
    payload = row.get("payload") or {}
    return {"version": int(row.get("version") or 0), "version_id": str(row.get("id") or ""),
            "saved_by": str(payload.get("saved_by") or ""),
            "saved_at": str(payload.get("saved_at") or row.get("created_at") or ""),
            "source": str(payload.get("source") or ""),
            "superseded_by": row.get("superseded_by") or "",
            "definition": payload.get("definition") or {}}


def history(kind: str, entity_id: str, current: Optional[dict], *, limit: int = 50) -> dict:
    """Every kept version of one automation or monitor, newest first, and whether the current
    definition is one of them — a definition saved before versions were kept is said, not hidden."""
    key = automation_key(entity_id) if kind == AUTOMATION_KIND else monitor_key(entity_id)
    versions = [_version_view(r) for r in _rows(key, max(1, min(int(limit), 500)))]
    current_version: Optional[int] = None
    if current is not None:
        want = _canonical(current)
        current_version = next((v["version"] for v in versions
                                if _canonical(v["definition"]) == want), None)
    if current is None:
        why = "it was deleted; its versions are kept"
    elif current_version is None:
        why = ("its current definition was saved before versions were kept; it is kept as a "
               "version at its next save or run")
    else:
        why = ""
    return {"versions": versions, "current_version": current_version,
            "current_kept": current_version is not None, "why_not": why}


def stamp_view(run: Any) -> dict:
    """What one run kept, for the run's own route: its version and its trigger — when it started, what asked
    (``via``: the tick, a person's Run now, a webhook, a parent chain) and, for a person's Run now, who (``by``)."""
    from aughor.automations.store import get_run_stamp
    stamp = get_run_stamp(run.id)
    base = {"run_id": run.id, "automation_id": run.automation_id,
            "cap_bytes": TRIGGER_CAP_BYTES}
    if stamp is None:
        return {**base, "kept": False, "version": None, "version_id": "",
                "why_not": "this run kept no version and no trigger: it ran before versions were kept",
                "trigger": None, "trigger_bytes": 0, "trigger_capped": False,
                "replayable": False}
    try:
        _replay_inputs(run, stamp)
        replayable, refused = True, ""
    except NotReplayable as exc:
        replayable, refused = False, str(exc)
    return {**base, "kept": True, "version": stamp.get("version"),
            "version_id": stamp.get("version_id") or "", "why_not": stamp.get("why_not") or "",
            "trigger": stamp.get("trigger") or {}, "trigger_bytes": stamp.get("trigger_bytes") or 0,
            "trigger_capped": bool(stamp.get("trigger_capped")),
            "replayable": replayable, "not_replayable_because": refused}


# ── replay ───────────────────────────────────────────────────────────────────────

def _replay_inputs(run: Any, stamp: Optional[dict]) -> tuple[dict, dict]:
    """``(version row, kept trigger)``, or :class:`NotReplayable` naming what was not kept."""
    if stamp is None:
        raise NotReplayable("this run kept no version and no trigger: it ran before versions were kept")
    if stamp.get("version") is None:
        raise NotReplayable(f"this run's version was not kept: {stamp.get('why_not') or 'no reason was recorded'}")
    row = _ledger().artifact_by_id(str(stamp.get("version_id") or ""))
    if row is None:
        raise NotReplayable(f"version {stamp.get('version')} is no longer in the record")
    if stamp.get("trigger_capped"):
        raise NotReplayable(
            f"this run's trigger payload was not kept whole: it was {int(stamp.get('trigger_bytes') or 0):,} "
            f"bytes, over the {TRIGGER_CAP_BYTES:,} kept")
    trigger = stamp.get("trigger") or {}
    if trigger.get("gated"):
        raise NotReplayable(f"this run was stopped before its trigger was read ({trigger['gated']}), "
                            "so no trigger payload was kept")
    if trigger.get("error") or "conditions" not in trigger:
        why = f" ({trigger['error']})" if trigger.get("error") else ""
        raise NotReplayable(f"this run's conditions could not be read{why}, so no trigger payload was kept")
    return row, trigger


def _as_automation(automation_id: str, row: dict) -> Any:
    from aughor.automations.models import Automation
    definition = dict((row.get("payload") or {}).get("definition") or {})
    try:
        if row.get("kind") == MONITOR_KIND:
            from aughor.automations.adopt import monitor_as_automation
            from aughor.monitors.models import Monitor
            return monitor_as_automation(Monitor(**{**definition, "id": automation_id[len(_MONITOR_PREFIX):]}))
        return Automation(**{**definition, "id": automation_id})
    except Exception as exc:  # noqa: BLE001
        raise NotReplayable(f"version {row.get('version')} no longer reads as a definition: {exc}") from exc


def replay(run: Any) -> tuple[Any, Any, int]:
    """Walk a past run again as a dry run: its own version, against its kept trigger.

    Every side effect is skipped by the engine's dry-run seam — nothing is sent, no action runs,
    no model is called, nothing is written. The conditions are not probed again: the world they
    read has moved on, so the run's kept verdicts are re-read under the version's own logic, and
    the payload the trigger handed the chain is handed to it again. Returns ``(the automation as
    that version, the dry run, the version number)``.
    """
    from aughor.automations.engine import run_automation
    from aughor.automations.store import get_run_stamp
    row, trigger = _replay_inputs(run, get_run_stamp(run.id))
    automation = _as_automation(run.automation_id, row)
    dry = run_automation(automation, dry_run=True, replay=trigger)
    return automation, dry, int(row.get("version") or 0)
