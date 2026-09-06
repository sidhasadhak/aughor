"""SP-3 — per-user preferences over HTTP: the same two verbs Spotlight's tool uses.

No capability gate on purpose: a preference is a cosmetic, self-scoped write (the store's
own custody line), available on every tier the way the theme toggle in Settings already
is. The org/user scope rides the identity contextvars, so an identified deployment shards
per user and a local one lives under "local" — the store documents that seam.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["preferences"])


@router.get("/me/preferences")
def read_preferences():
    from aughor.db.user_prefs import get_preferences
    return get_preferences()


class PreferenceValue(BaseModel):
    value: Any = None


@router.put("/me/preferences/{key}")
def write_preference(key: str, body: PreferenceValue):
    from aughor.db.user_prefs import set_preference
    try:
        return set_preference(key, body.value)
    except ValueError as exc:
        # The store's refusal sentence is the useful half — a closed key registry
        # answering with its known keys, never a silent write of a typo'd key.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
