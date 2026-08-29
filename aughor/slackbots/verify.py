"""Confirm a Slack credential actually works, before a record claims it does (RC-5).

`auth.test` is the cheapest call that proves a bot token is live AND tells us who it is:
the team, the app and the bot's own user id all come back from it, so verification and
identity capture are one round trip rather than two.

Deliberately not a mock-friendly abstraction over the whole Slack API — this module has
exactly one job, so a test can substitute one function.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_AUTH_TEST_URL = "https://slack.com/api/auth.test"
_TIMEOUT_S = 10


def auth_test(bot_token: str) -> tuple[bool, dict]:
    """``(ok, info)`` for a bot token. Never raises.

    A network failure is reported as a failure to VERIFY, not as a bad token — the two
    are different facts, and telling a user their token is wrong when Slack was simply
    unreachable sends them to rotate a credential that was fine.
    """
    if not (bot_token or "").strip():
        return False, {"error": "no token supplied"}
    req = urllib.request.Request(
        _AUTH_TEST_URL,
        data=b"",                                  # auth.test takes no body
        headers={"Authorization": f"Bearer {bot_token}",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    from aughor.govern.outbound import OutboundBlocked, external_call
    try:
        with external_call("slack", "auth.test"):
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
    except OutboundBlocked as blocked:
        # Reported as a failure to VERIFY, not a bad token — the same distinction the
        # network branch below makes, and for the same reason.
        return False, {"error": f"not verified: {blocked.reason}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("slack auth.test unreachable: %s", exc)
        return False, {"error": f"could not reach Slack to verify ({exc})"}
    if not body.get("ok"):
        return False, {"error": body.get("error", "invalid_auth")}
    return True, {
        "team_id": body.get("team_id", ""),
        "user_id": body.get("user_id", ""),     # the BOT's own user id
        "app_id": body.get("app_id", ""),
        "team": body.get("team", ""),
    }
