"""Arc BC-2 (ROADMAP §3.67) — the blocks an edition is composed from, and what code checks first.

The model chooses; code decides what may be drawn. A block of a type that does not exist, reading a source nobody
measured, naming a column its source lacks, or listening to nothing, is refused in a sentence the model can act
on. Every word is then checked against the numbers the sources hold — their cells, changes and shares — and
against claiming a cause; what fails is withheld and listed, never silently dropped.
"""
from __future__ import annotations

from aughor.briefing.compose import spec as P
from aughor.briefing.compose.sources import BREAKDOWN_COLUMNS, Source

SOURCES = {
    "sales": Source(id="sales", label="Sales", kind="check", columns=["start", "value", "this_range"],
                    rows=[["2026-10-12", 158815.0, False], ["2026-10-19", 166988.0, True]],
                    facts={"current": 166988.0, "previous": 158815.0, "usual_mean": 160960.0,
                           "usual_low": 149913.0, "usual_high": 172007.0, "rel": 0.0515}, unit="EUR"),
    "by_top": Source(id="by_top", label="Sales by top client", kind="breakdown", columns=BREAKDOWN_COLUMNS,
                     rows=[[True, 85349.0, 75932.0, 9417.0, 0.124, 70, False],
                           [False, 81640.0, 85028.0, -3388.0, -0.0398, 189, False]]),
    "stores": Source(id="stores", label="Top clients by storefront", kind="query",
                     columns=["platform", "this_week", "usual"],
                     rows=[["Mytheresa", 38840.0, 29849.0], ["YOOX", 9845.0, 11051.0]]),
    "orders": Source(id="orders", label="Largest orders", kind="query", columns=["order_id", "platform", "value"],
                     rows=[["MYT-1", "Mytheresa", 3459.0], ["NET-1", "NET-A-PORTER", 2505.0]]),
    "gone": Source(id="gone", label="Markdowns", kind="query", status="refused", error="[EXCLUDED] turned off"),
}


def _spec(*blocks) -> P.Spec:
    return P.Spec(blocks=[P.Block(**b) for b in blocks])


LEAD = {"type": "lead", "text": "Sales were an ordinary {€167.0k|sales}, but top clients spent {€9.4k more|by_top}."}


def test_a_good_spec_passes_whole():
    blocks, refusals = P.validate(_spec(
        LEAD,
        {"type": "bridge", "source": "by_top", "title": "Where the week's sales came from"},
        {"id": "store", "type": "control", "source": "stores", "column": "platform"},
        {"type": "compare", "source": "stores", "label": "platform", "value": "this_week", "compare": "usual",
         "listens": "store"},
        {"type": "table", "source": "orders", "link": "order_id", "listens": "store"},
        {"type": "decision", "text": "Look into it?", "actions": ["email_the_ceo"]},
    ), SOURCES)
    assert blocks[-1].actions == ["deep_analysis", "give_to_team", "not_now"]   # offered by code, always
    assert refusals == [] and [b.type for b in blocks] == ["lead", "bridge", "control", "compare", "table", "decision"]
    assert len({b.id for b in blocks}) == 6


def test_what_cannot_be_drawn_is_refused_in_sentences_the_model_can_act_on():
    blocks, refusals = P.validate(_spec(
        LEAD,
        {"type": "pie", "source": "sales"},
        {"type": "compare", "source": "nowhere", "label": "a", "value": "b"},
        {"type": "table", "source": "gone"},
        {"type": "compare", "source": "stores", "label": "storefront", "value": "this_week"},
        {"type": "figure", "source": "stores"},
        {"type": "table", "source": "orders", "listens": "no_control"},
    ), SOURCES)
    said = " | ".join(refusals)
    assert "no block type 'pie'" in said
    assert "'nowhere', which no source is called" in said
    assert "could not be measured" in said and "turned off" in said
    assert "names column 'storefront'" in said and "platform, this_week, usual" in said
    assert "(figure) must read a check" in said
    assert "listens to 'no_control', which is not a control" in said
    assert [b.type for b in blocks] == ["lead"]


