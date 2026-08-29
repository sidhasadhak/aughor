"""VA-9a — one seam for every call that leaves the platform.

Measured before building (2026-08-29): `slackbots/post.py`, `slackbots/verify.py` and
`notifications/executor.py` emitted **no span and consulted no cap**. Outbound calls were
invisible in the waterfall and unbudgeted — and VA-9's own risk note calls third-party
servers "the largest new attack surface in the arc". Adding an MCP consumer on top of a
plane that cannot see or budget what leaves would scale the blindness, not the capability,
which is why this slice comes before that one.

Three things happen here, in this order, and the order is the design:

1. **The cap is checked BEFORE the work.** A budget consulted afterwards is an accountant,
   not a guard. A cap whose action is ``block`` raises :class:`OutboundBlocked`; a cap set
   to ``alert`` records and proceeds, which is what ``alert`` means everywhere else.
2. **A span wraps the work**, so an external call appears in the same waterfall as the run
   that caused it (VA-5). Best-effort: a telemetry sink failing must never fail a send.
3. **The call is recorded as an ``EXTERNAL_CALL`` session event**, which is what makes it
   *countable*. A span alone would leave `observed_usage` blind — it reads session events,
   not spans, and that gap is exactly why deliverable 5 read as "instrumented" while
   nothing could be metered.

The seam RAISES on a block rather than returning a status, because its callers
(`post_as_bot`, `auth_test`, `fire_action`) each promise never to raise and each already
have an honest failure shape to return. Making them catch one named exception keeps that
promise visible at the call site instead of hiding a refusal inside a tuple.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Generator, Optional

logger = logging.getLogger(__name__)


class OutboundBlocked(RuntimeError):
    """A usage cap with action ``block`` refused this call before it was made."""

    def __init__(self, service: str, reason: str):
        super().__init__(reason)
        self.service = service
        self.reason = reason


def _cap_decision(org_id: str, user_id: str):
    """The pre-flight cap decision, or None when caps cannot be read.

    Never raises: a cap store that is missing or unreadable must not stop an outbound
    send. Failing OPEN is deliberate here and is the opposite of the approval gate's
    posture — a cap is a budget, and losing sight of a budget is not a reason to refuse
    work a human asked for. The approval gate governs *permission* and fails closed.
    """
    try:
        from aughor.govern.usage_caps import check
        return check(org_id=org_id, user_id=user_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "usage-cap read is best-effort for outbound calls",
                 counter="outbound.cap_read")
        return None


@contextmanager
def external_call(service: str, operation: str, *,
                  attributes: Optional[dict] = None) -> Generator[dict, None, None]:
    """Wrap one call that leaves the platform.

    ``service`` is the counterparty ("slack", "webhook", later an MCP server id);
    ``operation`` is what is being done ("chat.postMessage", "auth.test"). Yields a
    mutable dict the body may annotate — anything put in it rides out on the session
    event, which is how a caller records the outcome without this module knowing the
    shape of any particular API.

    Raises :class:`OutboundBlocked` if a cap with action ``block`` applies.
    """
    from aughor.obs import session_log as slog
    from aughor.org.context import current_org_id, current_user_id
    from aughor.telemetry import mlflow_tool_span

    org_id, user_id = current_org_id(), current_user_id()

    decision = _cap_decision(org_id, user_id)
    # `allowed` / `reason` are CapDecision's real interface — checked against the class,
    # not assumed. A guard that reads a field the object does not have never fires, and
    # looks identical to a guard that was never breached.
    if decision is not None and not decision.allowed:
        reason = decision.reason or "usage cap reached"
        logger.warning("outbound %s.%s blocked by a usage cap: %s", service, operation, reason)
        raise OutboundBlocked(service, reason)

    attrs = {"service": service, "operation": operation, **(attributes or {})}
    extra: dict = {}
    started = time.monotonic()
    ok = False
    error_class = ""
    try:
        with mlflow_tool_span(f"external.{service}.{operation}", attrs, span_kind="tool"):
            yield extra
        ok = True
    except Exception as exc:
        error_class = type(exc).__name__
        raise
    finally:
        # Recorded on EVERY path — success, refusal and exception alike. An external call
        # that is only recorded when it succeeds gives a usage picture that flatters
        # itself, and hides exactly the failing counterparty worth noticing.
        try:
            slog.emit(
                slog.EXTERNAL_CALL,
                name=f"{service}.{operation}",
                ok=ok,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_class=error_class or None,
                provider=service,
                payload={"operation": operation, **extra},
            )
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "external-call session event is best-effort",
                     counter="outbound.emit")
