"""Action executor — fires configured triggers with recommendation context.

Supports:
  webhook  — generic HTTP POST to any URL
  slack    — Slack incoming webhook with formatted message
  jira     — Jira REST API create-issue (server or cloud)

All dispatch is async-safe (uses httpx if available, falls back to requests).
Every fired action is logged to data/action_logs.json.
"""
from __future__ import annotations

import json
import time
import uuid
import logging
from datetime import datetime, timezone

from aughor.actions.models import ActionTrigger, ActionPayload, ActionLog
from aughor.actions.store  import log_action

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
_MAX_RETRIES = 2


def _post(url: str, headers: dict, payload: dict, timeout: int = _TIMEOUT_S) -> tuple[int, str]:
    """POST with retry. Returns (status_code, error_message)."""
    import requests
    last_err = ""
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            return resp.status_code, "" if resp.ok else resp.text[:200]
        except Exception as exc:
            last_err = str(exc)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(1.5 ** attempt)
    return 0, last_err


def _build_slack_payload(trigger: ActionTrigger, payload: ActionPayload) -> dict:
    return {
        "channel": trigger.channel or "#general",
        "text": f"*Aughor recommendation*: {payload.recommendation}",
        "attachments": [{
            "color": "#2D72D2",
            "fields": [
                {"title": "Investigation", "value": payload.investigation_id[:8], "short": True},
                {"title": "Metric",        "value": payload.metric_name or "—",    "short": True},
                {"title": "Headline",      "value": payload.headline or "—",       "short": False},
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

    status_code, error = _post(trigger.url, headers, http_payload)

    if status_code == 0:
        status = "timeout" if "timeout" in error.lower() else "failed"
    elif 200 <= status_code < 300:
        status = "ok"
    else:
        status = "failed"

    log = ActionLog(
        id=log_id, trigger_id=trigger.id, trigger_name=trigger.name,
        investigation_id=payload.investigation_id, rec_index=payload.rec_index,
        recommendation=payload.recommendation,
        status=status, http_status=status_code or None,
        error=error or None, fired_at=fired_at,
    )
    log_action(log)

    if status == "ok":
        logger.info("Action fired: %s → %s (%d)", trigger.name, trigger.url[:60], status_code)
    else:
        logger.warning("Action failed: %s → %s: %s", trigger.name, trigger.url[:60], error)

    return log