def test_a_listener_needs_the_controls_column_and_the_lead_comes_first():
    blocks, refusals = P.validate(_spec(
        {"id": "store", "type": "control", "source": "stores", "column": "platform"},
        LEAD,
        {"type": "bridge", "source": "by_top", "listens": "store"},
    ), SOURCES)
    said = " | ".join(refusals)
    assert "its source has no 'platform' column" in said
    assert "first block must be the lead" in said


def test_an_edition_has_at_most_fourteen_blocks():
    _blocks, refusals = P.validate(_spec(*([LEAD] + [{"type": "quiet", "text": "Steady."}] * 15)), SOURCES)
    assert any("at most 14 blocks" in r for r in refusals)


def test_a_citation_must_point_at_a_source():
    _b, refusals = P.validate(_spec({"type": "lead", "text": "Sales were {€167.0k|salez}."}), SOURCES)
    assert any("'salez', which no source is called" in r for r in refusals)


def test_every_number_a_source_holds_or_derives_is_allowed():
    allowed = P.allowed_numbers(SOURCES)
    near = lambda x: any(abs(a - x) < 0.6 for a in allowed)   # noqa: E731
    assert near(9417) and near(12.4)                            # a breakdown's change and its share
    assert near(30.1)                                           # Mytheresa against usual, a row's own change
    assert near(2)                                              # how many largest orders
    assert near(5.15) and near(6028)                            # a check's change on the week before, and on usual


def test_a_made_up_number_and_a_cause_are_withheld_and_listed():
    blocks, _ = P.validate(_spec(
        {"type": "lead", "text": "Sales were {€167.0k|sales}. Promotions lifted sales.",
         "sub": "Top clients spent €12.0k more."},
        {"type": "quiet", "text": "Margin rose 9 points."},
        {"type": "compare", "source": "stores", "label": "platform", "value": "this_week", "compare": "usual",
         "title": "Mytheresa's top clients spent 30% more"},
    ), SOURCES)
    kept, withheld, refusals = P.gate(blocks, SOURCES)
    by_type = {b.type: b for b in kept}
    assert by_type["lead"].text == "Sales were {€167.0k|sales}."          # the cited sentence kept, marks intact
    assert by_type["lead"].sub == ""
    assert by_type["compare"].title == "Mytheresa's top clients spent 30% more"
    assert "quiet" not in by_type                                          # nothing left to say: dropped, listed
    reasons = {w["sentence"]: w["why"] for w in withheld}
    assert "cause" in reasons["Promotions lifted sales."]
    assert "12.0k" in reasons["Top clients spent €12.0k more."]
    assert any(w["why"] == "every sentence of it was held" for w in withheld)
    assert refusals                                                        # and said back for the rewrite


# ── a number is checked against what it is said of, not only against every source ────────────

BY_STORE = Source(id="by_store", label="Sales by storefront", kind="breakdown", columns=BREAKDOWN_COLUMNS,
                  rows=[["Mytheresa", 38840.0, 29849.0, 8991.0, 0.301, 24, False],
                        ["YOOX", 9845.0, 11051.0, -1206.0, -0.109, 12, False]])
MORE = {**SOURCES, "by_store": BY_STORE}


def _held(*blocks) -> dict[str, str]:
    validated, _ = P.validate(_spec(LEAD, *blocks), MORE)
    _kept, withheld, _ = P.gate(validated, MORE)
    return {w["sentence"]: w["why"] for w in withheld if w["sentence"]}


def test_a_cited_number_must_come_from_the_source_its_citation_names():
    held = _held({"type": "quiet", "text": "Sales came to {€38.8k|sales}. Top clients spent {€38.8k|stores}."})
    assert held == {"Sales came to €38.8k.": "it cites Sales for 38.8k, which Sales does not hold"}


