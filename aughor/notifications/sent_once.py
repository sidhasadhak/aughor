"""Track C3 — a keyed send leaves once, however often it is retried (2026-11-06).

Senders already carried a ``delivery_key`` stable across every attempt of one delivery (4.1a): a
monitor or agent alert, a Briefing give, a mission report, a review question, an inbox accept.
Until this module only the RECEIVER could honour it — the key rode in the body, and Slack's
incoming webhooks, its chat.postMessage and Jira's create-issue ignore a body field. Each path had
built its own partial guard instead: the inbox resolves a proposal once before it sends, the engine
claims a period before it sends (a set `slack_post` was missing from), the action outbox leases
each call, and the departure gate holds the same words sent to one place within seven days — which a
reworded retry escapes, and from which alerts and briefings are exempt. Here the SENDER honours the
key, in the two transports every message leaves through (`fire_action`, `post_as_bot` — the
population the departure gate's exit ratchet discovers), so one rule covers every path.

The claim is written BEFORE the send and settled after it:

* **delivered** — a later send under the key is not made; it is answered with the first one's
  result, the replay a create endpoint gives under ``Idempotency-Key`` (`util/idempotency.py`).
* **claimed, never settled** — the worker stopped mid-send (killed, OOM, a deploy) and the
  message may have arrived: never sent blind, and said in the words a timeout uses.
* **uncertain** — the send reached the server and no answer came back: the same.
* **not delivered** — nothing arrived (refused, or blocked before it left): the claim is
  released, and a retry sends.

A send with no key is unchanged, and only a person's may have none: `KEYLESS_BY_DESIGN` names each
such call site with its reason, and `tests/unit/test_sent_once.py` holds every other one to
carrying a key. Declared actions keep their own claim — the outbox (`actions/outbox.py`) leases
each call, marks one whose worker stopped `unknown`, and checks before it sends again.

The record is the kernel ledger's kv, wherever the ledger lives, so two API processes on one shared
Postgres race for one claim and exactly one wins (`Ledger.kv_put_if_absent`). A ledger that cannot
be written sends anyway and says so — `automations.engine.claim_delivery`'s choice: a rare
duplicate is worth less than a message that never arrives.
"""
from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import Optional

STORE = "sent_once"
#: Claims kept. A retry comes within hours and a resume within days; past this the oldest go.
CAP = 50_000

CLAIMED, DELIVERED, UNCERTAIN, NOT_DELIVERED = "claimed", "delivered", "uncertain", "not_delivered"

#: The one sentence for "we do not know whether it arrived" (`automations.engine.UNCERTAIN_DELIVERY`).
MAY_HAVE_ARRIVED = "it may already have been delivered, so it was not retried"

#: Transport call sites that send with no delivery key, each with its reason. The ratchet reads it
#: both ways: every site named must still send, and a site not named must pass a key.
KEYLESS_BY_DESIGN: dict[str, str] = {
    "aughor/routers/actions.py::test_action_trigger":
        "a person pressed Test — every press is meant to send",
    "aughor/routers/actions.py::execute_recommendation_action":
        "a person pressed Execute on a recommendation — pressing it again is a second send they chose",
    "aughor/routers/actions.py::send_finding_to_trigger":
        "a person sent a finding to a destination — sending it again is a second send they chose",
    "aughor/actions/executor.py::_dispatch_destination":
        "a declared action's call: the outbox (actions/outbox.py) is its claim — leased before the "
        "call, unknown when its worker stops, checked before anything is sent again",
}


def _slot(scope: str, key: str) -> str:
    return f"{scope}|{key}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def claim(scope: str, key: str) -> Optional[dict]:
    """``None`` when this send may go: the key is now claimed for it, or it has none. Otherwise the
    claim already there (``{"state", "at", "result"}``), which says why it may not."""
    if not key:
        return None
    slot = _slot(scope, key)
    mine = {"state": CLAIMED, "at": _now(), "by": f"{socket.gethostname()}:{os.getpid()}"}
    try:
        ledger = _ledger()
        for _ in range(2):      # a claim released between our insert and our read: once more
            if ledger.kv_put_if_absent(STORE, slot, mine, max_entries=CAP):
                return None
            prior = ledger.kv_get(STORE, slot)
            if prior:
                return prior
        return {"state": CLAIMED, "at": mine["at"]}
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "sent-once claim unwritable — sending anyway, so a retry of this send could "
                      "duplicate it", counter="sent_once.claim_failed")
        return None


def settle(scope: str, key: str, state: str, result: Optional[dict] = None) -> None:
    """How the claimed send ended. ``not_delivered`` releases the claim: nothing arrived, so a
    retry may send. A settle that cannot be written leaves the claim, and a retry is then held as
    maybe-delivered — the safe side of not knowing."""
    if not key:
        return
    slot = _slot(scope, key)
    try:
        if state == NOT_DELIVERED:
            _ledger().kv_delete(STORE, slot)
        else:
            _ledger().kv_put(STORE, slot, {"state": state, "at": _now(), "result": result or {}},
                             max_entries=CAP)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "sent-once settle unwritable — the claim stays, so a retry is held as "
                      "maybe delivered", counter="sent_once.settle_failed")


def stopped(error: object) -> bool:
    """Whether a send's error is this module's sentence — a send that did not go because its key
    already had — rather than the transport's own (a caller prints it instead of "timed out")."""
    return isinstance(error, str) and error.startswith("not sent")


def why_not_sent(prior: dict) -> str:
    """The sentence a send that did not go carries, from the claim that stopped it."""
    when = str(prior.get("at") or "")[:16].replace("T", " ")
    state = prior.get("state")
    if state == DELIVERED:
        return f"not sent again — delivered at {when} under the same delivery key"
    if state == UNCERTAIN:
        return (f"not sent — an attempt under the same delivery key at {when} got no answer: "
                f"{MAY_HAVE_ARRIVED}")
    return (f"not sent — an attempt under the same delivery key began at {when} and has not "
            f"reported back: {MAY_HAVE_ARRIVED}")
