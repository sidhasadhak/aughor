"""Persistence for Slack bot records (RC-5).

`LedgerListStore`, deliberately — the same store `notifications/store.py` uses for
ActionHub triggers, and for the same reason. A bot record is *delivery configuration
another instance must see*: the supervisor process reads it to decide which sockets to
open, and on serverless a record written by one instance must be visible to the next.
The file-backed store is what once let a brief subscription be "created" into a
read-only bundle and evaporate with the response, so every cron tick evaluated zero
briefs. The Ledger rides `AUGHOR_DB_URL`, which is durable.

It also means **no migration**, which keeps this wave clear of the numbering trap
entirely (`PRAGMA user_version` has to be read off the LIVE db, and no hermetic test
can catch a wrong number).

Secrets are encrypted on the way in and decrypted only for the caller that must open a
socket. Read paths that serve the API use `SlackBot.to_safe_dict`.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path
from aughor.slackbots.models import SlackBot, decrypt_secrets, encrypt_secrets
from aughor.util.json_store import LedgerListStore
from aughor.util.time import now_iso_z

_DIR = resolve_db_path("AUGHOR_SLACKBOTS_DIR", Path("data"))
_STORE = LedgerListStore(_DIR / "slack_bots.json")


def _new_id() -> str:
    return f"sb_{uuid.uuid4().hex[:12]}"


def list_bots(*, include_disabled: bool = True) -> list[SlackBot]:
    """Every stored bot, secrets still encrypted."""
    out = [SlackBot(**d) for d in _STORE.all()]
    return out if include_disabled else [b for b in out if b.enabled]


def get_bot(bot_id: str) -> Optional[SlackBot]:
    d = _STORE.get(bot_id)
    return SlackBot(**d) if d else None


def get_bot_decrypted(bot_id: str) -> Optional[SlackBot]:
    """The form the supervisor needs — plaintext tokens, for opening a socket."""
    bot = get_bot(bot_id)
    return decrypt_secrets(bot) if bot else None


def save_bot(bot: SlackBot) -> SlackBot:
    """Create or update. Secrets are encrypted here so no caller can forget to."""
    if not bot.id:
        bot = bot.model_copy(update={"id": _new_id()})
    bot = bot.model_copy(update={"updated_at": now_iso_z()})
    _STORE.upsert(encrypt_secrets(bot).to_dict())
    return bot


def delete_bot(bot_id: str) -> bool:
    return _STORE.delete(bot_id)


def bots_for_owner(owner: str) -> list[SlackBot]:
    """Every bot belonging to one person, plus the org's unowned ones.

    Unowned bots are included deliberately: `owner=""` is what every bot created before
    VA-9b carries, and a shared workspace bot is a legitimate thing to keep. Excluding
    them would make this field a silent migration rather than an addition.
    """
    return [b for b in list_bots() if not b.owner or b.owner == owner]


def bots_for_agent(agent_id: str) -> list[SlackBot]:
    """Every bot fronting one agent — the query an agent-delete cascade needs, so a
    deleted agent does not leave a live socket answering as it."""
    return [b for b in list_bots() if b.agent_id == agent_id]
