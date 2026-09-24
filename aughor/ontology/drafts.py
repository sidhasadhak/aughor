"""ON-7b — the explorer's draft record: every proposal an explorer made on one scope, what the data said about it, what
was written, and every run (ROADMAP §3.15, the second movement).

The declarations themselves live where every declaration lives — the overrides tree, with `origin: model` and their
provenance — so the platform reads a proposal exactly as it reads what a person declared. This record keeps what the
overrides tree cannot: what the model SAID (its reason, its spelling), what the measurement refused and why, which run
said it, and — because withdrawing a declaration deletes it — the memory that it was once written, so the next run can
tell a proposal a person withdrew from one never made, and does not propose it again.

A proposal's tier (proposed · confirmed · released · withdrawn) is never stored here. It is read from the served graph
every time (`aughor.ontology.explorer.proposal_tier`), so a Confirm or a Withdraw through any door shows at once with
no second write to keep in step.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from aughor.db.sqlite_util import resolve_db_path

logger = logging.getLogger(__name__)

#: `data/ontology_drafts`, or `AUGHOR_ONTOLOGY_DRAFTS_DIR` — isolated in tests/conftest.py (and by `dump_openapi`) beside
#: the overrides tree it writes into, because an explore door test would otherwise rewrite a live draft.
_ROOT = resolve_db_path("AUGHOR_ONTOLOGY_DRAFTS_DIR",
                        Path(__file__).parent.parent.parent / "data" / "ontology_drafts")
#: Runs one record keeps; the proposals are kept whole.
MAX_RUNS = 20


def drafts_root() -> Path:
    """The draft records' root (`data/ontology_drafts`)."""
    return _ROOT


class DraftProposal(BaseModel):
    """One proposal, keyed by its SUBSTANCE (`explorer.part_key`, `link_key`, `entity_key`) — so the model spelling a
    binding differently on a second run is the same proposal, not a new one."""
    key: str
    kind: Literal["entity", "part", "link", "link_name", "process", "rule"]
    #: What the data said when it was proposed: `proposed` (measured, and written through a door) or `refused`.
    status: Literal["proposed", "refused"]
    sentence: str
    note: str = ""
    #: Where the declaration lives: {entity} · {entity, binding, table, part} · {relationship} · {process, entity} ·
    #: {rule, entity}.
    target: dict = Field(default_factory=dict)
    #: The spec the door was sent.
    spec: dict = Field(default_factory=dict)
    #: The proposal as the model said it, its reason included.
    said: dict = Field(default_factory=dict)
    #: What the measurement counted before anything was written.
    measured: dict = Field(default_factory=dict)
    provenance: str = ""
    first_run: str = ""
    last_run: str = ""


class DraftRun(BaseModel):
    """One explorer run: the binding that answered, and what became of what it said."""
    id: str
    at: str
    backend: str = ""
    model: str = ""
    #: True when a fallback link answered instead of the model that was asked — the provenance names the one that did.
    fallback: bool = False
    version: int = 0
    provenance: str = ""
    #: The run's trace — its model call and every event it wrote, replayable from the session log.
    trace_id: str = ""
    catalogue_chars: int = 0
    #: How many entities, parts and links the model proposed.
    said: dict = Field(default_factory=dict)
    written: int = 0
    refused: int = 0
    already: int = 0
    withdrawn: int = 0
    #: Why applying the run's proposals stopped part-way, when it did (PENDING item 20): the run is recorded anyway,
    #: so the model call it paid for is not paid again by every restart that finds no run here.
    error: str = ""


class DraftUnreadable(RuntimeError):
    """The scope's record exists and does not parse. It holds what people WITHDREW, so nothing may write over it and
    no explorer may run on it until a person repairs or removes it — an empty record in its place would propose
    every withdrawal again, and saving that record would erase them for good (PENDING item 20)."""


class OntologyDraft(BaseModel):
    connection_id: str
    schema_name: str
    runs: list[DraftRun] = Field(default_factory=list)
    proposals: dict[str, DraftProposal] = Field(default_factory=dict)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.=-]", "_", s or "default")


def _path(connection_id: str, schema_name: str) -> Path:
    return _ROOT / _safe(connection_id) / f"{_safe(schema_name)}.yaml"


def draft_unreadable(connection_id: str, schema_name: str) -> str:
    """Why the scope's record cannot be read, or ``""`` when it reads (or does not exist yet)."""
    path = _path(connection_id, schema_name)
    if not path.exists():
        return ""
    try:
        OntologyDraft.model_validate(yaml.safe_load(path.read_text()) or {})
    except Exception as exc:  # noqa: BLE001 — any failure to read is the answer
        return f"{path} does not parse ({type(exc).__name__}: {str(exc)[:200]})"
    return ""


def load_draft(connection_id: str, schema_name: str, *, strict: bool = False) -> OntologyDraft:
    """The scope's record, or an empty one when there is none. A record that no longer parses is logged and read as
    empty for SHOWING (``strict=False``); a caller about to act on it — the explorer — passes ``strict=True`` and
    gets :class:`DraftUnreadable` instead, because what the empty record forgot is which proposals a person
    withdrew (PENDING item 20)."""
    path = _path(connection_id, schema_name)
    if path.exists():
        try:
            return OntologyDraft.model_validate(yaml.safe_load(path.read_text()) or {})
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise DraftUnreadable(draft_unreadable(connection_id, schema_name)) from exc
            logger.warning("ontology draft %s could not be read (%s) — showing an empty record", path, exc)
    return OntologyDraft(connection_id=connection_id, schema_name=schema_name)


def save_draft(draft: OntologyDraft) -> None:
    """Write the record, atomically. Raises: the record is what keeps a second run from writing twice and from
    proposing what a person withdrew, so a failed save must be reported, not swallowed. It never writes over a record
    that does not parse — that record still holds the withdrawals an empty one would erase (:class:`DraftUnreadable`)."""
    unreadable = draft_unreadable(draft.connection_id, draft.schema_name)
    if unreadable:
        raise DraftUnreadable(unreadable)
    path = _path(draft.connection_id, draft.schema_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(draft.model_dump(), sort_keys=False, allow_unicode=True))
    tmp.replace(path)
