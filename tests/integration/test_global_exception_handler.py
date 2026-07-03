"""REC-09 / SEC-06 — unhandled exceptions return a generic 500 with no leak.

An endpoint that raises a bare (non-HTTP) exception must not surface the
exception text/traceback to the client; it returns a stable
``{"error": "internal_error", "request_id": ...}`` while the detail is logged
server-side. HTTPExceptions (intended 4xx/5xx) are untouched.
"""
from __future__ import annotations


def test_unhandled_exception_returns_generic_500(client):
    from aughor.api import app

    @app.get("/_test_unhandled_boom")
    def _boom():
        raise RuntimeError("SECRET internal detail that must not leak")

    r = client.get("/_test_unhandled_boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error"
    assert body.get("request_id")
    # No internal exception text / class / traceback leaks to the client.
    assert "SECRET internal detail" not in r.text
    assert "RuntimeError" not in r.text
    assert "Traceback" not in r.text


def test_httpexception_still_passes_through(client):
    """A deliberate HTTPException keeps its status + detail (not swallowed to 500)."""
    from aughor.api import app
    from fastapi import HTTPException

    @app.get("/_test_teapot")
    def _teapot():
        raise HTTPException(status_code=418, detail="i am a teapot")

    r = client.get("/_test_teapot")
    assert r.status_code == 418
    assert r.json()["detail"] == "i am a teapot"
