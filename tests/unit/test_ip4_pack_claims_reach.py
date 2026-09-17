"""Which of a pack's claims may reach a model — §3.15 ON-0a, and gate 6 (§3.17).

ON-0a's rule: "nothing from the map reaches a prompt block except through the same verified tier", and "an entry
that measures FALSE is rendered nowhere". ON-7b then gave the ontology explorer a catalogue that rendered every
claim — expectations included, from any pack a person had ever measured against the connection — while the module
and the model both said claims are never rendered. Since IP-4 a knowledge package is released by a person making it
active, so a draft's expectations could have reached a model through that block.

What holds now: the explorer's catalogue renders a claim only when a pack DEPLOYED on this connection (active and
bound) measured it TRUE. A person may still measure any pack's map against their data — that is how a package is
reviewed before it is activated — and the answer says whether the pack is deployed.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from aughor.db.connection import open_connection
from aughor.ontology.explorer import source_catalogue
from aughor.ontology.models import OntologyGraph
from aughor.ontology.prompt_reach import FIXTURE_DEPLOYED_PACKS, fixture_graph

REPO = Path(__file__).resolve().parents[2]
HEADING = "PACK CLAIMS"


def _claims_block(text: str) -> list[str]:
    if HEADING not in text:
        return []
    after = text.split(HEADING, 1)[1].splitlines()[1:]
    return [line for line in after if line.startswith("- ")]


def test_only_a_deployed_packs_confirmed_claim_reaches_the_prompt():
    """The fixture carries one claim of every tier from a deployed pack, and one a pack that is not deployed
    measured true. Only the first pack's measured-true claim is rendered."""
    graph = fixture_graph()
    tiers = {(c.provenance, c.tier) for c in graph.core_claims}
    assert tiers >= {("pack:core-ecommerce", "measured-true"), ("pack:core-ecommerce", "expected"),
                     ("pack:core-ecommerce", "measured-false"), ("pack:core-ecommerce", "human"),
                     ("pack:fashion-ecommerce", "measured-true")}, "the fixture must hold both sides of the gate"

    rendered = _claims_block(source_catalogue(graph, deployed_packs=FIXTURE_DEPLOYED_PACKS))
    assert rendered == ["- object Order: expected present, measured Order (orders)"]
    text = "\n".join(rendered)
    for absent in ("delivered, canceled",          # an expectation the data cannot speak to
                   "Order → Customer",             # a claim the data contradicts
                   "free_shipping",                # a claim a person settled
                   "Product"):                     # a pack that is not deployed here
        assert absent not in text


def test_a_catalogue_that_is_told_of_no_deployed_pack_renders_no_claim():
    """The default is closed: a caller that does not say which packs are deployed renders none of them."""
    graph = fixture_graph()
    assert graph.core_claims and HEADING not in source_catalogue(graph)


def test_the_explorer_sends_the_catalogue_it_was_given_the_packs_for():
    """The one model call carries the catalogue rendered for THIS connection's deployed packs."""
    from aughor.ontology.explorer import BusinessDraft, draft_business

    sent: dict = {}

    class _Llm:
        backend = "stub"

        def complete(self, *, system, user, response_model, temperature):
            sent["user"] = user
            return BusinessDraft()

    graph = fixture_graph()
    _draft, _answerer, catalogue = draft_business(graph, _Llm(), deployed_packs=FIXTURE_DEPLOYED_PACKS)
    assert _claims_block(catalogue) == ["- object Order: expected present, measured Order (orders)"]
    assert catalogue in sent["user"]
    _draft, _answerer, without = draft_business(graph, _Llm())
    assert HEADING not in without


# ── the measure door: a person may review any pack; the prompt still reads only a deployed one ──────────────────

def _lux() -> OntologyGraph:
    return OntologyGraph.model_validate(
        json.loads((REPO / "evals" / "ablation_luxexperience_ontology_measured.json").read_text()))


def test_the_explore_door_hands_the_catalogue_this_connections_deployed_packs(tmp_path, monkeypatch, client):
    """The route is the only plane that knows which packs a connection deployed. Were it to stop passing them, the
    claims would quietly leave the prompt rather than leak into it — so the wiring is read here by name."""
    import aughor.db.connection as C
    import aughor.llm.provider as P
    import aughor.ontology.explorer as EX
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology("914df862", "luxexperience", "fp", _lux())
    warehouse = tmp_path / "explore.duckdb"
    duckdb.connect(str(warehouse)).close()
    monkeypatch.setattr(C, "open_connection_for_with_schema",
                        lambda *_a, **_k: open_connection("duckdb", str(warehouse), connection_id="t"))
    monkeypatch.setattr(P, "get_provider", lambda *_a, **_k: object())
    seen: dict = {}

    def _recorder(graph, llm, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("this test reads the wiring, not the draft")

    monkeypatch.setattr(EX, "draft_business", _recorder)
    answer = client.post("/ontology/explore", params={"connection_id": "914df862", "schema_name": "luxexperience"})
    assert answer.status_code == 502, answer.text
    assert seen.get("deployed_packs") == [], "the route passes the packs deployed here — none, on this connection"


def test_the_measure_door_says_whether_the_pack_is_deployed_and_its_claims_stay_out_of_the_prompt(
        tmp_path, monkeypatch, client):
    """Reviewing a package against your own data is what gate 6 asks for, so the door takes any pack id. What it
    measures reaches the panel and the answer — never a prompt, until the pack is deployed here."""
    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.packs.ontology_map import bound_pack_ids
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology("914df862", "luxexperience", "fp", _lux())
    warehouse = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(warehouse))
    con.execute("CREATE SCHEMA luxexperience; CREATE TABLE luxexperience.payments (payment_id INT, status VARCHAR);"
                "INSERT INTO luxexperience.payments VALUES (1,'captured'), (2,'refunded'), (3,'failed');")
    con.close()
    monkeypatch.setattr(C, "open_connection_for_with_schema",
                        lambda *_a, **_k: open_connection("duckdb", str(warehouse), connection_id="t"))

    params = {"connection_id": "914df862", "schema_name": "luxexperience", "pack": "core-ecommerce"}
    answer = client.post("/ontology/measure", params=params)
    assert answer.status_code == 200, answer.text
    claims = answer.json()["claims"]
    assert claims["pack"] == "core-ecommerce" and claims["by_tier"]["measured-true"] >= 8
    assert claims["deployed"] is False, "the pack is not bound here, and the answer has to say so"

    saved = ST.load_ontology("914df862", "luxexperience", "fp")
    assert any(c.provenance == "pack:core-ecommerce" and c.tier == "measured-true" for c in saved.core_claims)
    assert bound_pack_ids("914df862", "luxexperience") == []
    assert HEADING not in source_catalogue(saved, deployed_packs=bound_pack_ids("914df862", "luxexperience"))
    # …and the same claims do reach it once the pack is deployed: the gate is deployment, not a blanket refusal.
    assert HEADING in source_catalogue(saved, deployed_packs=["core-ecommerce"])
