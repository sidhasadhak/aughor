"""The inbound email door — ``POST /doors/email`` (the decision-framework study §3.2; `aughor/record/email_door.py`).

Under the ``/doors/`` prefix the API's own key does not reach (`api.py:_AUTH_EXEMPT`): a mail provider cannot present
it. The door checks its own credential instead — the install's inbound secret, as an ``X-Aughor-Inbound-Secret`` header
or the password of HTTP basic auth (what a provider's webhook URL can carry). While the install sets no inbound domain
or no secret it takes no mail, and answers 503 saying which is missing.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["arrivals"])


def _credential(request: Request) -> str:
    given = request.headers.get("x-aughor-inbound-secret", "")
    if given:
        return given
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            return base64.b64decode(auth[6:].strip()).decode().split(":", 1)[-1]
        except Exception:  # noqa: BLE001 — a malformed credential is no credential
            return ""
    return ""


@router.post("/doors/email")
async def receive_email(request: Request) -> dict:
    """One mail sent to a decision's address: an approval, a dissent or evidence, decided by code — said which."""
    from aughor.record import email_door as E
    closed = E.door_closed()
    if closed:
        raise HTTPException(status_code=503, detail=closed)
    if not E.secret_ok(_credential(request)):
        raise HTTPException(status_code=401, detail="the inbound secret is missing or wrong")
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001 — not JSON is said, never guessed
        raise HTTPException(status_code=422, detail="the mail must arrive as JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="the mail must arrive as one JSON object")
    try:
        return E.receive(E.normalise(payload))
    except E.MailRefused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
