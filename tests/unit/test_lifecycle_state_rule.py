"""A lifecycle state is a short identifier, never a document — held at every place one is read.

Measured 2026-10-12 on LuxExperience: a one-row `generator_state.payload` JSON column contained
the word "complete", the explorer's substring match took it for a status column, and its
1.6M-character value was stored as a terminal state. `render_exploration_annotations` printed it
twice into the block appended to EVERY schema prompt (3.2M chars), the business-profile cap
budgeted only the tables, and the profile prompt reached 1.8M tokens — over every provider's
limit — so no profile and no metrics were ever built for that connection.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from aughor.ontology.lifecycle_states import is_lifecycle_state, plausible_lifecycle_states

BLOB = json.dumps({"ids": {"order": 145378}, "status": "complete", "next": "processing",
                   "rows": [{"k": i, "v": "x" * 40} for i in range(2000)]})
REAL = ["Complete", "Processing", "Shipped", "Cancelled", "Returned"]


def test_a_document_is_not_a_state_and_a_short_name_is():
    assert len(BLOB) > 100_000
    assert not is_lifecycle_state(BLOB)
    assert all(is_lifecycle_state(s) for s in REAL)
    assert not is_lifecycle_state("CA") and not is_lifecycle_state("Revenue / Spend")
    assert not is_lifecycle_state("") and not is_lifecycle_state("null")
    assert is_lifecycle_state("x" * 30) and not is_lifecycle_state("x" * 31)


def test_a_column_of_documents_has_no_lifecycle():
    assert plausible_lifecycle_states(REAL)
    assert not plausible_lifecycle_states([BLOB])
    assert plausible_lifecycle_states(REAL + [BLOB])          # judged on the values that are states
    assert not plausible_lifecycle_states(["a long description of a thing", "another one here"])


# ── the block appended to every schema prompt ───────────────────────────────────────────────

def _annotations(monkeypatch, maps: dict) -> str:
    from aughor.explorer import store
    monkeypatch.setattr(store, "load_aggregate", lambda _cid: {"phase": "complete", "lifecycle_maps": maps})
    return store.render_exploration_annotations("c1")


_ORDERS = {"status_column": "status", "states": REAL,
           "active_states": ["Processing", "Shipped"], "terminal_states": ["Complete", "Cancelled", "Returned"]}


def test_a_stored_document_state_never_reaches_the_prompt(monkeypatch):
    out = _annotations(monkeypatch, {
        "generator_state": {"status_column": "payload", "states": [BLOB],
                            "active_states": [], "terminal_states": [BLOB]},
        "orders": _ORDERS,
    })
    assert len(out) < 2_000, f"the lifecycle block is {len(out):,} chars"
    assert "generator_state" not in out and '"ids"' not in out
    assert "  orders.status\n    active:   Processing, Shipped\n    terminal: Complete, Cancelled, Returned" in out
    assert "active filter: status NOT IN ('Complete', 'Cancelled', 'Returned')" in out


def test_a_real_map_with_one_document_among_its_states_keeps_only_the_states(monkeypatch):
    mixed = {**_ORDERS, "states": REAL + [BLOB], "terminal_states": ["Complete", BLOB]}
    out = _annotations(monkeypatch, {"orders": mixed})
    assert BLOB[:20] not in out
    assert "terminal: Complete\n" in out and "NOT IN ('Complete')" in out


def test_a_clean_map_renders_as_it_always_did(monkeypatch):
    out = _annotations(monkeypatch, {"orders": _ORDERS})
    assert out == ("EXPLORATION INTELLIGENCE [COMPLETE] — background cartography, treat as authoritative:\n\n"
                   "ENTITY LIFECYCLE (verified state machines):\n"
                   "  orders.status\n"
                   "    active:   Processing, Shipped\n"
                   "    terminal: Complete, Cancelled, Returned\n"
                   "    active filter: status NOT IN ('Complete', 'Cancelled', 'Returned')")


# ── the source: which column the explorer maps ──────────────────────────────────────────────

def _col(values: list[str]) -> SimpleNamespace:
    return SimpleNamespace(semantic_type="dimension", is_low_cardinality=True, top_values=values)


def test_the_status_finder_skips_a_document_that_contains_a_state_word():
    from aughor.explorer.agent import _ACTIVE_SUBS, _find_status_col
    assert any(sub in BLOB for sub in _ACTIVE_SUBS)        # the substring match WOULD take it
    assert _find_status_col({"payload": _col([BLOB])}) is None
    assert _find_status_col({"payload": _col([BLOB]), "status": _col(REAL)}) == "status"


def test_the_lifecycle_phase_maps_only_states():
    from aughor.explorer.agent import _lifecycle_states
    assert _lifecycle_states([(BLOB,)]) is None
    assert _lifecycle_states([(s,) for s in REAL] + [(BLOB,)]) == REAL
    assert _lifecycle_states([("a long description of a thing",), ("another one here",)]) is None


# ── the ontology merge reads the same stored maps ───────────────────────────────────────────

def test_the_ontology_merge_keeps_a_document_out_of_the_active_filter(monkeypatch):
    from aughor.agent import schema_annotators
    from aughor.explorer import store
    mixed = {**_ORDERS, "states": REAL + [BLOB], "terminal_states": ["Complete", BLOB]}
    monkeypatch.setattr(store, "load_aggregate", lambda _cid: {"phase": "complete", "lifecycle_maps": {"orders": mixed}})
    entity = SimpleNamespace(id="order", source_tables=["orders"], terminal_states=[], properties={},
                             has_lifecycle=False, lifecycle_column=None, lifecycle_states=[],
                             active_filter=None, segments=[])
    graph = SimpleNamespace(entities={"order": entity}, relationships=[], joins=[])
    schema_annotators._apply_explorer_to_ontology(graph, "c1")
    assert entity.has_lifecycle and entity.lifecycle_states == REAL
    assert entity.terminal_states == ["Complete"]
    assert entity.active_filter == "status NOT IN ('Complete')"


# ── the business-profile cap is an upper bound on the whole text ────────────────────────────

def test_the_profile_cap_bounds_the_annotations_after_the_tables():
    from aughor.business_profile.infer import cap_schema
    tables = "\n\n".join(f"TABLE: t{i}  ({i * 100:,} rows)\n  a  INT\n  b  VARCHAR" for i in range(1, 30))
    trailer = ("EXPLORATION INTELLIGENCE\nENTITY LIFECYCLE (verified state machines):\n"
               f"  generator_state.payload\n    terminal: {BLOB}\n    active filter: payload NOT IN ('{BLOB}')\n"
               "SQL HINTS\n- keep me")
    schema = tables + "\n\n" + trailer
    assert len(schema) > 200_000
    out = cap_schema(schema, 6_000)
    assert len(out) <= 6_000, f"the cap let {len(out):,} chars through"
    assert out.startswith("TABLE: ") and "showing" in out             # tables kept, the table cut said
    assert "[line cut at 500 chars]" in out                            # the dumped value cut, and said
    assert "SQL HINTS\n- keep me" in out                               # short annotation lines survive


def test_the_profile_cap_says_when_it_cuts_annotations_short():
    from aughor.business_profile.infer import cap_schema
    tables = "TABLE: t1  (5 rows)\n  a  INT"
    trailer = "\n".join(f"- hint {i} " + "y" * 200 for i in range(400))
    out = cap_schema(tables + "\n\n" + trailer, 8_000)
    assert len(out) <= 8_000 and out.startswith("TABLE: t1")
    assert "annotations cut at 2,000 chars" in out
