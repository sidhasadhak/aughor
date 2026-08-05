"""Vercel function entrypoint — the whole platform behind one ASGI app.

Vercel's Python builder builds files under api/; the rewrite in vercel.json routes
every path here, so FastAPI's own router owns the URL space exactly as it does
locally. The app object (and the serverless shape: /tmp surfaces, the loud
AUGHOR_SECRET_KEY check) lives in aughor.api — this file is only the mount point.
"""
from aughor.api import app  # noqa: F401  (Vercel serves the module-level `app`)
