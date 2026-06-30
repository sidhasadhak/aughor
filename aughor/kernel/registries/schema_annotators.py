"""Schema-annotator registry — invert the schema-enrichment "god file".

The platform renders a connection's **raw** schema (``db.schema_render.render_raw_schema``)
and then runs registered annotators over it. The AGENT registers annotators that layer
its intelligence on top — glossary + join hints + the metrics catalog (the
``enrichment`` annotator), value profiles + the ontology (the ``intelligence``
annotator), and the exploration findings (the ``exploration`` annotator).

Two phases, applied in registration order:
  • **fast**  — the hot ``get_schema()`` path: enrichment + exploration (no DB profiling,
    no LLM).
  • **heavy** — the background ``build_intelligence()`` path: enrichment + intelligence
    (profiles + ontology) + exploration.

An annotator's ``phase`` may be ``"fast"``, ``"heavy"`` or ``"all"`` (runs in both).
With **no** annotators registered, ``run_annotators`` returns the raw schema unchanged —
the platform renders schemas with zero agent involvement, which is the plug-and-play
property the boundary guarantees. Each annotator runs under ``tolerate`` so a failing
enrichment never blocks schema loading (matching the old per-block try/except).
"""
from __future__ import annotations

from typing import Callable

from aughor.kernel.errors import tolerate

# fn(conn, schema_str) -> schema_str
Annotator = Callable[[object, str], str]

_ANNOTATORS: list[tuple[str, str, Annotator]] = []  # (name, phase, fn)


def register_schema_annotator(name: str, fn: Annotator, *, phase: str = "all") -> None:
    """Register a schema annotator. ``phase`` ∈ {``"fast"``, ``"heavy"``, ``"all"``}."""
    assert phase in ("fast", "heavy", "all"), phase
    _ANNOTATORS.append((name, phase, fn))


def clear() -> None:
    """Drop every registered annotator (idempotent re-registration / test isolation)."""
    _ANNOTATORS.clear()


def run_annotators(conn: object, schema_str: str, *, phase: str) -> str:
    """Apply the registered annotators for ``phase`` (and ``"all"``) in registration
    order. Returns the raw schema unchanged if nothing applies."""
    out = schema_str
    for name, ph, fn in list(_ANNOTATORS):
        if ph == phase or ph == "all":
            try:
                out = fn(conn, out)
            except Exception as e:
                tolerate(e, f"schema annotator {name!r} ({phase}) is additive; "
                            "schema loads without it", counter=f"schema.annotator.{name}")
    return out
