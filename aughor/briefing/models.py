"""Brief subscription model — binds a connection's digest to a schedule + channel."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


from aughor.util.time import now_iso_z as _now


# Sensible default cadences keyed by period.
DEFAULT_CRON = {
    "week": "0 8 * * 1",   # Monday 08:00 UTC
    "day":  "0 8 * * *",   # Every day 08:00 UTC
    # idea 3 — reachable only with `briefing.by_period` on (the router refuses them otherwise)
    "month": "0 8 1 * *",  # the 1st of each month 08:00 UTC
    "year":  "0 8 1 1 *",  # 1 January 08:00 UTC
}

#: What a subscription sends. "alert_summary" is what every subscription has always sent;
#: "briefing" (idea 3, flag `briefing.by_period`) is the Briefing written for its period.
CONTENTS = ("alert_summary", "briefing")

#: Arc BR-5 — a subscription that replaces an automation pauses it after this many delivered
#: mornings (the user's call, ROADMAP §6 item 34(e)): paused, not deleted.
SUPERSEDE_AFTER = 7

#: The fields BR-5 added. Written only when set, so every row stored before them — and every
#: row that never uses them — stays byte-identical.
_BR5_FIELDS = ("bot_id", "channel", "schema_name", "supersedes")


class BriefSubscription(BaseModel):
    """A recurring delivery of a connection's briefing.

    `trigger_id` references an Action Hub trigger (Slack/webhook/Jira) that performs
    the actual delivery — keeping subscriptions decoupled from channel mechanics.
    """
    id:           str = ""
    conn_id:      str
    name:         str
    period:       str = "week"                  # "week" | "day" (+ "month" | "year" with idea 3)
    send_cron:    str = ""                       # cron expr; derived from period if blank
    content:      str = "alert_summary"             # "alert_summary" | "briefing" — see CONTENTS
    trigger_id:   str = ""                       # Action Hub trigger that delivers it — or:
    #: Arc BR-5 — a Slack bot and channel, posting AS the bot the way an automation's
    #: slack_post does (theLook's channel is reached this way; it has no Action Hub trigger).
    bot_id:       str = ""
    channel:      str = ""
    #: Arc BR-5 — the scope the Briefing is built for; "" = the connection. Set, the send and
    #: the Briefing tab share one snapshot (and one narrator call) for that schema.
    schema_name:  str = ""
    #: Arc BR-5 — the automation this subscription replaces, and the mornings delivered so far.
    supersedes:   str = ""
    delivered:    int = 0
    #: Owning workspace; "" = UNOWNED, visible wherever its connection is.
    workspace_id: str = ""
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
        row = self.model_dump()
        # An alert-summary subscription is written exactly as it was before `content` existed, so
        # every stored row and every API payload stays byte-identical until someone picks "briefing".
        if row.get("content") == "alert_summary":
            row.pop("content")
        for k in _BR5_FIELDS:
            if not row.get(k):
                row.pop(k, None)
        if not row.get("delivered"):
            row.pop("delivered", None)
        return row
