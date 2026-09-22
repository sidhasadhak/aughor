"""CB-3 — owners the platform can reach (Arc CB, 2026-09-22).

Measured before this wave: an owner was free text on a metric, a process and a business rule,
and a glossary term had no owner at all. `owner_principal` routed `user:…` / `group:…` and left
"Ana (logistics)" as the display text it always was, so a question for Ana had nowhere to go —
and ideas 17, 20 and 22 all end in "ask the owner".

Now a person links an owner text to a principal ONCE, and every owner field reading that text
routes; nothing ever links by matching a name; until linked, an owner is UNRESOLVED and the
surfaces that would have asked say so. These tests pin: the link routes and unlinking stops it;
the key is the text, not its spelling; a display name is never resolved by search; an invalid
principal is refused; the inventory names every owner in use with its resolution; a review asks
the linked owner and records why it asked the accepter when the owner is unresolved; the doors.
"""
from __future__ import annotations

import pytest

from aughor.rbac import owners as OW
from aughor.rbac.routing import owner_principal, route

ORG = "default"


@pytest.fixture(autouse=True)
def _clean():
    for l in OW.list_owner_links(ORG):
        OW.unlink_owner(ORG, l.owner_text)
    yield
    for l in OW.list_owner_links(ORG):
        OW.unlink_owner(ORG, l.owner_text)


class TestALinkMakesAnOwnerReachable:
    def test_display_text_routes_once_linked_and_stops_when_unlinked(self):
        assert owner_principal("Ana (logistics)", org_id=ORG) is None
        link = OW.link_owner(ORG, "Ana (logistics)", "user:ana@corp", linked_by="user:admin@corp")
        assert link.principal == "user:ana@corp" and link.linked_by == "user:admin@corp" and link.linked_at
        assert owner_principal("Ana (logistics)", org_id=ORG) == "user:ana@corp"
        assert OW.unlink_owner(ORG, "Ana (logistics)") is True
        assert owner_principal("Ana (logistics)", org_id=ORG) is None
        assert OW.unlink_owner(ORG, "Ana (logistics)") is False

    def test_the_key_is_the_text_not_its_spelling(self):
        OW.link_owner(ORG, "Ana (logistics)", "group:logistics")
        assert owner_principal("ana  (LOGISTICS)", org_id=ORG) == "group:logistics"
        assert owner_principal("Ana", org_id=ORG) is None                 # a different owner, not a prefix match

    def test_a_principal_spelling_still_routes_without_a_link(self):
        assert owner_principal("group:finance", org_id=ORG) == "group:finance"
        with pytest.raises(ValueError):
            OW.link_owner(ORG, "group:finance", "user:x@y")               # nothing to link

    def test_never_by_matching_a_name(self):
        """A link resolves exactly the text it was written for. Not the person's first name, not
        the address inside the principal, not a looser spelling of the label — nothing is matched,
        so nobody's question is filed under someone else."""
        OW.link_owner(ORG, "Ana (logistics)", "user:ana@corp")
        for looks_like_her in ("Ana", "ana@corp", "Ana Logistics", "Ana (logistics) team", "logistics"):
            assert owner_principal(looks_like_her, org_id=ORG) is None, looks_like_her

    def test_an_unroutable_principal_is_refused(self):
        for bad in ("Ana", "workspace:w1", "", "ana@corp"):
            with pytest.raises(ValueError):
                OW.link_owner(ORG, "Ana (logistics)", bad)
        with pytest.raises(ValueError):
            OW.link_owner(ORG, "   ", "user:a@b")

    def test_relinking_replaces_and_is_org_scoped(self):
        OW.link_owner(ORG, "Ana (logistics)", "user:ana@corp")
        OW.link_owner(ORG, "Ana (logistics)", "user:ana@newcorp")
        assert owner_principal("Ana (logistics)", org_id=ORG) == "user:ana@newcorp"
        assert owner_principal("Ana (logistics)", org_id="other-org") is None
        assert len(OW.list_owner_links(ORG)) == 1

    def test_routing_a_departure_reaches_the_linked_owner(self):
        OW.link_owner(ORG, "Ana (logistics)", "user:ana@corp")
        dests = route("metric:late_dispatch", org_id=ORG, owner="Ana (logistics)")
        assert [d.principal for d in dests] == ["user:ana@corp"]
        assert route("metric:late_dispatch", org_id=ORG, owner="Bob (unlinked)") == []


