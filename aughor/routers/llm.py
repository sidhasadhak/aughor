"""LLM provider configuration — Settings → Inference.

Lets a user switch the inference backend / models / API keys at runtime (no env
edit, no restart). Keys are secretvault-encrypted on disk and never returned to
the client (GET reports only whether each key is set)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.licensing import Capability, gate
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


@router.post("/llm/config", dependencies=[gate(Capability.SECURITY_SUITE)])
def set_llm_config(patch: _ConfigPatch):
    """Merge a partial config and reload live providers. Returns the new config.

    Gated (SEC-10): changing the inference backend / models / API keys is an
    admin-grade action — an ungated caller could pivot all inference to an
    attacker endpoint (exfil) or set keys. Default tier is enterprise, so this is
    a no-op today; it becomes real the moment lower tiers exist.
    """
    try:
        return _provider.set_config(patch.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class _TestRequest(BaseModel):
    backend: Optional[str] = None
    model: Optional[str] = None            # explicit → test just that one
    include_agents: bool = False           # also ping each per-agent pinned model


@router.post("/llm/config/test")
def test_llm_config(req: Optional[_TestRequest] = None):
    """Real completions against a backend to confirm it is reachable and configured.

    Tests every DISTINCT model the deployment would use — all three role
    bindings, and the per-agent pins with ``include_agents`` — not just the coder
    model. A single-model check said nothing about a narrator or fast binding
    that may be a different model entirely.
    """
    req = req or _TestRequest()
    return _provider.test_provider(backend=req.backend, model=req.model,
                                   include_agents=req.include_agents)


class _CustomModelIn(BaseModel):
    backend: str
    model: str


@router.get("/llm/models")
def list_llm_models(backend: Optional[str] = None, refresh: bool = False):
    """The model catalogue for the picker — live list where the backend serves
    one, a curated floor otherwise, plus the user's kept custom entries.

    Not gated: reading which models exist is not privileged, and the picker needs
    it to render. Writing the config (which model to USE, and the keys) stays
    behind SECURITY_SUITE on POST /llm/config.
    """
    from aughor.llm import models as _models

    target = backend or _provider.current_config()["backend"]
    try:
        return _models.list_models(target, refresh=refresh)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/llm/models", dependencies=[gate(Capability.SECURITY_SUITE)])
def add_llm_model(body: _CustomModelIn):
    """Keep a typed model in the picker for next time. Idempotent.

    Gated with the rest of the inference config: a custom entry is a suggestion
    an operator will later click, so writing it is the same trust boundary as
    writing the config it feeds.
    """
    from aughor.llm import models as _models

    try:
        return {"backend": body.backend,
                "custom": _models.add_custom_model(body.backend, body.model)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/llm/models", dependencies=[gate(Capability.SECURITY_SUITE)])
def remove_llm_model(backend: str, model: str):
    """Drop a custom entry. Built-in and live entries are not removable — hiding
    a model the backend actually serves would make the picker lie."""
    from aughor.llm import models as _models

    try:
        return {"backend": backend,
                "custom": _models.remove_custom_model(backend, model)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
