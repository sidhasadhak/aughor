"""Action executor — fires configured triggers with recommendation context.

Supports:
  webhook  — generic HTTP POST to any URL
  slack    — Slack incoming webhook with formatted message
  jira     — Jira REST API create-issue (server or cloud)

All dispatch is async-safe (uses httpx if available, falls back to requests).
Every fired action is logged to data/action_logs.json.
"""
from __future__ import annotations

import time
import uuid
import logging
from datetime import datetime, timezone

from aughor.notifications.models import ActionTrigger, ActionPayload, ActionLog
from aughor.notifications.store  import log_action

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
_MAX_ATTEMPTS = 3
#: Never sleep longer than this for a rate limit. A `Retry-After` of ten minutes is a
#: signal to give up and let the next tick carry the message, not to hold a worker.
_MAX_RETRY_AFTER_S = 30.0
#: Slack rejects a payload over 40 KB outright. Trim well below it, with a visible marker:
#: a message that arrives truncated is worth more than one the API refuses.
_MAX_FIELD_CHARS = 1500
_TRUNCATED = "… (truncated)"


def redact_url(url: str) -> str:
    """Scheme and host, never the path. Safe to log, safe to store.

    A Slack incoming-webhook URL **is the credential** — anyone holding
    `hooks.slack.com/services/T…/B…/<secret>` can post as the app, and there is nothing
    else to steal. This module used to log `trigger.url[:60]` on every fire, success and
    failure, which is the workspace id, the channel id and the first characters of the
    secret, written to a log on every alert.

    Deliberately NOT `security.credentials.mask_credentials`: that answers "is this string
    a secret?", which is a judgement that must have exactly one implementation. This
    answers "which part of a URL may be shown", which is not a judgement at all — the path
    of a webhook is never showable.
    """
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return "(unparseable url)"
        return f"{parts.scheme}://{parts.netloc}/…"
    except Exception:                       # noqa: BLE001 — logging must never raise
        return "(unparseable url)"


def _retry_after(resp, attempt: int) -> float:
    """How long to wait for a 429, from the provider's own header where it gives one.

    Slack rate-limits incoming webhooks to roughly one message per second per hook and
    answers 429 with `Retry-After`. Backing off on our own schedule instead of theirs is
    how a burst of alerts turns into a burst of REJECTED alerts."""
    raw = (resp.headers or {}).get("Retry-After", "")
    try:
        wait = float(str(raw).strip())
    except (TypeError, ValueError):
        wait = 0.0
    if wait <= 0:
        wait = 1.5 ** attempt
    return min(wait, _MAX_RETRY_AFTER_S)


def _post(url: str, headers: dict, payload: dict,
          timeout: int = _TIMEOUT_S) -> tuple[int, str, bool]:
    """POST through the outbound seam (VA-9a), retrying per :func:`_post_attempts`.

    ONE span per logical send, with every retry inside it, and the cap checked once
    before the first attempt. A span per attempt would make a rate-limited delivery look
    like three deliveries in the waterfall — the opposite of what the retry policy exists
    to make legible.
    """
    from aughor.govern.outbound import OutboundBlocked, external_call
    try:
        with external_call("webhook", "post", attributes={"attempts_max": _MAX_ATTEMPTS}):
            return _post_attempts(url, headers, payload, timeout)
    except OutboundBlocked as blocked:
        # Nothing left the machine, so this is NOT uncertain — a retry once the window
        # rolls over is legitimate, and marking it uncertain would suppress a send that
        # never happened.
        return 0, f"blocked by a usage cap: {blocked.reason}", False


