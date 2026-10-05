"""Events out — a subscription to the Record's events, delivered as webhooks (the 2027 study §Q
"subscribe to restatements"; phase 7, P7-1).

An outside tool asks once — a URL, the kinds it wants (`kernel/events.SUBSCRIBABLE`), optionally
one connection — and from then on every such event is POSTed to it through the notifications
executor (`notifications/executor.fire_action`), which means the SSRF guard at send time, the
outbound cap, the span and the delivery log every other send gets. A subscription is a kernel
artifact (kind ``ledger_subscription``); withdrawing one restates it inactive, so who subscribed to
what stays on the record. A delivery that failed is a `ledger.delivered` event with its status,
never a silence; the pull door (`GET /ledger/v1/restatements?since=`) is the cursor a tool that
missed one reads back from.

Nothing here decides what counts as an event: the Record's modules call :func:`notify` at the
moment they emit — a restatement in `claims.book`, an outcome in `decisions.book_outcome`, a scored
prediction in `scenario.score_prediction`, a report in `mission.report_now`.

A delivery is information leaving the platform, so every one asks the departure gate
(`govern/departure.py`, HB-2's law: every exit asks) as kind ``ledger_event`` before the send: the
entry's own numbers are its measurement (the payload's values, recorded in this tick), its tier and
warrant its declared definition, the subscriber's host the place the repeat law remembers; the
attention budget is exempt by the gate's own policy (a machine asked, nobody's attention is spent).
A held delivery is not sent and is SAID — the `ledger.delivered` event carries ``held`` and why.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

KIND = "ledger_subscription"


class Subscription(BaseModel):
    url: str
    kinds: list[str] = Field(default_factory=list)
    connection_id: str = ""              # "" = every connection the subscriber may see
    headers: dict[str, str] = Field(default_factory=dict)
    created_by: str = ""
    created_at: str = ""
    active: bool = True
    withdrawn_at: str = ""
    withdrawn_by: str = ""
    note: str = ""
    id: str = ""
    key: str = ""


class SubscriptionRefused(ValueError):
    """The door said no, and why."""


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> str:
    from aughor.util.time import now_iso_z
    return now_iso_z()


def _from(art: dict) -> Subscription:
    s = Subscription.model_validate(dict(art.get("payload") or {}))
    s.id, s.key = str(art.get("id") or ""), str(art.get("natural_key") or "")
    return s


def _book(s: Subscription) -> Subscription:
    data = s.model_dump()
    sid = data.pop("id", "")
    key = data.pop("key", "") or f"subscription:{sid or uuid.uuid4().hex[:12]}"
    aid = _ledger().artifact_write(KIND, key, data, conn_id=s.connection_id or None,
                                   lineage=[("subscribes", k, "") for k in s.kinds])
    art = _ledger().artifact_by_id(aid)
    return _from(art) if art else s


def subscribe(*, url: str, kinds: list[str], by: str, connection_id: str = "", headers: Optional[dict] = None,
              note: str = "") -> Subscription:
    """Create a subscription. Refuses an unknown kind, no kind, or a URL the send-time guard would
    refuse anyway (said now rather than on the first delivery)."""
    from aughor.kernel.events import SUBSCRIBABLE
    from aughor.util.url_guard import is_safe_webhook_url
    wanted = sorted({str(k).strip() for k in (kinds or []) if str(k).strip()})
    unknown = [k for k in wanted if k not in SUBSCRIBABLE]
    if not wanted:
        raise SubscriptionRefused(f"a subscription names at least one kind of {', '.join(SUBSCRIBABLE)}")
    if unknown:
        raise SubscriptionRefused(f"not subscribable: {', '.join(unknown)}; the kinds are {', '.join(SUBSCRIBABLE)}")
    if not is_safe_webhook_url(url or ""):
        raise SubscriptionRefused("the URL is not an allowed public http(s) endpoint (the send-time SSRF guard would refuse it)")
    s = Subscription(url=url, kinds=wanted, connection_id=connection_id or "", headers=dict(headers or {}),
                     created_by=by or "unidentified", created_at=_now(), note=(note or "")[:400])
    booked = _book(s)
    _emit("ledger.subscribed", {"subscription": booked.id, "kinds": wanted, "active": True, "by": by, "url_host": _host(url)})
    return booked


def withdraw(subscription_id: str, *, by: str) -> Subscription:
    s = get(subscription_id)
    if s is None:
        raise SubscriptionRefused(f"no subscription {subscription_id!r}")
    s.active, s.withdrawn_at, s.withdrawn_by = False, _now(), by or "unidentified"
    booked = _book(s)
    _emit("ledger.subscribed", {"subscription": booked.id, "kinds": s.kinds, "active": False, "by": by})
    return booked


def get(subscription_id: str) -> Optional[Subscription]:
    art = _ledger().artifact_by_id(subscription_id)
    if not art or art.get("kind") != KIND:
        return None
    latest = _ledger().artifact_latest(str(art.get("natural_key") or ""))
    return _from(latest or art)


def list_subscriptions(*, active_only: bool = False, limit: int = 500) -> list[Subscription]:
    out = [_from(a) for a in _ledger().artifacts_of_kind(KIND, limit=limit)]
    return [s for s in out if s.active] if active_only else out


def public(s: Subscription) -> dict:
    """The subscription without its headers' values (an auth header is a credential)."""
    d = s.model_dump()
    d["headers"] = {k: "•••" for k in s.headers}
    d["url_host"] = _host(s.url)
    return d