class TestTheInventory:
    def test_every_owner_in_use_is_named_with_its_resolution(self, monkeypatch):
        from types import SimpleNamespace
        import aughor.semantic.metrics as M
        import aughor.semantic.glossary as G
        import aughor.agent.framing as F
        monkeypatch.setattr(M, "list_metrics", lambda path=None, connection_id=None: [
            SimpleNamespace(name="revenue", owner="Ana (logistics)", connection_id=""),
            SimpleNamespace(name="margin", owner="group:finance", connection_id=""),
            SimpleNamespace(name="orders", owner=None, connection_id="")])
        monkeypatch.setattr(G, "load_glossary", lambda path=None, **k: {"tables": {"orders": {"owner": "Ana (logistics)",
                                                                                              "columns": {"id": {"owner": "Data team"}}}}})
        proc = SimpleNamespace(owner="Ops lead"); rule = SimpleNamespace(owner="")
        monkeypatch.setattr(F, "served_graph", lambda cid, schema=None: SimpleNamespace(processes={"dispatch": proc}, rules={"r1": rule}))
        OW.link_owner(ORG, "Ops lead", "user:ops@corp")
        inv = OW.owner_inventory(ORG, connection_ids=["c1"])
        by = {e["owner_key"]: e for e in inv}
        assert by["ana (logistics)"]["resolved"] is False and by["ana (logistics)"]["how"] == "unresolved"
        assert {(u["kind"], u["id"]) for u in by["ana (logistics)"]["uses"]} == {("metric", "revenue"), ("glossary_table", "orders")}
        assert by["group:finance"]["how"] == "principal" and by["group:finance"]["principal"] == "group:finance"
        assert by["ops lead"]["how"] == "linked" and by["ops lead"]["principal"] == "user:ops@corp"
        assert by["ops lead"]["uses"] == [{"kind": "process", "id": "dispatch", "connection_id": "c1"}]
        assert by["data team"]["uses"][0]["kind"] == "glossary_column"
        assert [e["resolved"] for e in inv][:2] == [False, False]          # the unresolved come first

    def test_a_source_that_fails_hides_nothing_else(self, monkeypatch):
        import aughor.semantic.metrics as M
        monkeypatch.setattr(M, "list_metrics", lambda path=None, connection_id=None: (_ for _ in ()).throw(RuntimeError("boom")))
        import aughor.agent.framing as F
        monkeypatch.setattr(F, "served_graph", lambda cid, schema=None: None)
        OW.link_owner(ORG, "Ana (logistics)", "user:ana@corp")
        inv = OW.owner_inventory(ORG, connection_ids=[])
        assert any(e["owner_key"] == "ana (logistics)" and e["uses"] == [] and e["how"] == "linked" for e in inv)


class TestAReviewReachesTheOwner:
    def test_the_linked_owner_is_asked_and_an_unlinked_one_is_said_so(self, tmp_path, monkeypatch):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        from aughor.playbook import outcomes as O
        import aughor.semantic.metrics as M
        monkeypatch.setattr(M, "get_metric", lambda name, path=None, connection_id=None: SimpleNamespace(owner="Ana (logistics)"))
        path = tmp_path / "o.json"; now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        spec = {"metric_label": "late dispatch", "metric_sql": "COUNT(*)", "metric_table": "t", "date_column": "t.d", "window_days": 7}
        o = O.log_outcome("inv", 0, "x", "accepted", path=path)
        O.record_acceptance(o, spec=spec, connection_id="c1", accepted_by="user:acc@corp", run_sql=lambda s: ([], [[1.0]], None), now=now, path=path)
        run = O.run_due_reviews(now + timedelta(days=31), run_sql_for=lambda c: (lambda s: ([], [[2.0]], None)), path=path)
        assert run[0].review_asked_to == "user:acc@corp"
        assert "not linked to a person; asked the accepter" in run[0].review_note
        OW.link_owner(ORG, "Ana (logistics)", "user:ana@corp")
        o2 = O.log_outcome("inv2", 0, "y", "accepted", path=path)
        O.record_acceptance(o2, spec=spec, connection_id="c1", accepted_by="user:acc@corp", run_sql=lambda s: ([], [[1.0]], None), now=now, path=path)
        run = O.run_due_reviews(now + timedelta(days=31), run_sql_for=lambda c: (lambda s: ([], [[2.0]], None)), path=path)
        assert [r.review_asked_to for r in run] == ["user:ana@corp"] and run[0].review_note == ""


class TestTheDoors:
    def test_link_list_and_unlink(self, client):
        r = client.put("/owners/links", json={"owner_text": "Ana (logistics)", "principal": "user:ana@corp"})
        assert r.status_code == 200 and r.json()["principal"] == "user:ana@corp"
        body = client.get("/owners", params={"connection_id": "fixture"}).json()
        assert any(l["owner_text"] == "Ana (logistics)" for l in body["links"])
        assert client.put("/owners/links", json={"owner_text": "Ana (logistics)", "principal": "Ana"}).status_code == 422
        assert client.delete("/owners/links", params={"owner_text": "ana (logistics)"}).status_code == 200
        assert client.delete("/owners/links", params={"owner_text": "ana (logistics)"}).status_code == 404

    def test_the_glossary_takes_an_owner(self, client, tmp_path, monkeypatch):
        import aughor.semantic.glossary as G
        p = tmp_path / "glossary.yaml"
        monkeypatch.setattr(G, "_default_path", lambda: p, raising=False)
        G.update_table("orders", owner="Ana (logistics)", path=p)
        G.update_column("orders", "id", owner="Data  team", path=p)
        raw = G._load_raw(p)
        assert raw["tables"]["orders"]["owner"] == "Ana (logistics)"
        assert raw["tables"]["orders"]["columns"]["id"]["owner"] == "Data team"
