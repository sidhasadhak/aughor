"""An unexpected error is readable by the page that asked (2026-10-07).

Starlette runs the catch-all `Exception` handler outside CORSMiddleware, so its 500 carried no
CORS header: the Cockpit's NaN crash reached the browser as "Failed to fetch", not as the
`{error, request_id}` body that names the traceback in the log.
"""
from __future__ import annotations

import asyncio

from starlette.requests import Request

from aughor import api


def _request(origin: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/exploration/workspace/briefing/measures",
                    "headers": [(b"origin", origin.encode())], "query_string": b""})


def test_a_500_carries_the_cors_header_for_an_allowed_origin_and_only_for_one():
    allowed = api._cors_origins[0]
    answered = asyncio.run(api._unhandled_exception_handler(_request(allowed), ValueError("boom")))
    assert answered.status_code == 500
    assert answered.headers["access-control-allow-origin"] == allowed
    other = asyncio.run(api._unhandled_exception_handler(_request("https://evil.example"), ValueError("boom")))
    assert "access-control-allow-origin" not in other.headers
