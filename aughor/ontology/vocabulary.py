"""Wave O1 — the vocabulary plane: synonyms, value dictionaries, and format specs.

**Synonyms did not exist as a store.** The scoping survey found the whole synonym story
living inside ``tools/schema_linker.build_connection_hints``: an expansion derived at query
time from metric names and the connection KB's title/tags, assembled inside a ``try/except``
that logs at debug. There is no record of a synonym, no source, no rank, nothing to review
and nothing a human can override. So this is construction, not a re-key — and the first
rule is that the linker must READ this store rather than keep its own parallel derivation,
or the platform ends up with two synonym dialects and Wave V's thirteen-spellings lesson
repeats on a smaller scale.

**Source rank is the whole governance story.** ``human > mined > llm_candidate``. A mined
or model-proposed synonym is a *candidate*: recorded, retrievable, and ranked below any
human entry for the same subject. J4 is not weakened — a synonym does not create or weight
an edge, it only widens what a question can match — but the rank is what keeps "the model
suggested it" from ever reading as "the business decided it".

**Value dictionaries carry a hazard the program did not name.** A dictionary of a column's
low-cardinality values is built FROM table data, so publishing one for a
clearance-restricted table leaks its contents through the linker — the exact leak G5 closed
one layer up. :func:`visible_value_dictionaries` therefore applies the G5 trim, and the
scoping doc pins it as a gate. Generation runs under a service context and never a user's,
so the dictionary content itself is not shaped by whoever happened to trigger it (Genie's
own leakage carve-out).

**Format specs are half of #189, deliberately.** Declaring that a metric is a percent with
one decimal is O1's job; *rendering* it is S2's (J11). Nothing here formats a number, and
no chart-level formatting hack should appear in between.

Deterministic and store-backed; no LLM anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from aughor.db.sqlite_util import resolve_db_path

#: Where a synonym came from, strongest first. The ORDER is the policy: a human entry
#: always outranks a mined one, and a mined one always outranks a model's proposal.
SOURCE_RANKS: tuple[str, ...] = ("human", "mined", "llm_candidate")

#: What a synonym can be attached to.
SUBJECT_KINDS: tuple[str, ...] = ("table", "column", "metric", "term")

#: Declared display formats (O1c). Small and closed: a format nobody can render is a
#: format that silently does nothing, and S2 has to implement each one.
FORMATS: tuple[str, ...] = ("number", "currency", "percent", "compact", "date", "text")

_ROOT = resolve_db_path(
    "AUGHOR_VOCABULARY_ROOT",
    Path(__file__).parent.parent.parent / "data" / "vocabulary")


def _rank_index(source: str) -> int:
    try:
        return SOURCE_RANKS.index(source)
    except ValueError:
        return len(SOURCE_RANKS)          # unknown source ranks below everything known


@dataclass(frozen=True)
class Synonym:
    """One alternative name for one subject, with where it came from."""

    connection_id: str
    subject_kind: str          # one of SUBJECT_KINDS
    subject_id: str            # the table/column/metric/term it names
    synonym: str
    source: str = "human"      # one of SOURCE_RANKS
    note: str = ""

    @property
    def rank(self) -> int:
        return _rank_index(self.source)

    def to_dict(self) -> dict:
        return {"subject_kind": self.subject_kind, "subject_id": self.subject_id,
                "synonym": self.synonym, "source": self.source, "note": self.note}


@dataclass(frozen=True)
class FormatSpec:
    """How a metric or property should be displayed (O1c — declared here, rendered in S2)."""

    display_name: str = ""
    format: str = "number"
    decimals: Optional[int] = None
    currency: str = ""
    compact: bool = False

    def to_dict(self) -> dict:
        return {"display_name": self.display_name, "format": self.format,
                "decimals": self.decimals, "currency": self.currency,
                "compact": self.compact}


@dataclass
class ValueDictionary:
    """A column's low-cardinality values — what makes "womenswear" resolve to a real value."""

    connection_id: str
    table: str
    column: str
    values: list[str] = field(default_factory=list)
    truncated: bool = False        # more values existed than the cap allows

    def to_dict(self) -> dict:
        return {"table": self.table, "column": self.column,
                "values": list(self.values), "truncated": self.truncated}


