"""Answer back into the Teams conversation (AO-5c) through the Bot Connector.

Two calls: a client-credentials token for the bot (its app id and password, scope
`https://api.botframework.com/.default`), then `POST {serviceUrl}v3/conversations/{id}/
activities/{replyTo}` with a message activity. The `serviceUrl` is the inbound activity's
own — the Connector tells the bot where to answer — and is never guessed.

urllib, one job per function, never raises; a transport failure is `(False, why)`.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

TOKEN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
SCOPE = "https://api.botframework.com/.default"
_TIMEOUT_S = 15


def connector_token(app_id: str, app_password: str) -> tuple[bool, str]:
    """``(ok, token_or_why)``."""
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": app_id,
        "client_secret": app_password, "scope": SCOPE,
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                 headers={"content-type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, f"could not mint a Connector token: {exc}"
    token = str(payload.get("access_token") or "")
    return (True, token) if token else (False, f"no token: {payload.get('error_description') or payload}")


def send_reply(*, service_url: str, conversation_id: str, reply_to_id: str, text: str,
               token: str, recipient: dict | None = None, from_: dict | None = None) -> tuple[bool, dict]:
    """Post one message activity into the conversation. ``(ok, payload)``."""
    base = (service_url or "").rstrip("/") + "/"
    url = f"{base}v3/conversations/{urllib.parse.quote(conversation_id, safe='')}/activities/" \
          f"{urllib.parse.quote(reply_to_id or '', safe='')}"
    activity = {"type": "message", "text": text, "textFormat": "markdown",
                "replyToId": reply_to_id or None,
                **({"recipient": recipient} if recipient else {}),
                **({"from": from_} if from_ else {})}
    req = urllib.request.Request(
        url, data=json.dumps(activity).encode("utf-8"), method="POST",
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8") or "{}"
            try:
                return True, json.loads(body)
            except ValueError:
                return True, {"raw": body[:200]}
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, {"error": f"could not reach the Bot Connector: {exc}"}


def render_answer(answer: dict, *, money_symbol: str = "") -> str:
    """The folded answer as Teams markdown: the headline, then the rows (capped), then the
    SQL in a code block — every number the agent states, beside what it ran."""
    from aughor.answer.exhibit import reader_table

    lines = [answer.get("headline") or answer.get("error") or "No answer."]
    cols = answer.get("columns") or []
    rows = answer.get("rows") or []
    if cols and rows:
        # CP-5 — the one table builder; Teams' encodings are its own: ten rows, eight columns.
        table = reader_table(cols, rows, max_cols=8, max_rows=10, preview_rows=10,
                             rest="the rest are not shown here", money_symbol=money_symbol)
        lines += ["", table.markdown]
        if answer.get("truncated") and table.shown == table.total:
            lines.append(f"_… {answer.get('row_count') or len(rows)} rows in all_")
    if answer.get("sql"):
        lines += ["", "```sql", str(answer["sql"])[:1500], "```"]
    if answer.get("receipt_id"):
        lines.append(f"_receipt {answer['receipt_id']}_")
    return "\n".join(lines)
