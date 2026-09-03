"""VA-9d · the MCP consumer — what a server this deployment may talk to looks like.

`aughor/mcp/` is our SERVER: the eighteen tools this version exposes, plus DS-14's
automations, plus an HTTP client to our own REST API. This package is the other
direction, and it is deliberately a sibling rather than a submodule of that one — a
package named `mcp` that meant both "what we serve" and "whom we call" would make every
import a question.

**The allowlist IS the posture.** VA-9's own risk note calls this the largest new attack
surface in the arc, and the answer is not a flag. `FLAG_DEFAULT` has been empty since the
flag endgame, and a switch somebody has to remember to leave closed is the control this
repo already replaced once (the prompt-capture window). Instead: **an empty registry is the
off state.** A fresh clone can reach exactly nothing, not because a default says so but
because there is nowhere to go, and the only way to add a destination is a human writing
one down. That also makes the trust boundary legible — the spec says a client "should never
make tool use decisions based on ToolAnnotations received from untrusted servers", and
what makes a server trusted HERE is that a person put it in this table.

**Read-only first, per the posture decided 2026-09-01.** The protocol hands us hints, and
their own defaults do the work: `readOnlyHint` documents *"Default: false"* and
`destructiveHint` *"Default: true"*. So a tool that declares nothing is, by the protocol's
own reading, mutating and potentially destructive — which means the safe classification is
not a judgement call we are making, it is the specification's. An unannotated tool is
LISTED and REFUSED exactly like one that declares itself mutating: listed, because a roster
that hides what a server offers is the catalogue-that-lies failure DS-10 exists to end.

**The write slice settles what the read-only slice deferred** (decided 2026-09-02, §6.6).
*Whose declaration of "read-only" is believed:* nobody's but ours. A server's hints are
DISPLAYED and ADVISORY; what authorizes a mutating call is an explicit per-tool grant a
human wrote down (`McpToolGrant`). Note what this does to `classify()` — it does not change
it. Its restrictive defaults now decide what **needs a grant**, never what **may run**. The
allowlist says WHERE we may reach; the grant says WHAT we may do there, and neither answer
is borrowed from the counterparty.

*What a server that CHANGES a declaration after registration may do:* a grant pins the
declaration it was given for, and `grant_verdict` refuses when the roster no longer matches
it. Scoped to the tool that moved — a server is not quarantined for re-versioning one label,
because a control that fires on every legitimate change is one people learn to click
through — and fail-closed, because a silently relabelled tool is exactly the attack the
advisory reading exists to blunt.
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from aughor.util.time import now_iso_z

#: Encrypted at rest, dropped (never masked) on the way out — `Connection`'s rule, for its
#: reason: a mask still confirms a secret's length-class and invites a client to store the
#: field, and nothing above the store has a use for even the shape of these.
SERVER_SECRET_FIELDS = ("auth_header",)


def _new_id() -> str:
    return f"mcps_{uuid.uuid4().hex[:12]}"


class McpServer(BaseModel):
    """One MCP server a human has written down as reachable from this deployment.

    Two transports, and the split is the security boundary rather than a convenience:

    * ``stdio`` — we SPAWN a process. `command` plus `args`; there is no URL, and the
      process runs with this deployment's own privileges. This is the more dangerous of
      the two and the form says so.
    * ``http`` — we CONNECT to a URL (streamable HTTP, falling back to SSE). No process is
      created; the blast radius is the network.
    """

    id: str = Field(default_factory=_new_id)
    #: What a person calls it on the palette. Not an id — renaming must not orphan a step.
    name: str = ""
    transport: Literal["stdio", "http"] = "http"

    #: stdio only. The executable and its arguments, held APART rather than as one string:
    #: a single command line invites a shell to split it, and a shell is how an argument
    #: becomes a second command. Nothing here is ever passed to a shell.
    command: str = ""
    args: list[str] = Field(default_factory=list)
    #: stdio only. Extra environment for the child. Not secret-encrypted as a whole because
    #: it is a dict and the store's field-level encryption is per named field; a server
    #: needing a token should carry it in `auth_header`.
    env: dict = Field(default_factory=dict)

    #: http only. The full endpoint; scheme and host are the operator's, not a param's.
    url: str = ""
    #: http only. A complete `Authorization` header value, encrypted at rest. One opaque
    #: field rather than a credential type + value: this consumer does not implement any
    #: auth scheme, it forwards what the operator was given, so pretending to model
    #: "bearer vs basic" would be a taxonomy with no behaviour behind it.
    auth_header: str = ""

    #: A server present but switched off. Distinct from deleted, which forgets the roster
    #: and any step that named it; distinct from unreachable, which is a health verdict
    #: and not a human's intent.
    enabled: bool = True

    created_at: str = Field(default_factory=now_iso_z)
    updated_at: str = Field(default_factory=now_iso_z)

    @model_validator(mode="after")
    def _transport_fields_must_match(self) -> "McpServer":
        """Reject at parse, never at connect (K1). A server row missing the one field its
        transport needs would sit in the table looking reachable and fail on the first
        call — and a discovery failure reads as "their server is down", which sends the
        reader to debug somebody else's machine."""
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("a stdio server needs a `command` to run")
            if self.url:
                raise ValueError("a stdio server has no `url` — it is a process, not an address")
        else:
            if not self.url:
                raise ValueError("an http server needs a `url`")
            if self.command:
                raise ValueError("an http server has no `command` — it is an address, not a process")
        return self

    def to_safe_dict(self) -> dict:
        d = self.model_dump()
        for f in SERVER_SECRET_FIELDS:
            d.pop(f, None)
        d["has_auth"] = bool(getattr(self, "auth_header", ""))
        return d


