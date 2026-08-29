"""Post into a channel AS a bot (RC-5.4).

The distinction this module exists to make: `notifications/executor.py` posts through an
incoming WEBHOOK, which arrives under the webhook's own identity, in a channel, with no
thread anyone can reply into. A scheduled run therefore dead-ends the moment it lands.

Posting with the bot's `chat:write` token instead arrives AS the bot — mentionable,
repliable, and threaded. That is what closes the loop: the reply lands in a thread whose
`ts` the bot already uses as the Aughor `session_id`, so a follow-up composes on the same
conversation, with the same agent, over the same connection. The difference between a bot
that notifies and one that behaves like a colleague is this function.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_POST_URL = "https://slack.com/api/chat.postMessage"
_TIMEOUT_S = 15

#: Slack rejects a payload over 40 KB outright, so an unbounded report becomes a silent
#: non-delivery. Trim well below it, with a visible marker — the same bound and the same
#: reasoning as the webhook path.
_MAX_TEXT = 30_000


def post_as_bot(bot_token: str, channel: str, text: str,
                thread_ts: Optional[str] = None) -> tuple[bool, dict]:
    """``(ok, info)``. Never raises; the caller turns this into an EffectOutcome.

    ``info`` carries ``ts`` on success — the thread root a reply will land in, and the id
    that becomes the Aughor conversation for everything that follows.
    """
    if not (bot_token or "").strip():
        return False, {"error": "no bot token"}
    if not (channel or "").strip():
        return False, {"error": "no channel"}

    body = (text or "").strip() or "(no message)"
    if len(body) > _MAX_TEXT:
        body = body[:_MAX_TEXT] + "\n\n…truncated."

    payload = {"channel": channel, "text": body}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    req = urllib.request.Request(
        _POST_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {bot_token}",
                 "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # Distinguished from a Slack refusal on purpose: a transport failure MAY have
        # delivered, and the engine treats "uncertain" differently from "failed" —
        # a retried maybe-delivered message is the duplicate that layer exists to stop.
        logger.warning("slack chat.postMessage unreachable: %s", exc)
        return False, {"error": str(exc), "uncertain": True}
    if not data.get("ok"):
        return False, {"error": data.get("error", "unknown")}
    return True, {"ts": data.get("ts", ""), "channel": data.get("channel", "")}
