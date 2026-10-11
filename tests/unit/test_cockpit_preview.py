"""Arc AP-6 — preview a cockpit as a group (ROADMAP §3.57; the study's receipt: "Preview the desk as a group with a row
policy; see the rows it withholds said").

A builder reads the cockpit as they and a member of the group would: the group is one more party among the reader's.
Every party's row condition holds and a property is masked when any party may not read it, so a preview only ever
narrows — a person who may see more than the group sees exactly the group's objects, one who may see less sees only
what both may, and nobody is shown an object they may not see. What is withheld is said, naming the group.
"""
from __future__ import annotations

import pytest

from aughor.ontology.security import previewing
from tests.unit.test_object_actions import CONN, ORDER, db, graph  # noqa: F401 — fixtures by name
from tests.unit.test_ontology_security import RETURNED, SHIPPED, _as, _listing, secured  # noqa: F401 — fixtures by name


@pytest.fixture
def boss(secured):  # noqa: F811
    """One who may see every order the policies admit: in fulfilment and in support."""
    from aughor.rbac.groups import add_member
    add_member("default", "fulfilment", "user:boss")
    add_member("default", "support", "user:boss")
    return secured


def test_one_who_may_see_more_previews_exactly_the_groups_objects_told_whose_they_are(boss, db, monkeypatch):  # noqa: F811
    _as(monkeypatch, "boss")
    _, own, own_total = _listing(boss, db, columns=("status",))
    seen = {r[1] for r in own}
    assert seen <= SHIPPED | RETURNED and seen & SHIPPED and seen & RETURNED      # both groups' orders, their own
    with previewing("support"):
        compiled, rows, total = _listing(boss, db, columns=("status",))
    assert rows and {r[1] for r in rows} <= RETURNED and total < own_total
    assert any("only the Order objects user:boss previewing as support may see are shown — support: status in "
               "cancelled, refunded" in c for c in compiled.caveats), compiled.caveats


def test_one_who_may_see_less_previews_only_what_both_may_never_the_groups_rest(secured, db, monkeypatch):  # noqa: F811
    _as(monkeypatch, "ana")                                       # fulfilment: shipped and delivered only
    with previewing("support"):                                   # support: cancelled and refunded
        compiled, rows, total = _listing(secured, db, columns=("status",))
    assert (rows, total) == ([], 0)                                # never the group's orders ana may not see
    assert any("support: status in cancelled, refunded — and only those user:ana may see too (fulfilment: status in "
               "delivered, shipped)" in c for c in compiled.caveats), compiled.caveats


def test_a_preview_masks_what_the_group_may_not_read_even_when_its_previewer_may(secured, db, monkeypatch):  # noqa: F811
    _as(monkeypatch, "ben")                                       # in finance: reads the amount
    _, rows, _ = _listing(secured, db)
    assert any(r[2] is not None for r in rows)
    with previewing("support"):
        compiled, rows, _ = _listing(secured, db)
    assert all(r[2] is None for r in rows)
    assert any("masked for group:support; finance may read it" in c for c in compiled.caveats), compiled.caveats


def test_a_group_no_policy_admits_previews_no_object_and_says_so(secured, db, monkeypatch):  # noqa: F811
    from aughor.rbac.groups import upsert_group
    upsert_group("default", "marketing", "Marketing")
    _as(monkeypatch, "ben")
    with previewing("marketing"):
        compiled, rows, total = _listing(secured, db, columns=("status",))
    assert (rows, total) == ([], 0)
    assert any("marketing is none of its groups (fulfilment, support) — a member of marketing sees no Order object" in c
               for c in compiled.caveats), compiled.caveats


def test_the_doors_preview_only_a_group_of_this_organisation(secured, monkeypatch):  # noqa: F811
    from fastapi import HTTPException

    from aughor.ontology.security import reader
    from aughor.routers.objects import AS_GROUP, _preview
    _as(monkeypatch, "ben")
    with pytest.raises(HTTPException) as nope:
        _preview("no_such_group")
    assert nope.value.status_code == 422 and "no group 'no_such_group' here" in str(nope.value.detail)
    for nothing in (None, "", AS_GROUP):                           # a route called as a function holds FastAPI's default
        with _preview(nothing):
            assert reader().principals == ["user:ben"]
    with _preview("support"):
        assert reader().principals == ["user:ben", "group:support"]
        assert reader().groups["group:support"] == {"support", "*"}
    assert reader().principals == ["user:ben"]                     # and gone after


def test_a_request_previews_through_its_dependency_into_a_door_run_in_a_thread(secured, monkeypatch):  # noqa: F811
    """The door is a plain function FastAPI runs in a worker thread; the preview is set by the request's dependency on
    the request's own context, as the acting agent's header is — this holds that it reaches the read, and no other."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from aughor.ontology.security import reader
    from aughor.routers.objects import preview_from_request
    _as(monkeypatch, "ben")
    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(preview_from_request)])
    def probe():
        return {"principals": reader().principals}
    client = TestClient(app)
    assert client.get("/probe", params={"as_group": "support"}).json() == {"principals": ["user:ben", "group:support"]}
    assert client.get("/probe").json() == {"principals": ["user:ben"]}                 # the next request reads as ben
    refused = client.get("/probe", params={"as_group": "no_such_group"})
    assert refused.status_code == 422 and "no group 'no_such_group' here" in refused.text