def _host(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return ""


def _emit(kind: str, payload: dict, conn_id: Optional[str] = None) -> None:
    try:
        _ledger().emit(kind, payload, conn_id=conn_id)
    except Exception as exc:  # noqa: BLE001 — the event is the trail, never the act
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"the {kind} event could not be journaled", counter="subscriptions.emit")


# ── delivery ───────────────────────────────────────────────────────────────────────────────

#: The departures ledger's kind for a subscription delivery (`govern/departure.ATTENTION_POLICY` names it).
DEPARTURE_KIND = "ledger_event"
#: Payload keys that are the entry's measured numbers — the measurement law 1 grounds the text in.
_VALUE_KEYS = ("value", "actual", "baseline", "low", "high", "mid")


def _entry_id(payload: dict[str, Any]) -> str:
    return str(payload.get("id") or payload.get("claim_id") or payload.get("outcome_id") or payload.get("report") or "")


def _measurement(kind: str, payload: dict[str, Any], recorded_at: str):
    """The entry's own numbers, recorded in this tick, as the measurement its text departs on."""
    from aughor.govern.departure import Measurement
    values = [float(payload[k]) for k in _VALUE_KEYS
              if isinstance(payload.get(k), (int, float)) and not isinstance(payload.get(k), bool)]
    entry = _entry_id(payload)
    return Measurement(source=f"the Record's {kind} entry" + (f" {entry}" if entry else ""), values=values,
                       measured_at=recorded_at, as_of=str(payload.get("as_of") or ""),
                       definition=_definition(kind, payload),
                       stale_note="a Record entry is restated by its writer, never re-measured at delivery")


def _definition(kind: str, payload: dict[str, Any]) -> str:
    entry = _entry_id(payload)
    tier = str(payload.get("tier") or "")
    return (f"Record entry {entry or kind} ({payload.get('kind') or kind.split('.')[0]}"
            + (f", tier {tier}" if tier else "") + ")")


def _gate_args(kind: str, payload: dict[str, Any], s: Subscription, conn_id: str, now: str) -> dict[str, Any]:
    """What the departure gate is asked with for one delivery (the call itself is in :func:`notify`,
    where the exit ratchet reads it beside the send)."""
    from aughor.org.context import current_org_id
    text = str(payload.get("text") or kind)
    metric = str(payload.get("metric") or "")
    entry = _entry_id(payload)
    predictions = [entry] if entry and (kind == "prediction.scored" or payload.get("kind") == "prediction") else None
    return dict(kind=DEPARTURE_KIND, org_id=current_org_id(), conn_id=conn_id or "", text=text,
                target=_host(s.url), actor=f"subscription:{s.id}", source_kind="subscription", source_id=s.id,
                source_name=f"subscription {s.id} to {kind}", about=f"metric:{metric}" if metric else "",
                measurement=_measurement(kind, payload, now), declared_definition=_definition(kind, payload),
                predictions=predictions)


def notify(kind: str, payload: dict[str, Any], *, conn_id: str = "") -> list[dict]:
    """The Record's modules call this at the moment they emit: every active subscription to
    ``kind`` (and to this connection, when it named one) is judged by the departure gate and, when
    it departs, fired through the notifications executor with the gate's receipt. Best-effort by
    contract; what became of each delivery — ``ok``, ``failed``, ``held`` with why — is a
    `ledger.delivered` event. Returns the deliveries ``[{subscription, status, http_status, why}]``."""
    out: list[dict] = []
    try:
        subs = [s for s in list_subscriptions(active_only=True)
                if kind in s.kinds and (not s.connection_id or not conn_id or s.connection_id == conn_id)]
    except Exception as exc:  # noqa: BLE001 — an unreadable subscription store delivers nothing, and says so
        from aughor.kernel.errors import tolerate
        tolerate(exc, "subscriptions could not be read; nothing delivered", counter="subscriptions.read")
        return out
    if not subs:
        return out
    from aughor.govern.departure import gate_departure
    from aughor.notifications.executor import fire_action
    from aughor.notifications.models import ActionPayload, ActionTrigger
    now = _now()
    for s in subs:
        why, departure = "", ""
        try:
            # HB-2 — the departure gate, asked here beside the send so the exit ratchet reads both.
            verdict = gate_departure(**_gate_args(kind, payload, s, conn_id, now))
            departure = verdict.record_id
            if verdict.held:
                status, http, why = "held", None, verdict.reason_sentence() or verdict.state
            else:
                trigger = ActionTrigger(id=s.id, name=f"subscription {s.id}", type="webhook", url=s.url, headers=dict(s.headers))
                body = ActionPayload(investigation_id=str(payload.get("ref") or payload.get("key") or ""), rec_index=0,
                                     recommendation=str(payload.get("text") or kind), metric_name=str(payload.get("metric") or ""),
                                     headline=kind, trigger_id=s.id, triggered_at=now,
                                     delivery_key=f"{kind}:{_entry_id(payload) or now}",
                                     context={"event": kind, "connection_id": conn_id, **{k: v for k, v in payload.items() if k != "text"},
                                              "receipt": verdict.receipt, "receipt_line": verdict.receipt_line()})
                log = fire_action(trigger, body)
                status, http = getattr(log, "status", "unknown"), getattr(log, "http_status", None)
        except Exception as exc:  # noqa: BLE001 — one subscriber's failure does not stop the rest
            status, http, why = "failed", None, f"{type(exc).__name__}: {str(exc)[:200]}"
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"a subscription's delivery failed ({s.id})", counter="subscriptions.deliver")
        row = {"subscription": s.id, "status": status, "http_status": http, **({"why": why} if why else {})}
        out.append(row)
        _emit("ledger.delivered", {**row, "event": kind, "url_host": _host(s.url), "departure": departure}, conn_id=conn_id or None)
    return out
