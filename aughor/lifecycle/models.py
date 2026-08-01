from __future__ import annotations
from pydantic import BaseModel, Field


class ProcessNode(BaseModel):
    state: str
    count: int = 0
    is_terminal: bool = False


class ProcessEdge(BaseModel):
    from_state: str
    to_state: str
    count: int = 0
    rate: float = 0.0          # count / total leaving from_state


class ProcessMap(BaseModel):
    entity_id: str
    display_name: str
    lifecycle_column: str
    nodes: list[ProcessNode] = Field(default_factory=list)
    edges: list[ProcessEdge] = Field(default_factory=list)
    total_records: int = 0
    has_transitions: bool = False  # False when no temporal column available
