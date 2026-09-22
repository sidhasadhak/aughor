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
import urllib.parse
import urllib.request
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_POST_URL = "https://slack.com/api/chat.postMessage"
_GET_UPLOAD_URL = "https://slack.com/api/files.getUploadURLExternal"
_COMPLETE_UPLOAD_URL = "https://slack.com/api/files.completeUploadExternal"
_TIMEOUT_S = 15
#: The bytes hop gets its own budget: a chart is small, but it crosses to an S3-backed
#: URL rather than to Slack's API, and 15s is a latency bound tuned for a JSON call.
_UPLOAD_TIMEOUT_S = 30

#: A rendered chart is tens of kilobytes. Anything past this is not a chart any more —
#: refuse it here rather than discover it as a timeout against an upload URL.
_MAX_FILE_BYTES = 8 * 1024 * 1024

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
    # VA-9a — through the outbound seam: budgeted before the send, visible in the
    # waterfall after it. `OutboundBlocked` is caught here because this function
    # promises never to raise and already has an honest failure shape to return.
    from aughor.govern.outbound import OutboundBlocked, external_call
    try:
        with external_call("slack", "chat.postMessage",
                           attributes={"channel": channel, "threaded": bool(thread_ts)}):
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
    except OutboundBlocked as blocked:
        # Not "uncertain": nothing was sent, so a retry is legitimate once the window
        # rolls over. Saying uncertain here would suppress a send that never happened.
        return False, {"error": blocked.reason, "blocked": True}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # Distinguished from a Slack refusal on purpose: a transport failure MAY have
        # delivered, and the engine treats "uncertain" differently from "failed" —
        # a retried maybe-delivered message is the duplicate that layer exists to stop.
        logger.warning("slack chat.postMessage unreachable: %s", exc)
        return False, {"error": str(exc), "uncertain": True}
    if not data.get("ok"):
        return False, {"error": data.get("error", "unknown")}
    return True, {"ts": data.get("ts", ""), "channel": data.get("channel", "")}


def upload_file(bot_token: str, channel_id: str, *, data: bytes, filename: str,
                title: str = "", thread_ts: Optional[str] = None) -> tuple[bool, dict]:
    """Put one file into a channel (or a thread). ``(ok, info)``; never raises.

    Three hops, because the one-shot `files.upload` Slack retired in 2025 is gone:
    ask for an upload URL, PUT the bytes at it, then complete — and only the third
    hop takes `channel_id`/`thread_ts`, which is what actually posts the file.

    ``channel_id`` must be an ID (``C…``), not ``#name``: `completeUploadExternal`
    does not resolve names. Callers that just posted get one for free — `post_as_bot`
    returns Slack's own resolved `channel` — which is why this takes an id and does
    not try to look one up.
    """
    if not (bot_token or "").strip():
        return False, {"error": "no bot token"}
    if not (channel_id or "").strip():
        return False, {"error": "no channel"}
    if not data:
        return False, {"error": "no bytes"}
    if len(data) > _MAX_FILE_BYTES:
        return False, {"error": f"file is {len(data)} bytes, over the {_MAX_FILE_BYTES} cap"}

    name = (filename or "file").strip() or "file"
    from aughor.govern.outbound import OutboundBlocked, external_call
    try:
        # ── 1. where to put it ────────────────────────────────────────────────────
        # Form-encoded, not JSON: this one endpoint rejects an application/json body,
        # and the failure reads as a generic `invalid_arguments` that says nothing.
        form = urllib.parse.urlencode({"filename": name, "length": str(len(data))})
        req = urllib.request.Request(
            _GET_UPLOAD_URL, data=form.encode("utf-8"),
            headers={"Authorization": f"Bearer {bot_token}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with external_call("slack", "files.getUploadURLExternal",
                           attributes={"bytes": len(data)}):
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                ticket = json.loads(resp.read().decode("utf-8") or "{}")
        if not ticket.get("ok"):
            return False, {"error": ticket.get("error", "unknown")}
        upload_url, file_id = ticket.get("upload_url", ""), ticket.get("file_id", "")
        if not upload_url or not file_id:
            return False, {"error": "upload ticket missing url or file id"}

        # ── 2. the bytes ──────────────────────────────────────────────────────────
        body, content_type = _multipart(name, data)
        put = urllib.request.Request(upload_url, data=body,
                                     headers={"Content-Type": content_type})
        with external_call("slack", "files.upload.bytes",
                           attributes={"bytes": len(data)}):
            with urllib.request.urlopen(put, timeout=_UPLOAD_TIMEOUT_S) as resp:
                resp.read()

        # ── 3. post it ────────────────────────────────────────────────────────────
        payload: dict = {"files": [{"id": file_id, "title": title or name}],
                         "channel_id": channel_id}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        done = urllib.request.Request(
            _COMPLETE_UPLOAD_URL, data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {bot_token}",
                     "Content-Type": "application/json; charset=utf-8"},
        )
        with external_call("slack", "files.completeUploadExternal",
                           attributes={"channel": channel_id, "threaded": bool(thread_ts)}):
            with urllib.request.urlopen(done, timeout=_TIMEOUT_S) as resp:
                data_out = json.loads(resp.read().decode("utf-8") or "{}")
    except OutboundBlocked as blocked:
        return False, {"error": blocked.reason, "blocked": True}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # Same distinction `post_as_bot` draws, and it matters more here: hop 2 may
        # have landed. A retry that re-runs all three hops uploads a second copy.
        logger.warning("slack file upload unreachable: %s", exc)
        return False, {"error": str(exc), "uncertain": True}
    if not data_out.get("ok"):
        return False, {"error": data_out.get("error", "unknown")}
    return True, {"file_id": file_id}


def _multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    """One file as multipart/form-data — what Slack's own SDKs PUT at an upload URL."""
    boundary = f"----aughor{uuid.uuid4().hex}"
    head = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + data + tail, f"multipart/form-data; boundary={boundary}"
