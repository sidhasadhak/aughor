"""Manual brief delivery — what remains of the legacy brief scheduler.

The per-subscription APScheduler cron path was DELETED 2026-08-06 (flag endgame
Wave 4): every enabled subscription is delivered through the ONE automation engine
as a virtual automation (`aughor.automations.adopt.subscription_as_automation` — a
`schedule` condition on the subscription's cron plus the existing `brief` effect,
`max_retries=0` because a brief is an OUTWARD send and the legacy job's only retry
was the next cron fire). The heartbeat (`aughor.automations.scheduler`) is the only
loop; `/cron/tick` drives the same tick on serverless. The L4 equivalence receipt
(`65364174a172`) covers the adoption.

Only the synchronous test-endpoint trigger lives here now.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def trigger_now(sub_id: str) -> Optional[dict]:
    """Deliver a brief immediately (synchronous, for the API test endpoint)."""
    try:
        from aughor.briefing.store    import get_subscription
        from aughor.briefing.delivery import deliver_subscription
        from aughor.db.registry     import get_connection_org
        from aughor.org.context     import using_org
        sub = get_subscription(sub_id)
        if not sub:
            return None
        with using_org(get_connection_org(sub.conn_id) or ""):  # DATA-06: bind the sub's tenant
            return deliver_subscription(sub)
    except Exception as exc:
        logger.error("trigger_now failed for brief %s: %s", sub_id, exc)
        return None
