"""Teams bot records — one Azure Bot registration bound to one custom agent (AO-5c).

`LedgerListStore`, like the Slack bots: delivery configuration another instance must see.
The app password is the one secret; it is encrypted on the way in and read only to mint a
Connector token. Reads that serve the API use `to_safe_dict`.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from aughor.db.sqlite_util import resolve_db_path
from aughor.secretvault import decrypt_secret, encrypt_secret, mask_secret
from aughor.util.json_store import LedgerListStore
from aughor.util.time import now_iso_z

_DIR = resolve_db_path("AUGHOR_TEAMSBOTS_DIR", Path("data"))
_STORE = LedgerListStore(_DIR / "teams_bots.json")


class TeamsBot(BaseModel):
    """One Azure Bot registration, answering as one custom agent."""
    id: str = ""
    name: str = ""
    enabled: bool = True
    agent_id: str = ""
    connection_id: str = ""
    #: The Azure Bot's Microsoft App ID — the JWT audience the Bot Framework signs for.
    app_id: str = ""
    #: Its client secret; minted into a Connector token on every reply. Encrypted at rest.
    app_password: str = ""
    #: The tenant the bot lives in ("" = multi-tenant / `botframework.com`).
    tenant_id: str = ""
    created_at: str = Field(default_factory=now_iso_z)
    updated_at: str = Field(default_factory=now_iso_z)

    def to_safe_dict(self) -> dict:
        d = self.model_dump()
        d["app_password"] = mask_secret(d.get("app_password") or "")
        return d


def _new_id() -> str:
    return f"tb_{uuid.uuid4().hex[:12]}"


def list_bots(*, include_disabled: bool = True) -> list[TeamsBot]:
    rows = [TeamsBot(**r) for r in _STORE.all()]
    return rows if include_disabled else [b for b in rows if b.enabled]


def get_bot(bot_id: str) -> Optional[TeamsBot]:
    row = next((r for r in _STORE.all() if r.get("id") == bot_id), None)
    return TeamsBot(**row) if row else None


def get_bot_decrypted(bot_id: str) -> Optional[TeamsBot]:
    bot = get_bot(bot_id)
    if bot is None:
        return None
    return bot.model_copy(update={"app_password": decrypt_secret(bot.app_password or "") or ""})


def save_bot(bot: TeamsBot) -> TeamsBot:
    if not bot.id:
        bot = bot.model_copy(update={"id": _new_id()})
    bot = bot.model_copy(update={"updated_at": now_iso_z(),
                                 "app_password": encrypt_secret(bot.app_password or "") or ""})
    _STORE.upsert(bot.model_dump())
    return bot


def delete_bot(bot_id: str) -> bool:
    return bool(_STORE.delete(bot_id))


def bots_for_agent(agent_id: str) -> list[TeamsBot]:
    return [b for b in list_bots() if b.agent_id == agent_id]