# ── what a discovered tool is allowed to do ──────────────────────────────────────

#: The server says it does not modify anything, so we may call it.
CALLABLE = "callable"
#: The server says it mutates — or says nothing, which the protocol defines as the same
#: thing. Listed on the roster, refused at the door.
REFUSED_MUTATING = "refused_mutating"

#: The sentence a refused tool carries. One string, because the roster, the palette and the
#: call door must all give the reader the same reason — three wordings of one refusal is
#: how a reader learns the product has three opinions about it.
#: Both sentences end the same way, and that ending is the write slice. They used to say
#: writes "arrive in a later slice" — a promise that came true, and a sentence left
#: un-updated after the thing it deferred has shipped is how a working feature stays
#: invisible to the person the refusal is talking to.
_GRANT_INVITATION = (
    "Aughor calls it only if a person grants this tool by name, and a grant covers the "
    "declaration it was given for."
)
REFUSAL_UNDECLARED = (
    "This server does not declare the tool as read-only, and the protocol reads a missing "
    "declaration as 'may modify'. " + _GRANT_INVITATION
)
REFUSAL_MUTATING = (
    "This server declares the tool as modifying. " + _GRANT_INVITATION
)


class McpTool(BaseModel):
    """One tool discovered on an allowlisted server, as WE classify it.

    A snapshot of somebody else's system, and stored as one on purpose. DS-10's law —
    vocabulary is served, never mirrored — is about not copying OUR OWN contract into a
    client where it rots; a remote roster is genuinely remote state, and the alternative
    (a `tools/list` round trip, or a spawned subprocess, on every palette render) is not a
    thing a canvas can afford. So it is cached WITH the time it was read, and every
    surface shows that time rather than implying the list is live.
    """

    server_id: str = ""
    name: str = ""
    title: str = ""
    description: str = ""
    #: The tool's JSON Schema, verbatim from the server. Rendered as ports, never executed.
    input_schema: dict = Field(default_factory=dict)

    #: `callable` | `refused_mutating` — OUR verdict, not the server's word.
    disposition: str = REFUSED_MUTATING
    #: Why, in the words above. Empty when callable.
    reason: str = ""
    #: What the server actually said, kept raw so a reader can check our verdict against
    #: it and so a later slice can revisit the classification without re-discovering.
    read_only_hint: Optional[bool] = None
    destructive_hint: Optional[bool] = None

    discovered_at: str = Field(default_factory=now_iso_z)


def classify(read_only: Optional[bool], destructive: Optional[bool]) -> tuple[str, str]:
    """Our disposition for one tool, from the server's hints. Returns ``(disposition, reason)``.

    The whole of the read-only-first posture, in one function, so there is exactly one
    place that decides and every surface quotes it.

    The protocol's own defaults are what make the absent case safe rather than arbitrary:
    `readOnlyHint` is documented *"Default: false"* and `destructiveHint` *"Default: true"*.
    A server that says nothing has therefore not failed to answer — it has answered "may
    modify, possibly destructively", and we hold it to that.
    """
    if read_only is True:
        # `destructiveHint` is documented as meaningful ONLY when readOnlyHint is false, so
        # a server that sets both is contradicting itself. We take the restrictive reading:
        # a tool cannot be read-only and destructive, and guessing which half was meant is
        # how a refusal turns into a write.
        if destructive is True:
            return REFUSED_MUTATING, (
                "This server declares the tool both read-only and destructive. Aughor takes "
                "the restrictive reading of a contradiction rather than guessing which half "
                "was meant.")
        return CALLABLE, ""
    if read_only is False:
        return REFUSED_MUTATING, REFUSAL_MUTATING
    return REFUSED_MUTATING, REFUSAL_UNDECLARED


# ── the human's ratification, and what makes it go stale ─────────────────────────

#: No human has ratified this tool. The normal state, and the off state: a mutating tool
#: with no grant is refused exactly as it was before the write slice existed.
GRANT_NONE = "none"
#: Ratified, and the declaration still matches the one that was ratified.
GRANT_ACTIVE = "active"
#: Ratified, but the server has since changed what the tool declares. Refused until a human
#: looks again — the grant is not silently re-interpreted against a declaration nobody read.
GRANT_STALE = "stale"