# ── storage (YAML, git-reviewable, one file per connection) ──────────────────────────

def _path(connection_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (connection_id or "_"))
    return _ROOT / f"{safe}.yaml"


def read_vocabulary(connection_id: str) -> dict:
    """The whole stored vocabulary document for a connection.

    Public because O7's interchange exports every section, and a bundle assembled from a
    private reader is a bundle that breaks the next time the reader is refactored.
    """
    return _read(connection_id)


def _read(connection_id: str) -> dict:
    p = _path(connection_id)
    if not p.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(p.read_text()) or {}
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "an unreadable vocabulary file degrades to empty rather than "
                      "failing every question on the connection",
                 counter="ontology.vocabulary_read")
        return {}


def _write(connection_id: str, data: dict) -> None:
    import yaml

    p = _path(connection_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=True, allow_unicode=True))


def add_synonym(connection_id: str, subject_kind: str, subject_id: str, synonym: str, *,
                source: str = "human", note: str = "") -> Synonym:
    """Record one synonym. Raises on an unknown kind or source rather than storing junk
    that would silently never rank."""
    if subject_kind not in SUBJECT_KINDS:
        raise ValueError(f"unknown subject kind {subject_kind!r} — known: {list(SUBJECT_KINDS)}")
    if source not in SOURCE_RANKS:
        raise ValueError(f"unknown synonym source {source!r} — known: {list(SOURCE_RANKS)}")
    term = " ".join(str(synonym or "").lower().split())
    if not term:
        raise ValueError("a synonym needs a term")

    data = _read(connection_id)
    rows = list(data.get("synonyms") or [])
    # Identity is (kind, subject, term): re-adding the same synonym from a STRONGER source
    # promotes it, which is how a human confirming a mined candidate is recorded.
    for i, r in enumerate(rows):
        if (r.get("subject_kind") == subject_kind and r.get("subject_id") == subject_id
                and r.get("synonym") == term):
            if _rank_index(source) <= _rank_index(str(r.get("source") or "")):
                rows[i] = {**r, "source": source, "note": note or r.get("note", "")}
            break
    else:
        rows.append({"subject_kind": subject_kind, "subject_id": subject_id,
                     "synonym": term, "source": source, "note": note})
    data["synonyms"] = rows
    _write(connection_id, data)
    return Synonym(connection_id, subject_kind, subject_id, term, source, note)


def synonyms_for(connection_id: str, *, subject_kind: Optional[str] = None) -> list[Synonym]:
    """Every synonym on a connection, strongest source first then alphabetical.

    The ordering is load-bearing for retrieval: a caller taking the first match must get
    the human entry when one exists, without having to know the rank rules.
    """
    rows = _read(connection_id).get("synonyms") or []
    out = [Synonym(connection_id=connection_id,
                   subject_kind=str(r.get("subject_kind") or ""),
                   subject_id=str(r.get("subject_id") or ""),
                   synonym=str(r.get("synonym") or ""),
                   source=str(r.get("source") or "human"),
                   note=str(r.get("note") or ""))
           for r in rows if r.get("synonym")]
    if subject_kind:
        out = [s for s in out if s.subject_kind == subject_kind]
    return sorted(out, key=lambda s: (s.rank, s.subject_id, s.synonym))


def synonym_expansion(connection_id: str) -> dict[str, set[str]]:
    """``term -> {subject ids}`` for the linker.

    The shape ``schema_linker`` already consumes, so adopting this store is a swap rather
    than a rewrite of the linker's matching. Strongest source wins a term outright: a human
    saying "revenue" means `gmv_eur` must not be diluted by a mined guess pointing the same
    word somewhere else.
    """
    best: dict[str, int] = {}
    out: dict[str, set[str]] = {}
    for s in synonyms_for(connection_id):          # already strongest-first
        rank = best.get(s.synonym)
        if rank is None:
            best[s.synonym] = s.rank
            out[s.synonym] = {s.subject_id}
        elif s.rank == rank:
            out[s.synonym].add(s.subject_id)
        # a weaker source for a term already claimed is ignored
    return out


