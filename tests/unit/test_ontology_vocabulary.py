"""Wave O1 — the vocabulary plane: synonyms, value dictionaries, format specs.

Two carrying tests. :func:`test_the_linker_reads_the_declared_store` is the structural one
— before O1 the linker WAS the synonym story, and a store sitting beside it rather than
under it would have given the platform two dialects. :func:`TestValueDictionaryTrim` is
the hazard the program did not name: a value dictionary is built from table data, so one
over a restricted table leaks its contents through the linker.
"""
from __future__ import annotations

import pytest

from aughor.ontology.vocabulary import (
    FORMATS,
    SOURCE_RANKS,
    SUBJECT_KINDS,
    FormatSpec,
    add_synonym,
    format_for,
    remove_synonym,
    set_format,
    set_value_dictionary,
    synonym_expansion,
    synonyms_for,
    value_dictionaries,
)


@pytest.fixture(autouse=True)
def vocab_root(tmp_path, monkeypatch):
    """Point the store at a tmp dir — never the tracked data/ tree."""
    import aughor.ontology.vocabulary as V

    monkeypatch.setattr(V, "_ROOT", tmp_path / "vocabulary")
    return tmp_path


# ── synonyms ────────────────────────────────────────────────────────────────────────

def test_a_synonym_round_trips():
    add_synonym("c1", "metric", "gmv_eur", "revenue")
    got = synonyms_for("c1")
    assert [(s.subject_id, s.synonym, s.source) for s in got] == \
        [("gmv_eur", "revenue", "human")]


def test_synonyms_are_normalized():
    add_synonym("c1", "metric", "gmv_eur", "  Gross   Revenue  ")
    assert synonyms_for("c1")[0].synonym == "gross revenue"


def test_source_rank_orders_the_results():
    """A caller taking the first match must get the human entry without knowing the rules."""
    add_synonym("c1", "metric", "m", "a", source="llm_candidate")
    add_synonym("c1", "metric", "m", "b", source="human")
    add_synonym("c1", "metric", "m", "c", source="mined")
    assert [s.source for s in synonyms_for("c1")] == ["human", "mined", "llm_candidate"]


def test_a_stronger_source_promotes_an_existing_synonym():
    """A human confirming a mined candidate is recorded as a promotion, not a duplicate."""
    add_synonym("c1", "metric", "m", "takings", source="mined")
    add_synonym("c1", "metric", "m", "takings", source="human")
    got = synonyms_for("c1")
    assert len(got) == 1 and got[0].source == "human"


def test_a_weaker_source_does_not_demote_a_human_entry():
    add_synonym("c1", "metric", "m", "takings", source="human")
    add_synonym("c1", "metric", "m", "takings", source="llm_candidate")
    assert synonyms_for("c1")[0].source == "human"


def test_the_strongest_source_claims_a_term_outright():
    """A human saying 'revenue' means gmv_eur must not be diluted by a mined guess
    pointing the same word elsewhere."""
    add_synonym("c1", "metric", "gmv_eur", "revenue", source="human")
    add_synonym("c1", "metric", "other", "revenue", source="mined")
    assert synonym_expansion("c1")["revenue"] == {"gmv_eur"}


def test_equal_sources_both_claim_the_term():
    add_synonym("c1", "metric", "a", "rev", source="mined")
    add_synonym("c1", "metric", "b", "rev", source="mined")
    assert synonym_expansion("c1")["rev"] == {"a", "b"}


def test_connections_do_not_share_synonyms():
    add_synonym("c1", "metric", "m", "revenue")
    assert synonyms_for("c2") == []


def test_filtering_by_subject_kind():
    add_synonym("c1", "metric", "m", "a")
    add_synonym("c1", "table", "t", "b")
    assert [s.synonym for s in synonyms_for("c1", subject_kind="table")] == ["b"]


def test_removal():
    add_synonym("c1", "metric", "m", "revenue")
    assert remove_synonym("c1", "metric", "m", "revenue")
    assert synonyms_for("c1") == []
    assert not remove_synonym("c1", "metric", "m", "revenue")


@pytest.mark.parametrize("kwargs,match", [
    ({"subject_kind": "galaxy"}, "unknown subject kind"),
    ({"source": "vibes"}, "unknown synonym source"),
    ({"synonym": "   "}, "needs a term"),
])
def test_junk_is_refused_rather_than_stored(kwargs, match):
    """Stored junk would silently never rank, which is worse than an error."""
    args = {"connection_id": "c1", "subject_kind": "metric", "subject_id": "m",
            "synonym": "x", **kwargs}
    with pytest.raises(ValueError, match=match):
        add_synonym(**args)


