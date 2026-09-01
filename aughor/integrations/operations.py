"""VA-11 consumer — what a grant may actually be SPENT on, declared as data.

The vault was built and nothing reached it: `broker.fresh_access_token()` had zero
callers outside its own tests, measured again 2026-09-01 before this module existed.
The missing half was never more vault — it was a roster of things a held token is good
for, and one path that spends one.

**Why a closed roster rather than a URL field.** An effect that took an arbitrary URL
would be a request forgery surface wearing a credential, and it would put the choice of
counterparty in authored config — where a `{"$from": …}` binding could reach it. Here
the URL is a constant of this module, the params are declared and encoded, and the only
thing authored config chooses is WHICH declared row runs. (The general HTTP-template
component is DS-13's, behind its own form and its own review.)

**Everything here is a READ.** A write performed under a user's grant belongs behind the
graduated approval gate, which is the declared-action plane's job — and ROADMAP §3.4
settles the reason in one line: two gates that can disagree is strictly worse than one.
So this roster reads, and a chain that wants to write does it through a declared action
or the Slack door, both of which already pass a gate.

Adding a provider's operation is an entry in `OPERATIONS` plus a mapper — the same
"adapters are DATA" correction that kept the vault itself a wave rather than a quarter
(§3.4). The mapper is a function rather than a path expression because the shapes
genuinely disagree: Gmail returns its headers as a LIST of ``{name, value}`` pairs, and
a dotted-path mini-language that could reach into that would be a language, not data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class OperationParam:
    """One declared input to an operation.

    ``required`` is checked when the automation is SAVED (a binding counts as present),
    so a step missing its message id is refused at authoring time rather than at 07:00 —
    the same law every other config key in this plane follows.
    """

    name: str
    label: str
    required: bool = False
    default: str = ""
    #: What this becomes on the wire: a `{placeholder}` in the path, or a query key.
    #: Named rather than inferred, because a param that silently lands in neither is a
    #: field the form collects and the request never carries.
    query_key: str = ""
    in_path: bool = False


@dataclass(frozen=True)
class Operation:
    """One thing a grant can be spent on, and the shape of what comes back."""

    id: str
    provider: str
    label: str
    blurb: str
    #: The scope the PROVIDER must have granted. Checked against the connection's own
    #: `scopes` before the call, so a consent the user narrowed reads as a sentence
    #: naming the missing scope instead of the provider's 403 three layers down.
    scope: str
    path: str
    params: tuple[OperationParam, ...] = ()
    #: Query params this operation always sends. Constants of the row, never authored.
    fixed_query: tuple[tuple[str, str], ...] = ()
    #: The keys the mapper publishes into the chain context. Advertised on the surface
    #: so the rail can draw the ports; NOT a save-time refusal, because the effect kind's
    #: published set is open (`PUBLISHED_KEYS`) — one kind, many shapes.
    publishes: tuple[str, ...] = ()
    #: Provider response → chain context. The one place a vendor's JSON is read.
    respond: Callable[[dict], dict] = field(default=lambda body: {"ok": True})


# ── response mappers ─────────────────────────────────────────────────────────────
#
# Each returns a flat dict of scalars plus, where the operation is a list, an `items`
# list of dicts — which is what a `for_each` step fans over (W2 publishes `item.<key>`
# from a dict item, so `item.id` and `item.subject` are readable without anything new).

def _gmail_list(body: dict) -> dict:
    msgs = [m for m in (body.get("messages") or []) if isinstance(m, dict)]
    return {
        "count": len(msgs),
        "items": [{"id": str(m.get("id", "")), "thread_id": str(m.get("threadId", ""))}
                  for m in msgs],
        # Gmail's own estimate of the total match, which is NOT len(items): the page
        # size caps the list. A guard reading `count` is reading this page; one reading
        # `estimate` is reading the mailbox. Publishing both beats picking for them.
        "estimate": int(body.get("resultSizeEstimate") or 0),
    }


def _gmail_message(body: dict) -> dict:
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    headers = {str(h.get("name", "")).lower(): str(h.get("value", ""))
               for h in (payload.get("headers") or []) if isinstance(h, dict)}
    return {
        "id": str(body.get("id", "")),
        "subject": headers.get("subject", ""),
        "sender": headers.get("from", ""),
        "date": headers.get("date", ""),
        # The snippet, not the body: this value lands in chain context and can be posted
        # into a channel by a later step. A whole message body reaching Slack because a
        # step bound the obvious-looking key is a disclosure nobody authored.
        "snippet": str(body.get("snippet", "")),
    }


def _calendar_events(body: dict) -> dict:
    items = [e for e in (body.get("items") or []) if isinstance(e, dict)]

    def _when(side: dict) -> str:
        # An all-day event carries `date`; a timed one carries `dateTime`. Reading only
        # one of them makes half a calendar look empty.
        return str(side.get("dateTime") or side.get("date") or "")

    return {
        "count": len(items),
        "items": [{
            "id": str(e.get("id", "")),
            "summary": str(e.get("summary", "")),
            "start": _when(e.get("start") if isinstance(e.get("start"), dict) else {}),
            "end": _when(e.get("end") if isinstance(e.get("end"), dict) else {}),
        } for e in items],
    }


def _graph_messages(body: dict) -> dict:
    vals = [m for m in (body.get("value") or []) if isinstance(m, dict)]

    def _sender(m: dict) -> str:
        frm = m.get("from") if isinstance(m.get("from"), dict) else {}
        addr = frm.get("emailAddress") if isinstance(frm.get("emailAddress"), dict) else {}
        return str(addr.get("address", ""))

    return {
        "count": len(vals),
        "items": [{
            "id": str(m.get("id", "")),
            "subject": str(m.get("subject", "")),
            "sender": _sender(m),
            "date": str(m.get("receivedDateTime", "")),
        } for m in vals],
    }


# ── the roster ───────────────────────────────────────────────────────────────────
#
# Slack is deliberately absent. RC-5's bot door already posts into a channel with a
# token a laptop can obtain, and Slack's OAuth needs an HTTPS callback it cannot
# (`Provider.https_only`, measured against Slack's own docs). A second Slack door here
# would offer the one that install cannot open — the exact failure the catalog's
# `alt_door` rule was written to end.

OPERATIONS: dict[str, Operation] = {op.id: op for op in [
    Operation(
        id="google.gmail.messages.list",
        provider="google",
        label="List Gmail messages",
        blurb="Search the mailbox; publishes the matching ids for a for-each step.",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        path="https://gmail.googleapis.com/gmail/v1/users/me/messages",
        params=(
            OperationParam("q", "Search query", default="is:unread newer_than:1d",
                           query_key="q"),
            OperationParam("max_results", "Max results", default="10",
                           query_key="maxResults"),
        ),
        publishes=("count", "estimate", "items"),
        respond=_gmail_list,
    ),
    Operation(
        id="google.gmail.messages.get",
        provider="google",
        label="Read a Gmail message",
        blurb="Subject, sender and snippet for one message id.",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        path="https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
        params=(
            OperationParam("message_id", "Message id", required=True, in_path=True),
        ),
        # `metadata` format, headers named: the full message would drag the body (and
        # every attachment part) through a chain that asked for a subject line.
        fixed_query=(("format", "metadata"), ("metadataHeaders", "Subject"),
                     ("metadataHeaders", "From"), ("metadataHeaders", "Date")),
        publishes=("id", "subject", "sender", "date", "snippet"),
        respond=_gmail_message,
    ),
    Operation(
        id="google.calendar.events.list",
        provider="google",
        label="List calendar events",
        blurb="Upcoming events on the primary calendar.",
        # NOT in Google's default consent (`providers.py` asks for gmail.readonly), and
        # left that way on purpose: asking every user for a calendar they may never use
        # is how a consent screen teaches people to stop reading it. A grant without it
        # is refused with a sentence naming the scope — which is the honest half of the
        # "provider downgraded the consent" path §3.4 asks this plane to handle.
        scope="https://www.googleapis.com/auth/calendar.readonly",
        path="https://www.googleapis.com/calendar/v3/calendars/primary/events",
        params=(
            OperationParam("time_min", "From (ISO-8601)", query_key="timeMin"),
            OperationParam("max_results", "Max results", default="10",
                           query_key="maxResults"),
        ),
        fixed_query=(("singleEvents", "true"), ("orderBy", "startTime")),
        publishes=("count", "items"),
        respond=_calendar_events,
    ),
    Operation(
        id="microsoft.outlook.messages.list",
        provider="microsoft",
        label="List Outlook messages",
        blurb="Recent mail through Microsoft Graph.",
        scope="Mail.Read",
        path="https://graph.microsoft.com/v1.0/me/messages",
        params=(
            OperationParam("top", "Max results", default="10", query_key="$top"),
        ),
        fixed_query=(("$select", "id,subject,from,receivedDateTime"),
                     ("$orderby", "receivedDateTime desc")),
        publishes=("count", "items"),
        respond=_graph_messages,
    ),
]}


def get_operation(operation_id: str) -> Optional[Operation]:
    return OPERATIONS.get(operation_id)


def operations_for(provider_id: str = "") -> list[Operation]:
    """The roster, optionally narrowed to one provider. Ordered as declared."""
    return [op for op in OPERATIONS.values()
            if not provider_id or op.provider == provider_id]


def scope_granted(operation: Operation, granted: str) -> bool:
    """Does this grant carry the scope the operation needs?

    Space-separated membership, not a substring test. Graph is the standing example:
    `Mail.ReadBasic` contains `Mail.Read` and is strictly NARROWER than it — a substring
    check would read a metadata-only grant as full mail access and send the call anyway.
    Membership over the provider's own delimiter cannot make that mistake.

    An EMPTY granted string means the provider told us nothing about what it granted
    (`Connection.scopes` is read back from the token response and "" is its honest
    value). Unknown is not the same as missing: refusing on it would make every
    provider that omits `scope` unusable, so the call proceeds and the provider gets to
    be the authority on its own permission — which it is.
    """
    if not granted:
        return True
    return operation.scope in granted.split()
