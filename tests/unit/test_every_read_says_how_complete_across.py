"""Every object read says how complete it is — on an organisation's ontology (Arc ED, ED-6; ON-8's doors), whose
types live on more than one connection: the same field on the same doors, and a read that would have to be taken from
part of a far source's rows is refused, said as ``refused``."""
from __future__ import annotations


from tests.unit.test_object_sources import _isolated, sources, wide  # noqa: F401 — fixtures by name

DOMAIN = {"domain": "default"}


def _said(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()["completeness"]


def test_the_organisations_doors_say_it_too(client, wide):  # noqa: F811
    assert _said(client.get("/objects/Customer/C00001", params=DOMAIN))["state"] == "complete"
    linked = client.get("/objects/Customer/C00001/links/customer_to_order", params={**DOMAIN, "limit": 2})
    assert _said(linked)["shown"] == len(linked.json()["rows"])
    titled = _said(client.post("/objects/titles", params=DOMAIN, json={"object_type": "Customer", "keys": ["C00001", "C99999"]}))
    assert (titled["state"], titled["shown"], titled["of"]) == ("complete", 1, 2)
    counted = client.post("/objects/query", params=DOMAIN,
                          json={"object_type": "Order", "by": ["status"], "measures": [{"name": "n", "agg": "count"}]})
    assert _said(counted)["state"] == "complete" and _said(counted)["shown"] == len(counted.json()["rows"])
    refused = _said(client.post("/objects/query", params=DOMAIN,
                                json={"object_type": "Nothing", "measures": [{"name": "n", "agg": "count"}]}))
    assert refused["state"] == "refused"


def test_a_query_cut_at_the_cap_says_truncated_and_one_over_the_cross_source_cap_refused(client, wide,  # noqa: F811
                                                                                           monkeypatch):
    monkeypatch.setattr("aughor.db.connection.MAX_ROWS", 1)
    cut = client.post("/objects/query", params=DOMAIN,
                      json={"object_type": "Order", "by": ["status"], "measures": [{"name": "n", "agg": "count"}]})
    assert _said(cut)["state"] == "truncated" and cut.json()["truncated"] is True
    by_country = {"object_type": "Order", "by": ["placed_by.country"], "measures": [{"name": "n", "agg": "count"}]}
    whole = client.post("/objects/query", params=DOMAIN, json=by_country)
    assert _said(whole)["state"] == "complete"            # read across two connections: its own budget, not that cap
    monkeypatch.setattr("aughor.semantic.cross_source.MAX_HOME_ROWS", 2)
    far = client.post("/objects/query", params=DOMAIN, json=by_country)
    said = _said(far)
    assert said["state"] == "refused" and said["shown"] == 0
    assert "never taken from part of them" in said["said"] and said["said"] == far.json()["error"]