def test_an_unreadable_file_degrades_to_empty(vocab_root, monkeypatch):
    import aughor.ontology.vocabulary as V

    p = V._path("c1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not: valid: yaml: [")
    assert synonyms_for("c1") == []


def test_the_vocabularies_are_small_and_closed():
    assert SOURCE_RANKS == ("human", "mined", "llm_candidate")
    assert "metric" in SUBJECT_KINDS and "percent" in FORMATS


# ── the linker reads the store (the structural rule) ────────────────────────────────

def test_the_linker_reads_the_declared_store():
    """Before O1 the linker WAS the synonym story. A store beside it rather than under it
    gives the platform two dialects — Wave V's lesson at smaller scale."""
    from aughor.tools import schema_linker

    add_synonym("link-c1", "table", "orders", "takings")
    schema_linker.invalidate_hints("link-c1")
    table_hints, col_hints, synonyms = schema_linker.build_connection_hints("link-c1")

    assert "takings" in synonyms and "orders" in synonyms["takings"]
    assert "orders" in table_hints.get("takings", [])


def test_the_linker_still_works_with_no_declared_synonyms():
    from aughor.tools import schema_linker

    schema_linker.invalidate_hints("empty-c")
    assert schema_linker.build_connection_hints("empty-c") is not None


# ── format specs (O1c — declared here, rendered in S2) ──────────────────────────────

def test_a_format_spec_round_trips():
    set_format("c1", "gmv_eur", FormatSpec(display_name="GMV", format="currency",
                                           decimals=0, currency="EUR", compact=True))
    spec = format_for("c1", "gmv_eur")
    assert spec.format == "currency" and spec.currency == "EUR" and spec.compact


def test_an_unknown_format_is_refused():
    """A format nobody can render silently does nothing, and S2 has to implement each."""
    with pytest.raises(ValueError, match="unknown format"):
        set_format("c1", "x", FormatSpec(format="interpretive-dance"))


def test_an_undeclared_subject_has_no_spec():
    assert format_for("c1", "never-declared") is None


def test_this_module_does_not_render_anything():
    """#189's fix is split across two waves (J11): the spec is O1, the rendering is S2.
    A formatter here would be the chart-level hack the split exists to prevent."""
    import aughor.ontology.vocabulary as V

    assert not [n for n in dir(V) if n.startswith(("render", "format_value", "to_display"))]


# ── value dictionaries (O1b) ────────────────────────────────────────────────────────

def test_a_value_dictionary_round_trips():
    set_value_dictionary("c1", "products", "category", ["womenswear", "menswear"])
    dicts = value_dictionaries("c1")
    assert dicts[0].column == "category" and "womenswear" in dicts[0].values


def test_truncation_is_declared_not_silent():
    from aughor.ontology.vocabulary import MAX_VALUES

    vd = set_value_dictionary("c1", "t", "c", [f"v{i}" for i in range(MAX_VALUES + 10)])
    assert vd.truncated and len(vd.values) == MAX_VALUES


def test_resaving_replaces_rather_than_duplicates():
    set_value_dictionary("c1", "t", "c", ["a"])
    set_value_dictionary("c1", "t", "c", ["b"])
    assert len(value_dictionaries("c1")) == 1
    assert value_dictionaries("c1")[0].values == ["b"]


class TestValueDictionaryTrim:
    """The hazard the program did not name — pinned by the scoping doc as a gate."""

    def test_a_restricted_table_dictionary_is_withheld(self, monkeypatch):
        """Surfacing it would leak the table's CONTENTS through the linker — exactly what
        G5 closed one layer up."""
        from aughor.govern import tags as T
        from aughor.govern.tags import ClearanceDecision, Requirement
        from aughor.ontology.vocabulary import visible_value_dictionaries

        req = Requirement(key="tier", value="restricted", clearance="clearance.restricted")
        monkeypatch.setattr(
            T, "check",
            lambda securable, held, bypass=False: (
                ClearanceDecision(securable=securable, allowed=False,
                                  requirements=[req], missing=[req])
                if "salaries" in securable
                else ClearanceDecision(securable=securable, allowed=True)))

        set_value_dictionary("c1", "salaries", "band", ["A", "B"])
        set_value_dictionary("c1", "products", "category", ["womenswear"])
        kept, notice = visible_value_dictionaries("c1")

        assert [d.table for d in kept] == ["products"]
        assert "withheld by data governance" in notice
        assert "A" not in notice and "salaries" not in notice