def _post_attempts(url: str, headers: dict, payload: dict,
                   timeout: int = _TIMEOUT_S) -> tuple[int, str, bool]:
    """POST with a retry policy that matches what each failure MEANS.

    Returns ``(status_code, error, uncertain)``; ``uncertain`` is True when the request may
    already have been delivered.

    The policy this replaces was inverted, in both directions at once. It retried on
    exception — which is mostly a read timeout, the one case where Slack may already have
    posted the message — and it returned any HTTP status immediately, so a **429 or a 502
    was dropped on the floor**. Rate limiting is the normal way a webhook says "slow down",
    and a burst of alerts silently lost the tail of itself.

    So, by cause:
      * connect error / connect timeout — nothing left the machine. Retry.
      * read timeout — it arrived and we did not hear back. NEVER retry; report uncertain
        and let the caller decide, which upstream already knows how to do.
      * 429 — retry on the provider's `Retry-After`, not on ours.
      * 5xx — retry with backoff; the provider is asking us to.
      * other 4xx — a malformed or unauthorised request fails identically next time. Stop.
    """
    import requests

    last_status, last_err = 0, ""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.ConnectTimeout as exc:
            # A CONNECT timeout is not a read timeout: the connection was never
            # established, so nothing was delivered and a retry cannot duplicate.
            last_status, last_err, wait = 0, f"connect timeout: {exc}", 1.5 ** attempt
        except requests.exceptions.Timeout as exc:
            return 0, f"read timeout after {timeout}s: {exc}", True
        except Exception as exc:            # noqa: BLE001 — connection-level, safe to retry
            last_status, last_err, wait = 0, str(exc), 1.5 ** attempt
        else:
            if resp.ok:
                return resp.status_code, "", False
            last_status, last_err = resp.status_code, (resp.text or "")[:200]
            if resp.status_code == 429:
                wait = _retry_after(resp, attempt)
            elif 500 <= resp.status_code < 600:
                wait = 1.5 ** attempt
            else:
                # A malformed or unauthorised request fails identically next time.
                return resp.status_code, last_err, False
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(wait)
    return last_status, last_err, False


#: Slack attachment colour per alert severity — a wall of identical blue bars is not
#: a signal. Anything unrecognised keeps the house blue rather than inventing a colour.
_SEVERITY_COLOR = {"critical": "#CD4246", "warning": "#D1980B", "info": "#2D72D2"}


def _trim(value, limit: int = _MAX_FIELD_CHARS) -> str:
    """Bound one field, with the cut made visible.

    Slack refuses a payload over 40 KB outright — so an unbounded recommendation does not
    arrive long, it does not arrive at all. A reader who can see `… (truncated)` knows to
    open the link; a reader who got nothing does not know there was anything to open.
    """
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - len(_TRUNCATED)] + _TRUNCATED


def _build_slack_payload(trigger: ActionTrigger, payload: ActionPayload) -> dict:
    ctx = payload.context or {}
    if ctx.get("kind") == "monitor_alert":
        # OA·N8-0 — a monitor alert is not a recommendation, and rendering it as one
        # ("Aughor recommendation: Revenue [critical]: …") buries the two things the
        # reader needs first: which monitor, and how bad.
        sev = str(ctx.get("severity") or "info")
        fields = [
            {"title": "Severity",   "value": sev.upper(),                       "short": True},
            {"title": "Metric",     "value": ctx.get("metric_name") or "—",     "short": True},
        ]
        if ctx.get("current_value") is not None:
            observed = f"{ctx['current_value']:g}"
            if ctx.get("threshold") is not None:
                observed += f"  (threshold {ctx['threshold']:g})"
            fields.append({"title": "Observed", "value": observed, "short": True})
        if ctx.get("conn_id"):
            fields.append({"title": "Connection", "value": ctx["conn_id"], "short": True})
        fields.append({"title": "What fired", "value": _trim(ctx.get("message")) or "—",
                       "short": False})
        if ctx.get("caveat"):
            # The monitor's own guard finding. It travels with the alert or the reader
            # acts on a number the platform already doubts.
            fields.append({"title": "Caveat", "value": _trim(ctx["caveat"]), "short": False})
        if ctx.get("deep_link"):
            fields.append({"title": "Open", "value": ctx["deep_link"], "short": False})
        return {
            "channel": trigger.channel or "#general",
            "text": _trim(f"*Monitor alert*: {ctx.get('monitor_name') or 'Monitor'}"),
            "attachments": [{
                "color": _SEVERITY_COLOR.get(sev, "#2D72D2"),
                "fields": fields,
                "footer": "Aughor Intelligence Platform",
                "ts": int(time.time()),
            }],
        }
    return {
        "channel": trigger.channel or "#general",
        "text": _trim(f"*Aughor recommendation*: {payload.recommendation}"),
        "attachments": [{
            "color": "#2D72D2",
            "fields": [
                {"title": "Investigation", "value": payload.investigation_id[:8], "short": True},
                {"title": "Metric",        "value": payload.metric_name or "—",    "short": True},
                {"title": "Headline",      "value": _trim(payload.headline) or "—", "short": False},
            ],
            "footer": "Aughor Intelligence Platform",
            "ts": int(time.time()),
        }],
    }


