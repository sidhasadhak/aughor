"""ASGI entrypoint shim — the FastAPI app re-exported at a default detection path.

Deployment platforms with zero-config FastAPI detection (Vercel, some PaaS
builders) look for ``app`` in root-level ``main.py``/``app.py``; the real
application lives in ``aughor/api.py``. Local dev is unchanged:
``uvicorn aughor.api:app`` / ``aughor up``.

NOTE (serverless caveat): this API is a stateful, long-running service — it
persists to ``./data`` and runs background jobs/schedulers from its lifespan.
On an ephemeral read-only filesystem it degrades to a stateless demo at best;
see docker-compose.yml for the intended deployment shape.
"""
from aughor.api import app  # noqa: F401
