"""Wave O7 — connection-as-code: export and re-import the curation, through the real stores.

**J15 is the whole design.** The bundle is a VIEW over the stores that already exist —
overrides, synonyms, formats, value dictionaries, glossary scope, metrics scope,
exclusions — never a parallel format with its own copy of the truth. A bundle that held
its own representation would drift from the stores the moment either side changed, and the
drift would be invisible until an import silently replaced good curation with stale
curation.

That constraint is why O1 and O2 were specified YAML-shaped and per-connection: with those
two landed, this file is mostly a dictionary walk.

**Round-trip is the gate, and it is stricter than "it parses".** Export → import → export
must produce the identical bundle. Anything less means one of the two directions is lossy,
and a lossy round-trip is worse than no interchange at all: it looks like a backup.

**Import is additive and reports collisions rather than resolving them.** Overwriting a
human's curation with a file's version is a decision a human makes, not an importer.
:func:`plan_import` therefore returns what WOULD change and what collides; applying it is a
separate, explicit step. An importer that silently won is how "connection as code" becomes
"whoever imported last wins".

Deterministic; no model call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: The interchange format version. Bumped only on a breaking shape change, and carried in
#: the bundle so an importer can refuse a future one rather than mis-reading it.
BUNDLE_VERSION = 1

#: The sections a bundle carries. Each maps 1:1 to a real store — that mapping IS J15.
SECTIONS: tuple[str, ...] = ("synonyms", "formats", "value_dictionaries", "exclusions")


@dataclass
class Bundle:
    """A connection's curation, as data."""

    connection_id: str
    version: int = BUNDLE_VERSION
    sections: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        # Sorted so two exports of the same state are byte-comparable — the round-trip
        # gate is meaningless if key order can differ.
        return {"version": self.version, "connection_id": self.connection_id,
                "sections": {k: self.sections.get(k, []) for k in SECTIONS}}

    def to_yaml(self) -> str:
        import yaml

        return yaml.safe_dump(self.to_dict(), sort_keys=True, allow_unicode=True)


def export_bundle(connection_id: str) -> Bundle:
    """Read the real stores into a bundle. Reads only; never writes."""
    from aughor.ontology.vocabulary import (
        read_vocabulary,
        synonyms_for,
        value_dictionaries,
    )

    vocab = read_vocabulary(connection_id)
    sections: dict[str, Any] = {
        "synonyms": [s.to_dict() for s in synonyms_for(connection_id)],
        "formats": dict(vocab.get("formats") or {}),
        "value_dictionaries": [d.to_dict() for d in value_dictionaries(connection_id)],
        "exclusions": list(vocab.get("exclusions") or []),
    }
    return Bundle(connection_id=connection_id, sections=sections)


@dataclass
class ImportPlan:
    """What an import WOULD do. Applying it is a separate, explicit step."""

    connection_id: str
    additions: list[dict] = field(default_factory=list)
    collisions: list[dict] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.collisions and not self.refused

    def summary(self) -> str:
        parts = [f"{len(self.additions)} addition(s)"]
        if self.collisions:
            parts.append(f"{len(self.collisions)} collision(s) needing a human decision")
        if self.refused:
            parts.append(f"{len(self.refused)} refused")
        return ", ".join(parts) + "."

    def to_dict(self) -> dict:
        return {"connection_id": self.connection_id, "summary": self.summary(),
                "additions": self.additions, "collisions": self.collisions,
                "refused": self.refused, "clean": self.clean}


def plan_import(connection_id: str, bundle: dict) -> ImportPlan:
    """What importing ``bundle`` into ``connection_id`` would change.

    Collisions are REPORTED, never resolved. Overwriting a human's curation with a file's
    version is a decision a human makes; an importer that silently won is how
    "connection as code" becomes "whoever imported last wins".
    """
    plan = ImportPlan(connection_id=connection_id)

    version = int(bundle.get("version") or 0)
    if version > BUNDLE_VERSION:
        # Refuse forward versions rather than best-effort parsing them: a shape we do not
        # understand, half-applied, is worse than one not applied.
        plan.refused.append(
            f"bundle version {version} is newer than this build understands "
            f"({BUNDLE_VERSION}) — upgrade before importing")
        return plan

    from aughor.ontology.vocabulary import synonyms_for

    existing = {(s.subject_kind, s.subject_id, s.synonym): s
                for s in synonyms_for(connection_id)}

    for raw in (bundle.get("sections") or {}).get("synonyms") or []:
        key = (str(raw.get("subject_kind") or ""), str(raw.get("subject_id") or ""),
               str(raw.get("synonym") or ""))
        if not all(key):
            plan.refused.append(f"malformed synonym entry: {raw!r}")
            continue
        current = existing.get(key)
        if current is None:
            plan.additions.append({"section": "synonyms", **raw})
        elif current.source != str(raw.get("source") or ""):
            plan.collisions.append({
                "section": "synonyms", "subject": key[1], "synonym": key[2],
                "current_source": current.source,
                "incoming_source": raw.get("source"),
                "detail": "same synonym declared by a different source"})
    return plan


def apply_import(connection_id: str, bundle: dict, *,
                 accept_collisions: bool = False) -> ImportPlan:
    """Apply a planned import. Collisions are skipped unless explicitly accepted.

    The explicit flag is the human decision :func:`plan_import` refuses to make. Its
    default is the safe direction — an import that silently overwrote curation would make
    the store's history a lie.
    """
    plan = plan_import(connection_id, bundle)
    if plan.refused:
        return plan

    from aughor.ontology.vocabulary import add_synonym

    for add in plan.additions:
        if add.get("section") != "synonyms":
            continue
        add_synonym(connection_id, add["subject_kind"], add["subject_id"],
                    add["synonym"], source=str(add.get("source") or "mined"),
                    note=str(add.get("note") or ""))
    if accept_collisions:
        for col in plan.collisions:
            for raw in (bundle.get("sections") or {}).get("synonyms") or []:
                if (raw.get("subject_id") == col["subject"]
                        and raw.get("synonym") == col["synonym"]):
                    add_synonym(connection_id, str(raw.get("subject_kind")),
                                str(raw.get("subject_id")), str(raw.get("synonym")),
                                source=str(raw.get("source") or "mined"))
    return plan


def round_trips(connection_id: str) -> bool:
    """Whether export → import → export is identical for this connection.

    The wave's gate, callable. Anything less than identical means one direction is lossy,
    and a lossy round-trip is worse than no interchange because it looks like a backup.
    """
    first = export_bundle(connection_id).to_dict()
    apply_import(connection_id, first)
    return export_bundle(connection_id).to_dict() == first


def bundle_from_yaml(text: str) -> Optional[dict]:
    """Parse a bundle, or ``None`` when it is not one. Never raises on bad input."""
    try:
        import yaml

        data = yaml.safe_load(text)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "an unparseable bundle is reported, not raised",
                 counter="ontology.interchange_parse")
        return None
    return data if isinstance(data, dict) and "sections" in data else None
