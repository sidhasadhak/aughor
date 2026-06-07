"""Learned skills — inert stubs.

See aughor.memory.__init__ for why these exist. Each returns the "nothing
learned yet" value so the skills endpoints answer gracefully (empty list / 4xx)
rather than 500. Signatures match the call sites in
aughor/routers/ontology.py and aughor/ontology/store.py.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def resolve_active_schema(connection_id: str) -> str:
    """Schema key learned skills would be stored under. Inert default."""
    return "default"


def load_learned_actions(connection_id: str, schema_name: str) -> dict[str, Any]:
    """Map of learned OntologyActions by id. Inert: none learned."""
    return {}


def propose_skill_from_investigation(
    inv_id: str, table_to_entity: Optional[dict[str, str]] = None
) -> Optional[Any]:
    """Crystallize a candidate skill from a finished run. Inert: no candidate."""
    return None


def save_skill(
    connection_id: str,
    schema_name: str,
    action: Any,
    validator: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Persist a confirmed skill (read-only gated). Inert: not saved."""
    return False


def record_skill_use(connection_id: str, schema_name: str, action_id: str) -> int:
    """Increment a skill's usage_count. Inert: 0 (treated as 'not found')."""
    return 0


def delete_skill(connection_id: str, schema_name: str, action_id: str) -> bool:
    """Delete a learned skill. Inert: nothing to delete."""
    return False


def auto_crystallize(inv_id: str, connection_id: str) -> None:
    """Auto-promote an L2+ skill-worthy run into a learned skill. Inert no-op."""
    return None
