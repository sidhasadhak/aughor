"""Brief subscription model — binds a connection's digest to a schedule + channel."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


from aughor.util.time import now_iso_z as _now


# Sensible default cadences keyed by period.
DEFAULT_CRON = {
    "week": "0 8 * * 1",   # Monday 08:00 UTC
    "day":  "0 8 * * *",   # Every day 08:00 UTC
}


class BriefSubscription(BaseModel):
    """A recurring delivery of a connection's briefing.

    `trigger_id` references an Action Hub trigger (Slack/webhook/Jira) that performs
    the actual delivery — keeping subscriptions decoupled from channel mechanics.
    """
    id:           str = ""
    conn_id:      str
    name:         str
    period:       str = "week"                  # "week" | "day"
    send_cron:    str = ""                       # cron expr; derived from period if blank
    trigger_id:   str                            # Action Hub trigger that delivers it
    enabled:      bool = True
    # HB-1 — a subscription says what it is ABOUT and who it is FOR. Both were
    # implicit before (the whole connection, the organisation); "" keeps exactly that
    # reading, so every stored row means what it always did.
    subject:      str = ""                       # a securable ("promise:x", "domain:y"); "" = the connection
    reader:       str = ""                       # a principal ("group:finance", "user:a@b"); "" = the organisation

    created_at:   str = Field(default_factory=_now)
    updated_at:   str = Field(default_factory=_now)
    last_sent_at: Optional[str] = None
    last_status:  Optional[str] = None           # "ok" | "failed" | "timeout"
    last_error:   Optional[str] = None

    def resolved_cron(self) -> str:
        """The cron to schedule on — explicit send_cron wins, else period default."""
        if self.send_cron.strip():
            return self.send_cron.strip()
        return DEFAULT_CRON.get(self.period, DEFAULT_CRON["week"])

    def to_dict(self) -> dict:
        return self.model_dump()
