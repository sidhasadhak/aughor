"""DS-11 — what a grant may DO, declared as data.

`providers.py` says how to *get* a token. This says what a token may be *spent on*, in the
same shape and for the same reason: an operation is forty lines of data — a method, a URL,
the scopes it needs, its typed params and what it publishes — and a provider gains one by
an entry here plus nothing.

**The law this file exists to keep: a component references a governed capability; no node
is code.** DS-13 is the wave that lets a *user* declare an HTTP component from a form.
Until then the set of URLs this platform will call on a user's behalf is closed, reviewed
and in the repository — so an author placing an integration step chooses from a roster,
never types an endpoint. That is the difference between a palette and an SSRF surface.

Three rules make the closed set actually closed:

1. **A param can never move the host or the path.** Declared params land in the query
   string or the JSON body. The only exception is a ``{placeholder}`` in the URL, which
   must be declared ``in_path`` and is percent-encoded with an EMPTY safe set — so a
   message id of ``../../admin`` addresses a message literally called that, and reaches
   nothing else. A ratchet asserts every placeholder is a declared path param.
2. **Only declared params are sent.** An undeclared key is refused rather than forwarded:
   forwarding it would make the caller, not this file, the author of the request.
3. **Published keys are declared per operation** — including which of them are LISTS. That
   is what lets `validate_chain` refuse `{"$from": "step1.snippet"}` on a step that lists
   messages, and lets `for_each` fan over one that does. Before this, nothing in the
   automation plane published a list at all (§3.2's measured limit); a remote read is the
   first thing that honestly does.

**Scopes are stated, not guessed.** Every operation here is covered by a scope its provider's
cards ask for (``Provider.requestable_scopes`` — its own, or one product's), so the roster a
fresh grant can run is the roster it was granted — a
row that needs a scope the user never consented to is a row that dims with a sentence
naming the scope, not one that fails at 09:00 with the provider's own 403.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Optional
from urllib.parse import quote

from pydantic import BaseModel, Field

#: A `{placeholder}` in a URL template. Deliberately narrow — a name, nothing else — so a
#: template can carry no expression, no nesting and no format spec.
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class OperationParam(BaseModel):
    """One typed input to an operation — the port an author fills or binds."""

    name: str
    label: str = ""
    type: Literal["string", "number", "boolean", "object", "list"] = "string"
    required: bool = False
    #: Goes into the URL path rather than the query/body. Percent-encoded on the way in.
    in_path: bool = False
    placeholder: str = ""
    #: The value used when the author supplies none. Kept here rather than in the caller
    #: so "what does this step do with nothing filled in" has one answer.
    default: Any = None
    #: May a chain BIND this input to an earlier step's output? True for every param
    #: whose value is a datum (a message id, a channel, a body); false for the ones that
    #: are a knob on the request itself (`limit`), because an edge onto a page size is a
    #: picture of dataflow nobody meant to draw.
    bindable: bool = True


class ResultShape(BaseModel):
    """How one provider's JSON becomes the keys a later step may read.

    Declarative — a dotted path, never a callable — for the same reason the params are:
    the shape has to be *readable* by the registry and the validator, not only executable
    by the dispatcher. `items_path` names the list a provider buries under its own noun
    (`messages`, `channels`, `value`); `fields` names the scalars worth publishing.
    """

    #: Dotted path to the list this operation returns, if it returns one.
    items_path: str = ""
    #: The keys kept from each ITEM of that list. Not cosmetic — it is the bound on what
    #: a remote read drags into a stored automation run: Graph's `/me/messages` returns
    #: whole messages, bodies included, and a run history is read by people and kept.
    #: Empty means the item is published as the provider sent it, which is only ever
    #: declared for a list whose items are already two identifiers.
    item_fields: tuple[str, ...] = ()
    #: ``published key -> dotted path in the response body``.
    fields: dict[str, str] = Field(default_factory=dict)
    #: ``published key -> path through each ITEM`` whose strings are joined into one text.
    #: A ``[]`` part walks every element of a list. For a provider that keeps an item's words
    #: deep in nested lists — a Google slide's text sits under its page elements' text runs
    #: (2026-10-07) — still a declared path, never a callable.
    item_text: dict[str, str] = Field(default_factory=dict)


class Operation(BaseModel):
    """One thing a grant may do, at one provider."""

    id: str                                   # "gmail.messages.list" — unique per provider
    provider: str                             # "google" | "slack" | "microsoft"
    label: str
    description: str = ""
    method: Literal["GET", "POST"] = "GET"
    #: The absolute URL, with at most `{placeholder}`s naming ``in_path`` params.
    url: str
    #: Scopes the provider must have granted. Checked against what the CONNECTION says was
    #: granted (read back from the token response), never against what we asked for.
    scopes: tuple[str, ...] = ()
    params: tuple[OperationParam, ...] = ()
    result: ResultShape = Field(default_factory=ResultShape)
    #: Does this operation CHANGE something at the provider? A write passes the graduated
    #: approval gate before it is made; a read does not. Carried as a fact about the
    #: operation rather than inferred from the HTTP verb, because a POST that searches
    #: (which several of these APIs have) is not a write and gating it would teach an
    #: operator that the gate fires on things that change nothing.
    writes: bool = False
    #: Risk tier for the approval gate — HIGH is what makes an un-allowlisted write stop.
    risk: Literal["low", "medium", "high"] = "low"
    #: This provider reports failure in the BODY, not the status line. Slack answers
    #: `200 {"ok": false, "error": "channel_not_found"}`; treating that as success is the
    #: classic way an integration reports a message it never sent. Measured off
    #: `slackbots/post.py`, which already carries the same check.
    ok_in_body: bool = False

    # ── derived, so every reader agrees ──────────────────────────────────────────

    @property
    def publishes(self) -> tuple[str, ...]:
        """What later steps may bind to. A CLOSED set — this is the first effect kind
        whose keys are knowable at save time per instance, so B1's unknown-key refusal
        finally covers a remote call."""
        keys: list[str] = []
        if self.result.items_path:
            keys += ["items", "count"]
        keys += list(self.result.fields)
        return tuple(keys)

    @property
    def list_keys(self) -> tuple[str, ...]:
        """Which published keys are LISTS — the ones `for_each` may fan over. Everything
        else is refused as a fan source at SAVE, exactly as W2 refuses a string today."""
        return ("items",) if self.result.items_path else ()

    @property
    def path_params(self) -> tuple[str, ...]:
        return tuple(m.group(1) for m in _PLACEHOLDER.finditer(self.url))

    @property
    def gov_action(self) -> str:
        """The name this operation is audited and allowlisted under.

        A property rather than an f-string at each call site because three modules now
        spell it — the call seam gates on it, the proposal inbox audits an accept and a
        reject under it, and an operator allowlists it by hand. Two spellings would mean
        an allowlist entry that permits a name nothing checks, which looks exactly like a
        gate that is working.
        """
        return f"integration.{self.provider}.{self.id}"


# ── the roster ───────────────────────────────────────────────────────────────────
#
# Small on purpose. The first six proved one shape each: a list (the fan source), a single
# fetch (a path param), and a write (the approval gate). Google's four read tools
# (2026-10-07) are copies of those shapes, one per product a Google card connects — each
# covered by that product's own scope, so connecting the card is what lets its tool run.

_GOOGLE_AUTH = "https://www.googleapis.com/auth/"

OPERATIONS: tuple[Operation, ...] = (
    # ── Google ───────────────────────────────────────────────────────────────────
    Operation(
        id="gmail.messages.list",
        provider="google",
        label="Gmail · list messages",
        description="Message ids matching a Gmail search query, newest first.",
        url="https://gmail.googleapis.com/gmail/v1/users/me/messages",
        scopes=("https://www.googleapis.com/auth/gmail.readonly",),
        params=(
            OperationParam(name="q", label="Search", placeholder="is:unread newer_than:1d"),
            OperationParam(name="maxResults", label="Limit", type="number", default=10,
                           bindable=False),
        ),
        result=ResultShape(items_path="messages", item_fields=("id", "threadId"),
                           fields={"next_page_token": "nextPageToken"}),
    ),
    Operation(
        id="gmail.messages.get",
        provider="google",
        label="Gmail · read a message",
        description="One message's snippet and thread, by id — what a list step fans over.",
        url="https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}",
        scopes=("https://www.googleapis.com/auth/gmail.readonly",),
        params=(
            OperationParam(name="id", label="Message id", required=True, in_path=True,
                           placeholder='{"$from": "step1.item.id"}'),
            # `metadata` keeps the body out of our process entirely: this step exists to
            # decide whether something is worth acting on, and the full MIME payload is
            # both large and the most sensitive thing the grant can reach.
            OperationParam(name="format", label="Format", default="metadata",
                           bindable=False),
        ),
        result=ResultShape(fields={"id": "id", "thread_id": "threadId",
                                   "snippet": "snippet"}),
    ),
    # ── Google Sheets, Slides, Drive, Calendar — one read each ─────────────────────
    Operation(
        id="sheets.values.get",
        provider="google",
        label="Sheets · read a range",
        description="The cells of one range of a spreadsheet, row by row — at most 200 rows, "
                    "so name a range that fits.",
        url="https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}",
        scopes=(_GOOGLE_AUTH + "spreadsheets.readonly",),
        params=(
            OperationParam(name="spreadsheet_id", label="Spreadsheet id", required=True,
                           in_path=True, placeholder="the id in …/spreadsheets/d/<id>/"),
            OperationParam(name="range", label="Range", required=True, in_path=True,
                           placeholder="Sheet1!A1:F50"),
        ),
        result=ResultShape(items_path="values", fields={"range": "range"}),
    ),
    Operation(
        id="slides.presentations.get",
        provider="google",
        label="Slides · read a presentation",
        description="Its title and the text of each slide's shapes and text boxes, in order.",
        url="https://slides.googleapis.com/v1/presentations/{presentation_id}",
        scopes=(_GOOGLE_AUTH + "presentations.readonly",),
        params=(
            OperationParam(name="presentation_id", label="Presentation id", required=True,
                           in_path=True, placeholder="the id in …/presentation/d/<id>/"),
            # Only the text runs come back — no images, layouts or masters — which keeps a
            # whole deck to a few kilobytes in a stored run.
            OperationParam(name="fields", label="Fields", bindable=False,
                           default="title,slides(objectId,pageElements(shape(text(textElements(textRun(content))))))"),
        ),
        result=ResultShape(items_path="slides", item_fields=("objectId",),
                           item_text={"text": "pageElements[].shape.text.textElements[].textRun.content"},
                           fields={"title": "title"}),
    ),
    Operation(
        id="drive.files.list",
        provider="google",
        label="Drive · find files",
        description="Files matching a Drive search, newest first — names, types and links, "
                    "never their contents.",
        url="https://www.googleapis.com/drive/v3/files",
        scopes=(_GOOGLE_AUTH + "drive.metadata.readonly",),
        params=(
            OperationParam(name="q", label="Search",
                           placeholder="name contains 'budget' and trashed = false"),
            OperationParam(name="pageSize", label="Limit", type="number", default=20,
                           bindable=False),
            OperationParam(name="orderBy", label="Order", default="modifiedTime desc",
                           bindable=False),
            OperationParam(name="fields", label="Fields", bindable=False,
                           default="files(id,name,mimeType,modifiedTime,webViewLink),nextPageToken"),
        ),
        result=ResultShape(items_path="files",
                           item_fields=("id", "name", "mimeType", "modifiedTime", "webViewLink"),
                           fields={"next_page_token": "nextPageToken"}),
    ),
    Operation(
        id="calendar.events.list",
        provider="google",
        label="Calendar · list events",
        description="Events on your main calendar from a start time, soonest first.",
        url="https://www.googleapis.com/calendar/v3/calendars/primary/events",
        scopes=(_GOOGLE_AUTH + "calendar.readonly",),
        params=(
            OperationParam(name="timeMin", label="From", required=True,
                           placeholder="2026-10-08T00:00:00Z"),
            OperationParam(name="timeMax", label="Until", placeholder="2026-10-15T00:00:00Z"),
            OperationParam(name="q", label="Search", placeholder="board review"),
            OperationParam(name="maxResults", label="Limit", type="number", default=25,
                           bindable=False),
            # A recurring meeting as its single occurrences, in time order — what "what is
            # on this week" means; without these Google returns the series, unordered.
            OperationParam(name="singleEvents", label="Expand recurring", type="boolean",
                           default=True, bindable=False),
            OperationParam(name="orderBy", label="Order", default="startTime", bindable=False),
        ),
        result=ResultShape(items_path="items",
                           item_fields=("id", "summary", "start", "end", "location", "htmlLink"),
                           fields={"next_page_token": "nextPageToken"}),
    ),
    # ── Slack ────────────────────────────────────────────────────────────────────
    Operation(
        id="slack.conversations.list",
        provider="slack",
        label="Slack · list channels",
        description="Channels this grant can see.",
        url="https://slack.com/api/conversations.list",
        scopes=("channels:read",),
        params=(
            OperationParam(name="limit", label="Limit", type="number", default=100,
                           bindable=False),
        ),
        result=ResultShape(items_path="channels",
                           item_fields=("id", "name", "is_private")),
        ok_in_body=True,
    ),
    Operation(
        id="slack.chat.postMessage",
        provider="slack",
        label="Slack · post a message",
        description="Post into a channel as the connected Slack account.",
        method="POST",
        url="https://slack.com/api/chat.postMessage",
        scopes=("chat:write",),
        params=(
            OperationParam(name="channel", label="Channel", required=True,
                           placeholder="#revenue or C0…"),
            OperationParam(name="text", label="Message", required=True,
                           placeholder='{"$from": "step1.answer"}'),
            OperationParam(name="thread_ts", label="Reply in thread"),
        ),
        # The same two keys `slack_post` publishes, spelled the same way: two surfaces
        # that post to Slack and name the thread root differently is a chain that breaks
        # when its author swaps one door for the other.
        result=ResultShape(fields={"ts": "ts", "channel": "channel"}),
        writes=True,
        risk="high",
        ok_in_body=True,
    ),
    # ── Microsoft ────────────────────────────────────────────────────────────────
    Operation(
        id="graph.messages.list",
        provider="microsoft",
        label="Outlook · list messages",
        description="Messages from the signed-in mailbox, newest first.",
        url="https://graph.microsoft.com/v1.0/me/messages",
        scopes=("Mail.Read",),
        params=(
            OperationParam(name="$top", label="Limit", type="number", default=10,
                           bindable=False),
            OperationParam(name="$search", label="Search", placeholder='"project update"'),
        ),
        # The declared bound that matters most in this file: Graph returns WHOLE
        # messages here, body included, and an automation run is stored and read by
        # people. Four identifiers is what a chain needs to decide and to fan.
        result=ResultShape(items_path="value",
                           item_fields=("id", "subject", "receivedDateTime",
                                        "webLink")),
    ),
    Operation(
        id="graph.me.get",
        provider="microsoft",
        label="Outlook · who am I",
        description="The signed-in account — the cheapest proof a grant is alive.",
        url="https://graph.microsoft.com/v1.0/me",
        scopes=("User.Read",),
        result=ResultShape(fields={"id": "id", "display_name": "displayName",
                                   "mail": "mail"}),
    ),
)

_BY_ID: dict[str, Operation] = {op.id: op for op in OPERATIONS}


def get_operation(operation_id: str) -> Optional[Operation]:
    return _BY_ID.get(operation_id or "")


def operations_for(provider_id: str) -> tuple[Operation, ...]:
    """Every operation declared for one provider, in roster order."""
    return tuple(op for op in OPERATIONS if op.provider == provider_id)


# ── the two pure helpers the dispatcher and the tests share ──────────────────────

def missing_scopes(op: Operation, granted: str) -> tuple[str, ...]:
    """Scopes this operation needs that the grant does not carry.

    ``granted`` is ``Connection.scopes`` — space-separated, read back from the provider's
    own token response. **An EMPTY string returns nothing missing**, deliberately: several
    providers return no scope list at all, and an unknown grant is not a measured absence.
    Refusing on silence would dim every row on a provider that simply does not say — the
    palette's own rule (only a measured zero dims) applied one plane over.
    """
    if not (granted or "").strip():
        return ()
    have = set(granted.split())
    return tuple(s for s in op.scopes if s not in have)


def build_request(op: Operation, params: dict) -> tuple[str, dict, dict]:
    """``(url, query, body)`` for one call — the whole of how a param reaches a provider.

    Raises :class:`ValueError` with a sentence an author can act on when a required param
    is absent or an undeclared one is supplied. Undeclared keys are REFUSED rather than
    dropped: silently discarding `{"cc": …}` would send a message the author believes was
    copied to someone, which is worse than not sending it.
    """
    declared = {p.name: p for p in op.params}
    unknown = [k for k in params if k not in declared]
    if unknown:
        raise ValueError(
            f"'{op.id}' has no input named '{unknown[0]}' — it takes "
            f"{', '.join(declared) or 'no inputs'}")

    values: dict[str, Any] = {}
    for name, spec in declared.items():
        val = params.get(name, spec.default)
        if val is None or (isinstance(val, str) and not val.strip()):
            if spec.required:
                raise ValueError(f"'{op.id}' needs '{name}' ({spec.label or name})")
            continue
        values[name] = val

    url = op.url
    for name in op.path_params:
        # `safe=""` — the encoding is the whole guarantee. A path param that could carry a
        # `/` would let a declared operation address an undeclared endpoint, which is the
        # closed set quietly opening.
        url = url.replace("{" + name + "}", quote(str(values.pop(name, "")), safe=""))

    query = {k: v for k, v in values.items() if op.method == "GET"}
    body = {} if op.method == "GET" else dict(values)
    return url, query, body


def extract(op: Operation, payload: dict) -> dict:
    """The provider's JSON as this operation's declared, published keys — and nothing else.

    Nothing undeclared is published, so a later step can only bind to what the roster
    already told its author about, and a provider that adds a field tomorrow does not
    silently widen what a chain carries.
    """
    out: dict[str, Any] = {}
    if op.result.items_path:
        items = _dig(payload, op.result.items_path)
        items = items if isinstance(items, list) else []
        out["items"] = [_item(it, op.result) for it in items]
        out["count"] = len(items)
    for key, path in op.result.fields.items():
        got = _dig(payload, path)
        out[key] = got if got is not None else ""
    return out


def _item(item: Any, shape: ResultShape) -> Any:
    """One list item as published: its declared keys, and the texts gathered for it."""
    kept = _shrink(item, shape.item_fields)
    if shape.item_text and isinstance(item, dict):
        kept = {**(kept if isinstance(kept, dict) else {}),
                **{key: "".join(_gather(item, path)).strip() for key, path in shape.item_text.items()}}
    return kept


def _gather(node: Any, path: str) -> list[str]:
    """Every string at ``path`` through ``node`` — a ``[]`` part walks each element of a list."""
    nodes = [node]
    for part in (p for p in (path or "").split(".") if p):
        each = part.endswith("[]")
        key = part[:-2] if each else part
        found: list[Any] = []
        for n in nodes:
            val = n.get(key) if isinstance(n, dict) else None
            if each:
                found.extend(val if isinstance(val, list) else [])
            elif val is not None:
                found.append(val)
        nodes = found
    return [n for n in nodes if isinstance(n, str)]


def _shrink(item: Any, keep: tuple[str, ...]) -> Any:
    """One list item, reduced to its declared keys. A non-dict item (a bare id) is
    published as-is — there is nothing to reduce and dropping it would lose the list."""
    if not keep or not isinstance(item, dict):
        return item
    return {k: item.get(k) for k in keep if k in item}


def _dig(payload: Any, path: str) -> Any:
    cur = payload
    for part in (path or "").split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur
