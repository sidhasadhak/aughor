"""Arc SH, SH-8 — a sheet shared with chosen people and groups, and a stale write that says who (ROADMAP §3.64).

Run against the real stores — the ledger, the edit layer, the projection, the RBAC store — each at a temporary path.
Who is asking is set as the install's operator (``AUGHOR_LOCAL_USER``), the person every request without a sign-in
acts for, so each person below is a real request through the real routes.

The falsifier is a row of a sheet not shared with someone reaching them: through the sheet's routes, the Sheets
connection (the SQL Editor, dashboards, every answer), the chat's tools, the schema a model is handed, or combining.
"""
from __future__ import annotations

import json

import pytest

from aughor.kernel.flags import flag_overrides

ORDERS = """order_id,customer_id,order_status,price
e481f51c,9ef432eb,delivered,29.99
53cdb2fc,b0830fb4,shipped,118.70
47770eb9,41ce2a54,shipped,159.90
"""
CUSTOMERS = """customer_id,city
9ef432eb,sao paulo
b0830fb4,campinas
"""

ON = {"sheets.core": True, "sheets.grid": True, "sheets.chat": True, "sheets.combine": True, "sheets.sharing": True}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    from aughor.actions import overlay
    from aughor.rbac import store as rbac_store
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    monkeypatch.setattr(rbac_store, "_DB_PATH", tmp_path / "rbac.db")
    from aughor.sheets import projection
    projection.reset()
    with flag_overrides(ON):
        yield tmp_path
    projection.reset()


def _as(monkeypatch, person: str) -> None:
    monkeypatch.setenv("AUGHOR_LOCAL_USER", person)


def _make(env, name="Olist orders", text=ORDERS, file="olist_orders_dataset.csv"):
    from aughor.sheets import files, service
    path = env / file
    path.write_text(text)
    return service.create_from_file(files.stage(path, path.name), name=name, by="user:ana")


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import sheets as sheets_router
    app = FastAPI()
    app.include_router(sheets_router.router)
    return TestClient(app)


def _share(sheet, shares, by="user:ana"):
    from aughor.sheets import model, sharing
    return sharing.set_sharing(model.get(sheet.id), "chosen", shares, by=by)


BO_READS_CY_EDITS = [{"kind": "person", "id": "bo", "level": "view"}, {"kind": "person", "id": "cy", "level": "edit"}]


# ── off, and never shared ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_sheet_never_shared_keeps_its_definition_and_its_reads_as_they_were(env):
    """Byte-identical: a sheet never shared stores no sharing in its definition, and with the flag off the home and the
    sheet read exactly the keys they read before SH-8."""
    from aughor.kernel.ledger import Ledger
    from aughor.sheets import model
    sheet = _make(env)
    for art in Ledger.default().artifacts_of_kind(model.KIND, conn_id=model.SHEETS_CONNECTION, org_id="default"):
        body = art["payload"]["_body"]
        assert "sharing" not in body and "shared_with" not in body
    with flag_overrides({"sheets.sharing": False}):
        listed = _client().get("/sheets").json()["sheets"][0]
        read = _client().get(f"/sheets/{sheet.id}").json()
    assert set(listed) == {"id", "name", "table", "rows", "columns", "came_from", "source", "last_change", "created_by",
                           "created_at", "version", "shared_with"}
    assert listed["shared_with"] == "workspace" and "access" not in read
    with flag_overrides({"sheets.sharing": False}):
        assert _client().get(f"/sheets/{sheet.id}/sharing").status_code == 404
        assert _client().put(f"/sheets/{sheet.id}/sharing", json={"sharing": "workspace"}).status_code == 404


def test_shared_back_with_the_workspace_the_definition_is_plain_again(env):
    from aughor.sheets import model, sharing
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    back = sharing.set_sharing(model.get(sheet.id), "workspace", [], by="user:ana")
    assert back.sharing == "workspace" and back.shared_with == []
    assert back.change.what == "shared with everyone in the workspace"
    from aughor.kernel.ledger import Ledger
    newest = max(Ledger.default().artifacts_of_kind(model.KIND, conn_id=model.SHEETS_CONNECTION, org_id="default"),
                 key=lambda a: a["version"])
    assert "sharing" not in newest["payload"]["_body"]


