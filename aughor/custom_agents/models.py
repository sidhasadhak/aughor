"""The UserAgent entity — dynamic, user-created rows (contrast: the static
built-in fleet charters in aughor/kernel/agents.py, which govern the PLATFORM's
own agent kinds; a UserAgent is a user's persona OVER the platform)."""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field, computed_field

NAME_MAX = 120
INSTRUCTIONS_MAX = 8000

# The fields that decide HOW the agent answers — its governing configuration (Wave H6).
# `name` is a label and `enabled` is an on/off switch: neither changes a single token of
# the prompt or a single document retrieved, so neither mints a revision. Everything here
# does, which is exactly why the pass chip has to name which of these it measured.
GOVERNING_FIELDS = ("instructions", "connection_id", "schema_scope", "doc_ids", "pack_ids",
                    # VA-9c — which actions an agent may propose changes what it can DO,
                    # so it is governing configuration: an eval chip earned before a grant
                    # was added was earned by a different agent.
                    "tool_grants")

# What `eval_basis` can say. The four states exist because "no chip", "a chip from before
# we tracked this" and "a chip earned by a configuration that no longer exists" are three
# different things, and only one of them means "this agent is measured".
EVAL_NONE = "none"          # never evaluated
EVAL_CURRENT = "current"    # earned by the configuration running right now
EVAL_STALE = "stale"        # earned by a configuration since edited — the number is about a different agent
EVAL_UNKNOWN = "unknown"    # a chip predating revision tracking: cannot be shown current OR stale


class UserAgent(BaseModel):
    id: str
    name: str
    instructions: str = ""
    #: VA-2 — the SHORT routing line a supervisor reads when choosing a delegate.
    #: Deliberately separate from `instructions`: the roster block lists every
    #: candidate agent, so putting full instructions there is how a supervisor
    #: prompt silently becomes mostly other agents' prose (measured once at 65%).
    purpose: str = ""
    connection_id: str = ""          # "" = unbound (answers on the ask's connection)
    schema_scope: str = ""           # "" = all schemas; else the agent answers in this schema
    doc_ids: list[str] = Field(default_factory=list)  # bound documents (knowledge registry ids)
    # Bound Domain Expertise Packs: a preference that RESTRICTS pack selection to
    # these when the agent runs — never a deploy-gate bypass (a pack still only
    # steers where a pinned, human-confirmed binding exists). [] = no restriction.
    pack_ids: list[str] = Field(default_factory=list)
    #: VA-9c — the declared actions this agent may PROPOSE, by id. [] = none, which is
    #: every agent written before this field and is read-only behaviour byte-for-byte.
    #:
    #: **A grant is permission to PROPOSE, never permission to EXECUTE.** A proposal still
    #: lands in the resolve-once inbox and waits for a human accept (or a target-bound
    #: standing grant, which is minted separately per value). Conflating the two would
    #: turn "this agent may suggest a refund" into "this agent may issue refunds", which
    #: is the entire distinction the approvals plane exists to hold.
    #:
    #: NAMED actions, never a whole connection: VA-9's own rule is that an agent gets
    #: named tools, not the server. A wildcard here would re-create the blanket grant
    #: that target-bound standing grants were built to avoid.
    tool_grants: list[str] = Field(default_factory=list)
    owner: str = ""                  # org/user identity when identity is enforced
    enabled: bool = True
    # Latest golden-suite evaluation ({passed, total, at, per_question, config_rev}); None =
    # never evaluated. Written by quality.evaluate_agent, shown as the pass chip.
    last_eval: dict | None = None
    created_at: str = ""
    updated_at: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def config_rev(self) -> str:
        """A stable fingerprint of this agent's governing configuration.

        Derived, never stored: two agents configured identically have the same rev, and an
        agent edited and edited back returns to the rev it had. That is the point — the
        question a pass chip has to answer is "is this the configuration I measured?", not
        "how many times has someone pressed save?".

        Lists are sorted before hashing, so reordering bound documents is not a new
        configuration; it is the same agent with the same behaviour.
        """
        canonical = {
            "instructions": self.instructions,
            "connection_id": self.connection_id,
            "schema_scope": self.schema_scope,
            "doc_ids": sorted(self.doc_ids),
            "pack_ids": sorted(self.pack_ids),
            # VA-9c — sorted like the other lists: reordering grants is not a new
            # configuration, but ADDING one is. `config_rev` is what a pass chip compares
            # against, and an agent that gained the power to propose a refund is not the
            # agent that was measured.
            "tool_grants": sorted(self.tool_grants),
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def eval_basis(self) -> str:
        """Whether the pass chip is about the agent as it is configured NOW.

        Before H6 the chip survived any edit: an agent whose instructions had been inverted
        and whose document scope had been emptied still displayed its old `passed 5/5`. The
        number was real once — it was simply about a different agent. So the chip is never
        deleted on edit (that would destroy real evidence); it is LABELLED, and the label is
        what the UI must render alongside the number.
        """
        if not self.last_eval:
            return EVAL_NONE
        measured = str((self.last_eval or {}).get("config_rev") or "")
        if not measured:
            return EVAL_UNKNOWN
        return EVAL_CURRENT if measured == self.config_rev else EVAL_STALE
