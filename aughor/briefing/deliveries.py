"""A Briefing signed and dated as a delivery (the 2027 study §V, screen 3; decided 2026-10-05,
ROADMAP §6 item 42c).

A send already leaves a departure row and carries the gate's receipt. What neither says is WHICH
Briefing left: the version, kept in the ledger, that the reader was sent. This ties the two — one
ledger entry per send, citing the version it delivered and the departure that carried it — so a
Briefing met later, in a thread or a slide, opens to the version that was sent and not to today's.

Only a send that left is a delivery. A send the gate held, or one the channel refused, is in the
departures ledger with its reason and is not listed here.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from aughor.briefing import versions as _versions

KIND = "briefing_delivery"


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def briefing_key(conn_id: str, briefing: dict, *, scope_key: str) -> str:
    """The key a Briefing's versions are kept under — spelled exactly as the version keeper spells it."""
    period = briefing.get("period") or {}
    return _versions.natural_key(conn_id, scope_key=str(scope_key or ""),
                                 range_key=str(period.get("covers") or period.get("last_day") or ""),
                                 recipe=str(period.get("period") or ""))


def record_delivery(*, conn_id: str, scope_key: str, briefing: dict, to: str, to_kind: str,
                    subscription_id: str = "", subscription_name: str = "", departure_id: str = "",
                    receipt_line: str = "", held_lines: int = 0, now: Optional[str] = None) -> str:
    """Book one delivery of the Briefing as it was sent. Returns the entry's id, or "" when the
    Briefing carries no kept version (the standing Briefing measures nothing to keep) or the
    ledger could not be written — a send is never failed by its own record."""
    kept = briefing.get("version") if isinstance(briefing.get("version"), dict) else {}
    version_id = str(kept.get("artifact_id") or "")
    if not version_id:
        return ""
    period = briefing.get("period") or {}
    sent_at = now or _now()
    key = briefing_key(conn_id, briefing, scope_key=scope_key)
    payload = {"briefing_key": key, "version": kept.get("version"), "version_artifact_id": version_id,
               "covers": str(period.get("covers") or ""), "label": str(period.get("label") or ""),
               "scope_key": str(scope_key or ""), "sent_at": sent_at, "to": to, "to_kind": to_kind,
               "subscription_id": subscription_id, "subscription_name": subscription_name,
               "departure_id": departure_id, "receipt_line": receipt_line, "held_lines": int(held_lines or 0)}
    try:
        return _ledger().artifact_write(
            KIND, f"{KIND}:{key}#{departure_id or sent_at}", payload, conn_id=conn_id,
            lineage=[("delivers", version_id, f"version {kept.get('version')} to {to}")])
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the Briefing left; the record of which version left could not be written",
                 counter="briefing.delivery.record")
        return ""


def _row(art: dict) -> dict:
    return {**dict(art.get("payload") or {}), "id": str(art.get("id") or "")}


def deliveries_of(conn_id: str, briefing: dict, *, scope_key: str, limit: int = 20) -> dict:
    """Every delivery of one Briefing — this scope and range, whichever version left — newest first,
    with the version current now, so a reader sees at once whether what was sent still stands."""
    key = briefing_key(conn_id, briefing, scope_key=scope_key)
    rows = [_row(a) for a in _ledger().artifacts_of_kind(KIND, conn_id=conn_id, limit=500)]
    mine = sorted((r for r in rows if r.get("briefing_key") == key),
                  key=lambda r: str(r.get("sent_at") or ""), reverse=True)[:limit]
    latest = _ledger().artifact_latest(key)
    current = int(latest.get("version") or 0) if latest else None
    for r in mine:
        r["restated_since"] = bool(current and r.get("version") and int(r["version"]) < current)
    return {"deliveries": mine, "current_version": current}


def delivery(delivery_id: str) -> Optional[dict[str, Any]]:
    """One delivery with the Briefing as it was sent — the kept version it cites, read by id, never
    the latest under its key."""
    art = _ledger().artifact_by_id(delivery_id)
    if not art or art.get("kind") != KIND:
        return None
    row = _row(art)
    sent = _ledger().artifact_by_id(str(row.get("version_artifact_id") or ""))
    payload = (sent or {}).get("payload") or {}
    row["connection_id"] = str(art.get("conn_id") or "")
    row["briefing"] = payload.get("briefing") if isinstance(payload.get("briefing"), dict) else None
    row["as_of"] = str(payload.get("as_of") or "")
    latest = _ledger().artifact_latest(str(row.get("briefing_key") or ""))
    row["current_version"] = int(latest.get("version") or 0) if latest else None
    row["restated_since"] = bool(row["current_version"] and row.get("version")
                                 and int(row["version"]) < row["current_version"])
    return row