def remove_synonym(connection_id: str, subject_kind: str, subject_id: str,
                   synonym: str) -> bool:
    """Drop one synonym. Returns whether anything was removed."""
    term = " ".join(str(synonym or "").lower().split())
    data = _read(connection_id)
    rows = list(data.get("synonyms") or [])
    kept = [r for r in rows
            if not (r.get("subject_kind") == subject_kind
                    and r.get("subject_id") == subject_id and r.get("synonym") == term)]
    if len(kept) == len(rows):
        return False
    data["synonyms"] = kept
    _write(connection_id, data)
    return True


# ── format specs (O1c) ──────────────────────────────────────────────────────────────

def set_format(connection_id: str, subject_id: str, spec: FormatSpec) -> FormatSpec:
    if spec.format not in FORMATS:
        raise ValueError(f"unknown format {spec.format!r} — known: {list(FORMATS)}")
    data = _read(connection_id)
    formats = dict(data.get("formats") or {})
    formats[subject_id] = spec.to_dict()
    data["formats"] = formats
    _write(connection_id, data)
    return spec


def format_for(connection_id: str, subject_id: str) -> Optional[FormatSpec]:
    raw = (_read(connection_id).get("formats") or {}).get(subject_id)
    if not isinstance(raw, dict):
        return None
    return FormatSpec(display_name=str(raw.get("display_name") or ""),
                      format=str(raw.get("format") or "number"),
                      decimals=raw.get("decimals"),
                      currency=str(raw.get("currency") or ""),
                      compact=bool(raw.get("compact")))


# ── value dictionaries (O1b) ────────────────────────────────────────────────────────

#: Values kept per column. A dictionary exists to resolve a phrase to a real value, and a
#: list long enough to need scrolling is a list nobody reads and a prompt nobody affords.
MAX_VALUES = 50


def set_value_dictionary(connection_id: str, table: str, column: str,
                         values: Iterable[str]) -> ValueDictionary:
    """Record a column's value list. Truncation is DECLARED, never silent."""
    vals = [str(v) for v in values if str(v).strip()]
    truncated = len(vals) > MAX_VALUES
    vd = ValueDictionary(connection_id=connection_id, table=table, column=column,
                         values=vals[:MAX_VALUES], truncated=truncated)
    data = _read(connection_id)
    dicts = list(data.get("value_dictionaries") or [])
    dicts = [d for d in dicts if not (d.get("table") == table and d.get("column") == column)]
    dicts.append(vd.to_dict())
    data["value_dictionaries"] = dicts
    _write(connection_id, data)
    return vd


def value_dictionaries(connection_id: str) -> list[ValueDictionary]:
    """Every recorded dictionary — UNTRIMMED. Callers that put these in front of a user
    must use :func:`visible_value_dictionaries` instead."""
    return [ValueDictionary(connection_id=connection_id,
                            table=str(d.get("table") or ""),
                            column=str(d.get("column") or ""),
                            values=[str(v) for v in (d.get("values") or [])],
                            truncated=bool(d.get("truncated")))
            for d in (_read(connection_id).get("value_dictionaries") or [])]


def visible_value_dictionaries(
    connection_id: str, *, schema_name: str = "",
) -> tuple[list[ValueDictionary], str]:
    """The dictionaries the CALLER may see, plus the notice for any withheld.

    The hazard the program did not name: a value dictionary is built FROM table data, so
    surfacing one for a clearance-restricted table leaks its contents through the linker —
    precisely what G5 closed one layer up. New retrieval that skips the trim silently
    re-opens it, which is why the scoping doc pins this as a gate.
    """
    from aughor.govern import tags as _tags

    dicts = value_dictionaries(connection_id)
    if not _tags.enabled() or not dicts:
        return dicts, ""

    from aughor.govern.retrieval_trim import (
        caller_clearances,
        partition,
        securable_for_table,
    )

    result = partition(
        dicts,
        lambda d: securable_for_table(connection_id, schema_name, d.table),
        caller_clearances())
    return result.kept, result.notice()