def test_a_number_said_of_a_segment_must_be_that_segments():
    held = _held({"type": "quiet", "text": "YOOX's top clients spent {€38.8k|stores}. "
                                            "Mytheresa's top clients spent {€38.8k|stores}."})
    assert held == {"YOOX's top clients spent €38.8k.":
                    "it puts 38.8k on YOOX, which is not YOOX's in Top clients by storefront"}


def test_a_direction_must_be_the_way_the_measured_change_went():
    held = _held({"type": "quiet", "text": "YOOX rose to {€9.8k|by_store}. Mytheresa rose to {€38.8k|by_store}. "
                                            "Sales fell to {€166,988|sales}. Sales rose to {€167.0k|sales}."})
    assert held == {"YOOX rose to €9.8k.": "it says YOOX rose, but YOOX is below its usual in Sales by storefront",
                    "Sales fell to €166,988.": "it says Sales fell, but it is above every range it is compared with"}


def test_a_direction_in_another_clause_is_not_put_on_the_citation():
    assert _held({"type": "quiet", "text": "Returns fell below usual, so sales came to {€167.0k|sales}."}) == {}


def test_a_number_outside_a_citation_must_come_from_a_source_the_block_reads():
    held = _held({"type": "figure", "source": "sales", "text": "Top clients bought 9,417 more. Sales were 166,988."})
    assert held == {"Top clients bought 9,417 more.":
                    "it states 9,417, which none of the sources it reads (Sales) holds"}


# ── what the platform already knows, cited ───────────────────────────────────────────────────

ANALYSIS = Source(id="analysis_a1", label="Revenue rose on volume", kind="analysis", status="final",
                  columns=["headline", "question", "completed"], rows=[["Revenue rose €93,820 on order volume", "Why?", ""]],
                  facts={"headline": "Revenue rose €93,820 (+14.9%) on order volume", "summary": "Orders rose 16.8%.",
                         "licence": "descriptive"})
CAUSAL = ANALYSIS.model_copy(update={"id": "analysis_c1", "facts": {**ANALYSIS.facts, "licence": "causal"}})
KNOWN_SRC = {**SOURCES, ANALYSIS.id: ANALYSIS, CAUSAL.id: CAUSAL}


def _held_known(*blocks) -> dict[str, str]:
    validated, refusals = P.validate(_spec(LEAD, *blocks), KNOWN_SRC)
    assert refusals == [], refusals
    _kept, withheld, _ = P.gate(validated, KNOWN_SRC)
    return {w["sentence"]: w["why"] for w in withheld if w["sentence"]}


def test_a_deep_analysiss_numbers_may_be_repeated_when_it_is_cited():
    assert _held_known({"type": "context", "source": "analysis_a1",
                        "text": "A deep analysis found {revenue rose €93,820, or 14.9%|analysis_a1}."}) == {}


def test_a_cause_stands_only_on_a_deep_analysis_licensed_to_say_it():
    held = _held_known({"type": "quiet", "text": "Order volume drove the rise, a deep analysis found {€93,820|analysis_a1}. "
                                                 "Order volume drove revenue, another found {€93,820|analysis_c1}."})
    assert list(held) == ["Order volume drove the rise, a deep analysis found €93,820."]      # descriptive: held
    assert "cause" in held["Order volume drove the rise, a deep analysis found €93,820."]


def test_a_context_block_draws_only_the_platforms_own_work_and_its_work_only_in_a_context_block():
    _blocks, refusals = P.validate(_spec(LEAD, {"type": "context", "source": "sales"},
                                         {"type": "table", "source": "analysis_a1"}), KNOWN_SRC)
    said = " | ".join(refusals)
    assert "(context) reads a deep analysis, a finding, a decision or a discussion; 'sales' is a check" in said
    assert "(table) cannot draw 'analysis_a1', the platform's own work — use a context block" in said
