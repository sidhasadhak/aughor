"""User-defined agents — the product entity binding instructions + documents +
a connection into a reusable persona ("Gems on governed data").

Part B Phase 1 of docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md.
Flag `agents.user_defined`, default off. Slice 1 wires: pinned INSTRUCTIONS
(lead the quick-path prompt, rules_block-style), DOCUMENT scope (retrieval
restricted to the agent's bound documents — an agent with no documents sees
none), and the CONNECTION binding (the agent always answers over its data;
a conflicting explicit connection is rejected, fail-closed). Pack bindings,
schema scoping, deep-intake injection, and the builder UI are later slices.
"""
from aughor.user_agents.models import UserAgent
from aughor.user_agents.store import (
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    update_agent,
)

__all__ = [
    "UserAgent",
    "create_agent",
    "delete_agent",
    "get_agent",
    "list_agents",
    "update_agent",
]
