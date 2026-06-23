"""LLM provider configuration — Settings → Inference.

Lets a user switch the inference backend / models / API keys at runtime (no env
edit, no restart). Keys are secretvault-encrypted on disk and never returned to
the client (GET reports only whether each key is set)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.llm import provider as _provider

router = APIRouter(tags=["llm"])


@router.get("/llm/config")
def get_llm_config():
    """The effective inference config — backend, models, base URLs, which keys are
    set, plus the available backends and per-backend default models for the UI."""
    return _provider.current_config()


class _ConfigPatch(BaseModel):
    backend: Optional[str] = None
    models: Optional[dict] = None       # {coder?, narrator?, fast?}  ("" clears)
    base_urls: Optional[dict] = None    # {ollama?, lmstudio?}        ("" clears)
    keys: Optional[dict] = None         # {groq?, together?, anthropic?}  ("" clears, masked = unchanged)


@router.post("/llm/config")
def set_llm_config(patch: _ConfigPatch):
    """Merge a partial config and reload live providers. Returns the new config."""
    try:
        return _provider.set_config(patch.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class _TestRequest(BaseModel):
    backend: Optional[str] = None
    model: Optional[str] = None


@router.post("/llm/config/test")
def test_llm_config(req: Optional[_TestRequest] = None):
    """Run a tiny real completion against a backend (defaults to the active one,
    using the saved/env key) to confirm it's reachable and configured."""
    req = req or _TestRequest()
    return _provider.test_provider(backend=req.backend, model=req.model)


class _ProbeRequest(BaseModel):
    role: Optional[str] = None       # which role's bound model to probe (default coder)
    rounds: Optional[int] = None     # shared/distinct calls per series (default 3)


@router.post("/llm/config/cache-probe")
def cache_probe(req: Optional[_ProbeRequest] = None):
    """Measure whether the active binding reuses a shared prompt prefix across requests
    (PLATFORM_ARCHITECTURE.md §5b.3) and persist the verdict so the capability seam adopts
    it. Makes a handful of tiny real completions — defaults to the coder role's model."""
    from aughor.llm import cache_probe as _probe

    req = req or _ProbeRequest()
    return _probe.probe_prefix_cache(role=(req.role or "coder"), rounds=(req.rounds or 3))