# ── who may do what ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_maker_owns_the_workspace_edits_and_the_chosen_get_what_they_were_given(env):
    from aughor.sheets import model, sharing
    sheet = _make(env)
    assert sharing.level_of(sheet, "user:ana").level == "own"
    assert sharing.level_of(sheet, "user:dee").level == "edit"          # the workspace's, as every sheet was
    kept = _share(sheet, BO_READS_CY_EDITS)
    assert kept.change.what == "shared with bo (can read), cy (can edit)" and kept.change.by == "user:ana"
    sheet = model.get(sheet.id)
    assert [sharing.level_of(sheet, p).level for p in ("user:ana", "user:bo", "user:cy", "user:dee")] == \
        ["own", "view", "edit", ""]


def test_a_group_reaches_its_members_and_a_role_its_holders(env):
    from aughor.rbac.groups import add_member, upsert_group
    from aughor.rbac.store import assign_role
    from aughor.sheets import model, sharing
    sheet = _make(env)
    upsert_group("default", "finance", "Finance")
    add_member("default", "finance", "user:eve")
    assign_role("default", "fay", "analyst")
    _share(sheet, [{"kind": "group", "id": "finance", "level": "view"}, {"kind": "role", "id": "analyst", "level": "edit"}])
    sheet = model.get(sheet.id)
    assert sharing.level_of(sheet, "user:eve").level == "view"
    assert sharing.level_of(sheet, "user:fay").level == "edit"
    assert sharing.level_of(sheet, "user:gus").level == ""              # neither in the group nor holding the role
    assert sheet.change.what == "shared with Finance (can read), Editor (can edit)"


def test_what_cannot_be_shared_is_refused_by_name(env):
    from aughor.sheets import model, service, sharing
    sheet = _make(env)
    with pytest.raises(service.Refused, match="there is no group 'nobody' here"):
        _share(sheet, [{"kind": "group", "id": "nobody", "level": "view"}])
    with pytest.raises(service.Refused, match="choose at least one person or group"):
        _share(sheet, [])
    with pytest.raises(service.Refused, match="no spaces"):
        _share(sheet, [{"kind": "person", "id": "bo smith", "level": "view"}])
    with pytest.raises(service.Refused, match="a person, a group or a role"):
        _share(sheet, [{"kind": "team", "id": "x", "level": "view"}])
    # the maker is not a share — they own it — and the last word on a person stands
    kept = _share(sheet, [{"kind": "person", "id": "ana", "level": "view"}, {"kind": "person", "id": "bo", "level": "view"},
                          {"kind": "person", "id": "user:bo", "level": "edit"}])
    assert [(s.id, s.level) for s in kept.shared_with] == [("bo", "edit")]
    with pytest.raises(sharing.NotShared, match="Only ana, who made"):
        sharing.set_sharing(model.get(sheet.id), "workspace", [], by="user:bo")


# ── the sheet's own routes ───────────────────────────────────────────────────────────────────────────────────────────

def test_a_sheet_not_shared_with_someone_is_listed_and_said_never_read(env, monkeypatch):
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    _as(monkeypatch, "dee")
    client = _client()
    listed = client.get("/sheets").json()["sheets"][0]
    assert listed["name"] == "Olist orders" and listed["created_by"] == "user:ana" and listed["access"] == ""
    # withheld is said: no count that reads as "empty", a sentence that says why and who to ask
    assert listed["rows"] is None and listed["columns"] is None and listed["last_change"] is None
    assert listed["withheld"] == '"Olist orders" was not shared with you. ana made it; ask them to share it with you.'
    for path in ("", "/rows", "/csv", "/check", "/changes", "/cells/1/c1", "/records/1", "/groups?group=c3",
                 "/sharing", "/grounding"):
        r = client.get(f"/sheets/{sheet.id}{path}")
        assert r.status_code == 403 and "was not shared with you" in r.json()["detail"], path
    r = client.patch(f"/sheets/{sheet.id}/cells", json={"cells": [{"row": 1, "column": "c3", "value": "lost"}]})
    assert r.status_code == 403


