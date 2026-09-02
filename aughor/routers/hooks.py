"""DS-17 · the inbound door — ``POST /hooks/{automation_id}``.

The one route in this repo that a stranger is *meant* to reach. Everything about its
shape follows from that, and each choice below refuses something a plausible version
would have allowed.

**Its own prefix, not ``/automations/{id}/webhook``.** The app-wide key gate exempts by
path PREFIX (`api.py:_AUTH_EXEMPT`, `startswith`), so putting the public door under
`/automations/` would mean either exempting that whole surface — every read, every write,
every delete — or a matcher subtle enough to get wrong later. A top-level prefix makes the
exemption exactly as wide as the thing being exempted. It also reads better in the box
where somebody pastes it: `https://host/hooks/a1671c53`.

**Exempt from the shared key, gated on its own token.** A webhook is called by something
that holds a URL and nothing else — GitHub, Stripe, another team's job. Requiring
`AUGHOR_API_KEY` as well would mean handing a third party a credential that opens the
entire API in order to let it run one chain. The per-automation token is strictly the
narrower grant, which is the trade: this door is open to a stranger, and it opens onto
exactly one chain.

**The token is not the only gate.** A call runs through `trigger_now`, which is the same
entry `Run now` presses, so `enabled`, `paused_until` and `expires_at` all still hold and
every governed write inside the chain still parks for approval. DS-14's line, again: the
caller changes, the governance does not.

**The chain must still declare a Webhook trigger.** Checked here as well as at issue time,
because a route is the real boundary and a trigger can be removed after a token was
minted. Without it a token would be a way to run a scheduled chain on demand — `manual`
bypasses the schedule by design — so the trigger on the canvas is the author's consent to
being called, and this refuses when it is gone.

**One failure sentence for every failure.** Wrong token, no token, unknown id, deleted
automation: all 401, all the same body. Distinguishing them would turn this into an
oracle for which automation ids exist.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hooks"])

#: Every refusal that is about the credential says exactly this, whatever went wrong.
_REFUSED = "unknown or invalid webhook credential"


@router.post("/hooks/{automation_id}")
def call_webhook(automation_id: str, request: Request) -> dict:
    """Run the chain this token belongs to. Returns its run, exactly as Run now does.

    The body is ignored on purpose. A webhook payload is untrusted data from outside the
    deployment, and a chain reads its inputs from governed objects — a metric, a vetted
    query, a connection's rows — never from the request that woke it. Threading a caller's
    JSON into the chain context would open a binding path from the public internet into
    every downstream step's config, which is the request-forgery shape §3.4 refuses for
    `connection_call`'s URL. If a payload is ever wanted it needs its own declared, typed
    port, not a passthrough.
    """
    token = _bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail=_REFUSED)

    from aughor.automations.webhooks import webhook_token_matches
    if not webhook_token_matches(automation_id, token):
        raise HTTPException(status_code=401, detail=_REFUSED)

    from aughor.automations.store import get_automation
    automation = get_automation(automation_id)
    if automation is None:
        # A token outliving its automation. Same sentence as a bad token: from out here
        # "deleted" and "never existed" are the same fact, and only one of them is ours.
        raise HTTPException(status_code=401, detail=_REFUSED)
    if not any(c.kind == "webhook" for c in (automation.conditions or [])):
        raise HTTPException(
            status_code=409,
            detail="This chain no longer has a Webhook trigger, so its URL does nothing. "
                   "Add the trigger back, or revoke the URL.")

    from aughor.automations.scheduler import trigger_now
    run = trigger_now(automation_id, via="webhook")
    if run is None:
        raise HTTPException(status_code=500, detail="the run could not be started")
    logger.info("webhook ran automation %s: %s", automation_id, run.outcome)
    return run.model_dump()


def _bearer(request: Request) -> str:
    """The bearer token, or ``""``. Same header shape `/cron/tick` already asks for, so a
    deployment holds one convention for "a machine is calling with a secret"."""
    raw = request.headers.get("authorization", "")
    if not raw.lower().startswith("bearer "):
        return ""
    return raw[7:].strip()