class McpToolGrant(BaseModel):
    """One human's ratification that one mutating tool on one server may be called.

    **Why this is not `user_agents.tool_grants`.** That column is a different plane wearing
    a similar word: its subject is an AGENT, its object is an ontology action id validated
    against a connection's declared actions, and its verb is PROPOSE — it grants the right
    to suggest, never to act. This grant's subject is the deployment, its object is a
    ``(server, tool)`` pair on somebody else's machine, and its verb is CALL. Putting an MCP
    tool name into that column would fail its own validator and conflate two planes that
    happen to share a noun.

    **The pinned declaration is the whole point.** A grant records what the server was
    saying about the tool at the moment a human said yes. Without it "the declaration
    changed" is not a question this code can ask, and the ratification would silently carry
    over to a tool that now claims something else.
    """

    server_id: str = ""
    tool_name: str = ""

    #: The declaration AS RATIFIED — not the current one. Compared against the roster on
    #: every call; a difference is `GRANT_STALE`.
    read_only_hint: Optional[bool] = None
    destructive_hint: Optional[bool] = None

    #: Who said yes and when. A grant with no author is one nobody can be asked about.
    granted_by: str = ""
    granted_at: str = Field(default_factory=now_iso_z)
    #: Optional: why this write is acceptable. Read back on the roster, so the next person
    #: to look inherits the reasoning rather than only the permission.
    note: str = ""

    @property
    def key(self) -> str:
        return grant_key(self.server_id, self.tool_name)


def grant_key(server_id: str, tool_name: str) -> str:
    """The id a grant is stored under. One tool on one server, never a wildcard.

    ``*`` is not accepted anywhere on this surface, for the reason `_validate_agent_grants`
    already gives one plane over: a grant names a tool, never a roster, because a blanket
    grant is what per-target ratification exists to avoid. A server's whole roster is
    granted by granting each tool, which is meant to be tedious in proportion to its reach.
    """
    return f"{server_id}::{tool_name}"


def grant_verdict(tool: McpTool, grant: Optional[McpToolGrant]) -> tuple[str, str]:
    """Does this grant still authorize this tool? Returns ``(state, reason)``.

    The single place staleness is decided, for `classify()`'s reason: the door, the roster
    and the API must give one answer, and three readings of one grant is how a reader learns
    the product has three opinions about their permissions.

    **Only the ANNOTATIONS are compared.** A tool's title and description change for
    cosmetic reasons and revoking on those would fire constantly — and a control that fires
    on every legitimate change is one people learn to click through. The annotations are the
    security claim: a human who ratified "mutating, but not destructive" has not ratified
    the same tool once it declares itself destructive, and that is exactly the transition
    this catches. An `input_schema` change is surfaced on the roster (`schema_changed`)
    rather than revoking, because we supply a granted tool's arguments ourselves — a changed
    schema breaks our call rather than widening theirs.
    """
    if grant is None:
        return GRANT_NONE, ""
    if (grant.read_only_hint == tool.read_only_hint
            and grant.destructive_hint == tool.destructive_hint):
        return GRANT_ACTIVE, ""
    return GRANT_STALE, (
        f"'{tool.name}' was granted when this server declared it "
        f"{_declaration_phrase(grant.read_only_hint, grant.destructive_hint)}, and it now "
        f"declares it {_declaration_phrase(tool.read_only_hint, tool.destructive_hint)}. "
        f"The grant covered the first declaration, not this one, so it no longer applies. "
        f"Review the tool and grant it again if the change is expected.")


def _declaration_phrase(read_only: Optional[bool], destructive: Optional[bool]) -> str:
    """A server's hints as a sentence fragment, for the staleness message.

    Spelled out rather than printed as ``readOnlyHint=None``, because the person reading
    this is being asked to re-ratify a permission and "nothing" is a claim with meaning
    here — the protocol reads silence as "may modify, possibly destructively", and a reader
    who does not know that cannot judge the change they are being shown.
    """
    if read_only is True:
        return "read-only" + (", and destructive" if destructive is True else "")
    if read_only is False:
        return "modifying" + (", and destructive" if destructive is True
                              else ", and not destructive" if destructive is False
                              else "")
    return "nothing (which the protocol reads as 'may modify, possibly destructively')"


def service_name(server: McpServer) -> str:
    """The counterparty name on the span, the cap and the audit line.

    ``mcp:<server id>``, never the display name: `external_call`'s `service` is what a usage
    cap is written against and what an audit line is read back by, and a name a person can
    rename would silently detach both. `Operation.gov_action` states the same rule one plane
    over — two spellings would mean an allowlist entry that permits a name nothing checks,
    which looks exactly like a gate that is working.

    Lives HERE rather than in `discover`, because both `discover` and `call` need it: a
    helper two modules share is not either one's private detail, and reaching across for an
    underscore-prefixed name is how a module's internals become somebody else's contract.
    """
    return f"mcp:{server.id}"
