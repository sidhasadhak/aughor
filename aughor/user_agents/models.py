"""The UserAgent entity — dynamic, user-created rows (contrast: the static
built-in fleet charters in aughor/kernel/agents.py, which govern the PLATFORM's
own agent kinds; a UserAgent is a user's persona OVER the platform)."""
from __future__ import annotations

from pydantic import BaseModel, Field

NAME_MAX = 120
INSTRUCTIONS_MAX = 8000


class UserAgent(BaseModel):
    id: str
    name: str
    instructions: str = ""
    connection_id: str = ""          # "" = unbound (answers on the ask's connection)
    schema_scope: str = ""           # "" = all schemas; else the agent answers in this schema
    doc_ids: list[str] = Field(default_factory=list)  # bound documents (knowledge registry ids)
    # Bound Domain Expertise Packs: a preference that RESTRICTS pack selection to
    # these when the agent runs — never a deploy-gate bypass (a pack still only
    # steers where a pinned, human-confirmed binding exists). [] = no restriction.
    pack_ids: list[str] = Field(default_factory=list)
    owner: str = ""                  # org/user identity when identity is enforced
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