def test_a_reader_reads_and_is_told_why_they_cannot_change(env, monkeypatch):
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    _as(monkeypatch, "bo")
    client = _client()
    read = client.get(f"/sheets/{sheet.id}").json()
    assert read["access"] == "view" and read["shared_with"] == "chosen" and read["shares"] == 2
    assert client.get(f"/sheets/{sheet.id}/rows").json()["total"] == 3
    status = sheet.column("order_status").id
    for method, path, body in (("patch", "/cells", {"cells": [{"row": 1, "column": status, "value": "lost"}]}),
                               ("post", "/rows", {"values": {}}), ("post", "/columns", {"name": "x"}),
                               ("patch", "", {"name": "Mine now"}), ("post", "/undo", None),
                               ("post", "/propose", {"words": "add a column"})):
        r = getattr(client, method)(f"/sheets/{sheet.id}{path}", **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (method, path)
        assert r.json()["detail"] == 'You can read "Olist orders" but not change it: ana shared it with you to read.'


def test_an_editor_changes_it_but_only_its_maker_reshares_or_removes_it(env, monkeypatch):
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    status = sheet.column("order_status").id
    _as(monkeypatch, "cy")
    client = _client()
    assert client.patch(f"/sheets/{sheet.id}/cells",
                        json={"cells": [{"row": 1, "column": status, "value": "lost"}]}).status_code == 200
    r = client.put(f"/sheets/{sheet.id}/sharing", json={"sharing": "workspace"})
    assert r.status_code == 403 and r.json()["detail"].startswith("Only ana, who made")
    assert client.delete(f"/sheets/{sheet.id}").status_code == 403
    said = client.get(f"/sheets/{sheet.id}/sharing").json()
    assert said["access"] == "edit" and not said["may_change"] and said["maker"] == "ana"
    assert [(s["id"], s["level"]) for s in said["shared_with"]] == [("bo", "view"), ("cy", "edit")]
    _as(monkeypatch, "ana")
    changed = client.put(f"/sheets/{sheet.id}/sharing", json={"sharing": "workspace"}).json()
    assert changed["sharing"] == "workspace" and changed["may_change"]
    assert client.delete(f"/sheets/{sheet.id}").status_code == 200


def test_turning_sharing_off_never_opens_what_was_closed(env, monkeypatch):
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    _as(monkeypatch, "dee")
    with flag_overrides({"sheets.sharing": False}):
        assert _client().get(f"/sheets/{sheet.id}/rows").status_code == 403
        assert _client().get("/sheets").json()["sheets"][0]["rows"] is None


# ── every other door ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_sheets_connection_refuses_a_sheet_not_shared_with_the_person_it_runs_for(env, monkeypatch):
    """The SQL Editor, dashboards and every answer read sheets through this one connection."""
    from aughor.sheets.connection import SheetsConnection
    sheet = _make(env)
    other = _make(env, "Olist customers", CUSTOMERS, "olist_customers_dataset.csv")
    _share(sheet, BO_READS_CY_EDITS)
    _as(monkeypatch, "dee")
    for sql in (f"SELECT * FROM {sheet.table}",
                f"WITH x AS (SELECT * FROM {sheet.table}) SELECT COUNT(*) FROM x",                 # a CTE hides nothing
                f"SELECT * FROM {other.table} c JOIN {sheet.table} o ON o.customer_id = c.customer_id"):
        result = SheetsConnection().execute("t", sql)
        assert result.rows == [] and result.error and "was not shared with you, so this was not run" in result.error
    # a sheet still the workspace's reads as before, for them too
    assert SheetsConnection().execute("t", f"SELECT COUNT(*) FROM {other.table}").rows == [["2"]]
    _as(monkeypatch, "bo")
    assert SheetsConnection().execute("t", f"SELECT COUNT(*) FROM {sheet.table}").rows == [["3"]]


def test_a_statement_whose_tables_cannot_be_read_is_held_to_the_names_it_says(env, monkeypatch):
    from aughor.sheets import sharing
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    monkeypatch.setattr("aughor.sql.tables.extract_tables", lambda sql, dialect=None: set())
    assert "was not shared with you" in sharing.refusal_for_statement(f"SELECT 1 FROM {sheet.table}", "user:dee")
    assert sharing.refusal_for_statement("SELECT 1", "user:dee") == ""


def test_the_schema_a_model_is_handed_carries_no_values_of_a_sheet_shared_with_chosen_people(env):
    from aughor.db.schema_render import SAMPLE_MARK
    from aughor.sheets.connection import SheetsConnection
    sheet = _make(env)
    other = _make(env, "Olist customers", CUSTOMERS, "olist_customers_dataset.csv")
    _share(sheet, BO_READS_CY_EDITS)
    blocks = {}
    current = ""
    for line in SheetsConnection().get_schema().splitlines():
        if line.startswith("TABLE:"):
            current = line.split()[1].split(".")[-1]
        blocks.setdefault(current, []).append(line)
    assert any("order_status" in line for line in blocks[sheet.table])          # its columns are told
    assert not any(SAMPLE_MARK in line for line in blocks[sheet.table])          # its values are not
    assert any(SAMPLE_MARK in line for line in blocks[other.table])              # the workspace's sheet keeps them


def test_the_chats_tools_refuse_a_sheet_not_shared_with_the_person_asking(env, monkeypatch):
    from aughor.sheets import answer, chat
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    _as(monkeypatch, "dee")
    shown = answer.show_rows(sheet.id, {"conditions": [], "about": "all"})
    assert shown["shown"] is False and "was not shared with you" in shown["refused"] and "rows" not in shown
    assert answer.citable_counts(sheet.id) == []
    grounded = chat.explain_sheet(sheet.id)
    assert grounded["found"] is False and "was not shared with you" in grounded["summary"]


def test_a_sheet_not_shared_cannot_be_combined_into_one_that_is(env, monkeypatch):
    """A link or a total brings the other sheet's values in: the person combining must be able to read it."""
    orders = _make(env)
    customers = _make(env, "Olist customers", CUSTOMERS, "olist_customers_dataset.csv")
    _share(customers, [{"kind": "person", "id": "bo", "level": "view"}])
    _as(monkeypatch, "dee")
    body = {"column": orders.column("customer_id").id, "other": customers.id,
            "other_column": customers.column("customer_id").id, "bring": [customers.column("city").id]}
    for path in ("/links/preview", "/links"):
        r = _client().post(f"/sheets/{orders.id}{path}", json=body)
        assert r.status_code == 403 and "Olist customers" in r.json()["detail"], path


# ── two people at once ───────────────────────────────────────────────────────────────────────────────────────────────

def test_a_stale_write_says_who_changed_the_cell(env, monkeypatch):
    sheet = _make(env)
    _share(sheet, [{"kind": "person", "id": "bo", "level": "edit"}, {"kind": "person", "id": "cy", "level": "edit"}])
    status = sheet.column("order_status").id
    client = _client()
    _as(monkeypatch, "bo")
    read = client.get(f"/sheets/{sheet.id}/rows").json()
    version = read["versions"].get("2", {}).get(status, 0)
    _as(monkeypatch, "cy")
    assert client.patch(f"/sheets/{sheet.id}/cells",
                        json={"cells": [{"row": 2, "column": status, "value": "delivered", "version": version}]}
                        ).status_code == 200
    _as(monkeypatch, "bo")
    r = client.patch(f"/sheets/{sheet.id}/cells",
                     json={"cells": [{"row": 2, "column": status, "value": "canceled", "version": version}]})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail.startswith("cy changed order_status in row 2 at ") and "your change was not made" in detail
    assert "cy's value" in detail and "user:" not in detail and "version" not in detail
    page = client.get(f"/sheets/{sheet.id}/rows").json()
    row2 = next(r for r in page["rows"] if r[0] == 2)
    assert "delivered" in row2 and "canceled" not in json.dumps(page["rows"])       # cy's value stands


def test_the_chat_cannot_propose_or_apply_a_link_to_a_sheet_not_shared_with_the_person(env, monkeypatch):
    """Whoever applies a proposal may not be who asked for it: both are held to the other sheet's sharing — a proposal
    through the preview it is checked by (combining's own gate), an application through the sheet it reads."""
    from aughor.sheets import chat, projection, sharing
    orders = _make(env)
    customers = _make(env, "Olist customers", CUSTOMERS, "olist_customers_dataset.csv")
    _share(customers, [{"kind": "person", "id": "bo", "level": "view"}])
    _as(monkeypatch, "dee")
    cur = projection.cursor()
    try:
        with pytest.raises(chat.ChangeRefused, match='"Olist customers" was not shared with you'):
            chat.check_change(orders, {"type": "link", "column": "customer_id", "other": "Olist customers",
                                       "other_column": "customer_id", "bring": ["city"]}, cur)
    finally:
        cur.close()
    with pytest.raises(sharing.NotShared, match="was not shared with you"):
        chat._applied_from(customers.id)
    _as(monkeypatch, "bo")
    assert chat._applied_from(customers.id).id == customers.id


def test_a_person_reached_twice_holds_the_most_either_gives(env):
    from aughor.rbac.groups import add_member, upsert_group
    from aughor.sheets import model, sharing
    sheet = _make(env)
    upsert_group("default", "finance", "Finance")
    add_member("default", "finance", "user:bo")
    for order in ([{"kind": "group", "id": "finance", "level": "edit"}, {"kind": "person", "id": "bo", "level": "view"}],
                  [{"kind": "person", "id": "bo", "level": "view"}, {"kind": "group", "id": "finance", "level": "edit"}]):
        _share(sheet, order)
        assert sharing.level_of(model.get(sheet.id), "user:bo").level == "edit", order


def test_a_proposal_is_read_and_applied_only_as_its_sheet_is_shared(env, monkeypatch):
    from aughor.sheets import chat
    sheet = _make(env)
    _share(sheet, [{"kind": "person", "id": "bo", "level": "view"}])
    staged = {"id": "p1", "sheet": sheet.id, "state": "staged", "changes": []}
    monkeypatch.setattr(chat, "proposal", lambda pid: staged if pid == "p1" else None)
    monkeypatch.setattr(chat, "apply", lambda pid, picks, by: {"applied": pid})
    client = _client()
    _as(monkeypatch, "dee")
    r = client.get("/sheets/proposals/p1")
    assert r.status_code == 403 and "was not shared with you" in r.json()["detail"]
    _as(monkeypatch, "bo")
    assert client.get("/sheets/proposals/p1").status_code == 200
    r = client.post("/sheets/proposals/p1/apply", json={})
    assert r.status_code == 403 and r.json()["detail"].startswith('You can read "Olist orders" but not change it')
    _as(monkeypatch, "ana")
    assert client.post("/sheets/proposals/p1/apply", json={}).json() == {"applied": "p1"}


def test_the_result_cache_never_keeps_or_serves_a_sheets_rows(env, monkeypatch):
    """The cache sits in front of the door: a sheet's rows kept for one reader were served to the next, to whom the
    sheet was not shared (found on a scratch API 2026-10-27) — and stale after any edit. A sheet is live: every read of
    it goes to its door."""
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.db import matcache
    rows = QueryResult(hypothesis_id="t", sql="SELECT 1", columns=["n"], rows=[["3"]], row_count=1)
    never = matcache._never_cached
    # never kept: with the read side's guard lifted, nothing was written to read back
    matcache.put_cache("sheets", "SELECT COUNT(*) FROM olist_orders", rows, variant="v")
    monkeypatch.setattr(matcache, "_never_cached", lambda conn_id: False)
    assert matcache.get_cached("sheets", "SELECT COUNT(*) FROM olist_orders", variant="v") is None
    # never served: an entry kept before this held (a live install's cache) is a miss
    matcache.put_cache("sheets", "SELECT COUNT(*) FROM olist_orders", rows, variant="w")
    monkeypatch.setattr(matcache, "_never_cached", never)
    assert matcache.get_cached("sheets", "SELECT COUNT(*) FROM olist_orders", variant="w") is None
    matcache.put_cache("workspace", "SELECT COUNT(*) FROM olist_orders", rows, variant="v")
    assert matcache.get_cached("workspace", "SELECT COUNT(*) FROM olist_orders", variant="v").rows == [["3"]]


def test_a_stale_version_on_a_cell_nobody_changed_never_names_someone(env):
    """Found on the live receipt 2026-10-28: a version the cell never had, on a cell with no change on record, was said as
    "Someone changed order_status…" — a change that never happened."""
    from aughor.sheets import service
    sheet = _make(env)
    status = sheet.column("order_status").id
    with pytest.raises(service.Conflict) as refused:
        service.set_cells(sheet, [{"row": 1, "column": status, "value": "x", "version": 99}], by="user:cy")
    said = str(refused.value)
    assert said.startswith("Nobody has changed order_status in row 1, and this page sent a version it never had, so "
                           "your change was not made.")
    assert "Someone" not in said


def test_no_profile_or_ontology_is_built_over_the_sheets(env, monkeypatch):
    """The heavy pass writes value profiles everyone reads: over sheets it would carry a chosen sheet's values to people
    it was not shared with, stale after the next edit. The Sheets connection hands back its fast schema instead."""
    from aughor.db.schema_render import SAMPLE_MARK
    from aughor.kernel.registries import schema_annotators
    from aughor.sheets.connection import SheetsConnection
    sheet = _make(env)
    _share(sheet, BO_READS_CY_EDITS)
    real = schema_annotators.run_annotators

    def no_heavy(db, base, phase="fast"):
        assert phase != "heavy", "the heavy pass ran over the Sheets connection"
        return real(db, base, phase=phase)
    monkeypatch.setattr(schema_annotators, "run_annotators", no_heavy)
    db = SheetsConnection()
    built = db.build_intelligence()
    assert db.last_build["stage"] == "skipped"
    lines = built.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith("TABLE:") and line.split()[1].split(".")[-1] == sheet.table)
    block = []
    for line in lines[start + 1:]:
        if line.startswith("TABLE:"):
            break
        block.append(line)
    assert any("order_status" in line for line in block)                    # its columns are told
    assert not any(SAMPLE_MARK in line for line in block)                    # its values are not