def _build_jira_payload(trigger: ActionTrigger, payload: ActionPayload) -> dict:
    return {
        "fields": {
            "project":   {"key": trigger.project or "OPS"},
            "issuetype": {"name": trigger.issue_type or "Task"},
            "summary":   payload.recommendation[:200],
            "description": {
                "type":    "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": (
                        f"Aughor recommendation from investigation {payload.investigation_id}.\n\n"
                        f"Recommendation: {payload.recommendation}\n\n"
                        f"Metric: {payload.metric_name or '—'}\n"
                        f"Headline: {payload.headline or '—'}"
                    )}],
                }],
            },
        }
    }


def fire_action(trigger: ActionTrigger, payload: ActionPayload) -> ActionLog:
    """Dispatch a trigger and return an ActionLog record."""
    log_id    = str(uuid.uuid4())[:8]
    fired_at  = datetime.now(timezone.utc).isoformat()

    if not trigger.enabled:
        log = ActionLog(
            id=log_id, trigger_id=trigger.id, trigger_name=trigger.name,
            investigation_id=payload.investigation_id, rec_index=payload.rec_index,
            recommendation=payload.recommendation,
            status="failed", http_status=None, error="Trigger is disabled", fired_at=fired_at,
        )
        log_action(log)
        return log

    # SSRF guard at SEND time (SEC-04): triggers persist and DNS can rebind, so
    # a create-time check alone is insufficient. Never POST to a private/internal
    # target. Failure is recorded like any other action failure (audit trail).
    from aughor.util.url_guard import is_safe_webhook_url
    if not is_safe_webhook_url(trigger.url):
        logger.warning("Action blocked (SSRF guard): %s → %s", trigger.name,
                       redact_url(trigger.url))
        log = ActionLog(
            id=log_id, trigger_id=trigger.id, trigger_name=trigger.name,
            investigation_id=payload.investigation_id, rec_index=payload.rec_index,
            recommendation=payload.recommendation,
            status="failed", http_status=None,
            error="Blocked: URL is not an allowed public http(s) endpoint (SSRF guard)",
            fired_at=fired_at,
        )
        log_action(log)
        return log

    headers = {**trigger.headers, "Content-Type": "application/json"}

    if trigger.type == "slack":
        http_payload = _build_slack_payload(trigger, payload)
    elif trigger.type == "jira":
        http_payload = _build_jira_payload(trigger, payload)
        # Jira REST API uses Basic auth — expect URL to contain credentials or
        # caller sets Authorization header
    else:
        # Generic webhook
        http_payload = payload.to_dict()

    status_code, error, uncertain = _post(trigger.url, headers, http_payload)

    if uncertain:
        # It reached the server and we did not hear back. "failed" would license a retry
        # upstream, and a retried maybe-delivered message is the duplicate this whole
        # policy exists to prevent.
        status = "timeout"
    elif 200 <= status_code < 300:
        status = "ok"
    else:
        status = "failed"
    # A provider's error body can echo the request URL back at us, and that URL is the
    # credential. Redact on the way into the stored log, not only on the way to stdout.
    error = error.replace(trigger.url, redact_url(trigger.url)) if error else error

    log = ActionLog(
        id=log_id, trigger_id=trigger.id, trigger_name=trigger.name,
        investigation_id=payload.investigation_id, rec_index=payload.rec_index,
        recommendation=payload.recommendation,
        status=status, http_status=status_code or None,
        error=error or None, fired_at=fired_at,
    )
    log_action(log)

    # `trigger.url[:60]` used to go here, on every fire. For a Slack webhook that is the
    # workspace id, the channel id and the first characters of the secret — the whole
    # credential is the URL, so 60 characters of it is not a safe prefix, it is a leak
    # written on every alert.
    if status == "ok":
        logger.info("Action fired: %s → %s (%d)", trigger.name, redact_url(trigger.url),
                    status_code)
    else:
        logger.warning("Action %s: %s → %s: %s", status, trigger.name,
                       redact_url(trigger.url), error)

    return log
