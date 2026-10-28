"""Arc SH, SH-7 — combining sheets: links, totals, a newer file (ROADMAP §3.64).

The falsifier is a test here: a linked total must equal the same total computed by SQL over the two sheets, through
the Sheets connection — before and after either sheet changes.
"""
from __future__ import annotations

import pytest


ORDERS = """order_id,customer_id,order_status,price
o1,c1,delivered,10.00
o2,c2,shipped,20.00
o3,c9,delivered,30.00
o4,,canceled,40.00
"""
CUSTOMERS = """customer_id,customer_city,customer_state
c1,sao paulo,SP
c2,rio de janeiro,RJ
c3,curitiba,PR
"""
PAYMENTS = """order_id,payment_type,payment_value
o1,credit_card,6.00
o1,voucher,4.00
o2,boleto,20.00
o9,boleto,99.00
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.sheets import projection
    projection.reset()
    yield tmp_path
    projection.reset()


def _make(env, name, text):
    from aughor.sheets import files, service
    path = env / f"{name}.csv"
    path.write_text(text)
    return service.create_from_file(files.stage(path, path.name), name=name, by="user:ana")


def _col(sheet, row, name):
    from aughor.sheets import model, projection
    s = model.get(sheet.id)
    return (projection.read_row(s, row) or {}).get(s.column(name).id)


def test_a_link_counts_every_match_and_every_miss_before_it_is_kept(env):
    from aughor.sheets import combine
    orders, customers = _make(env, "Orders", ORDERS), _make(env, "Customers", CUSTOMERS)
    seen = combine.link_preview(orders, "customer_id", customers.id, "customer_id")
    assert (seen["matched"], seen["missed"], seen["empty"]) == (2, 1, 1)
    assert seen["some_misses"] == ["c9"] and seen["other_repeats"] == 0


def test_a_looked_up_column_follows_the_sheet_it_reads(env):
    from aughor.sheets import combine, model, service
    orders, customers = _make(env, "Orders", ORDERS), _make(env, "Customers", CUSTOMERS)
    city = customers.column("customer_city").id
    combine.link_keep(orders, "customer_id", customers.id, "customer_id", bring=[city], by="user:ana")
    assert _col(orders, 1, "customer_city") == "sao paulo"
    assert _col(orders, 3, "customer_city") is None          # a miss is empty, never a guess
    service.set_cells(model.get(customers.id), [{"row": 1, "column": "customer_city", "value": "santos"}],
                      by="user:ana")
    assert _col(orders, 1, "customer_city") == "santos"
    from aughor.sheets import projection
    assert projection.check(model.get(orders.id))["same"]


def test_a_linked_total_equals_the_same_total_by_sql_over_the_two_sheets(env):
    """SH-7's falsifier."""
    from aughor.sheets import combine, model, service
    from aughor.sheets.connection import SheetsConnection
    orders, payments = _make(env, "Orders", ORDERS), _make(env, "Payments", PAYMENTS)
    seen = combine.total_preview(orders, "order_id", payments.id, "order_id", "sum",
                                 payments.column("payment_value").id)
    assert (seen["rows_with"], seen["rows_without"], seen["other_rows_unmatched"]) == (2, 2, 1)
    combine.total_keep(orders, "order_id", payments.id, "order_id", "sum", payments.column("payment_value").id,
                       name="Paid", by="user:ana")
    service.add_row(model.get(payments.id), {"order_id": "o3", "payment_type": "pix", "payment_value": "30"},
                    by="user:ana")

    def by_sql():
        o, p = model.get(orders.id), model.get(payments.id)
        r = SheetsConnection().execute("t", f"SELECT o.order_id, SUM(p.payment_value) FROM {o.table} o LEFT JOIN "
                                            f"{p.table} p ON p.order_id = o.order_id GROUP BY 1 ORDER BY 1")
        assert r.error is None, r.error
        return {k: (None if v == "NULL" else v) for k, v in r.rows}

    linked = SheetsConnection().execute("t", f'SELECT order_id, "Paid" FROM {model.get(orders.id).table} ORDER BY 1')
    assert {k: (None if v == "NULL" else v) for k, v in linked.rows} == by_sql()
    assert _col(orders, 4, "Paid") is None                   # no payment: empty, never zero
    assert _col(orders, 1, "Paid") == "10.00"


def test_a_count_of_no_rows_is_zero(env):
    from aughor.sheets import combine
    orders, payments = _make(env, "Orders", ORDERS), _make(env, "Payments", PAYMENTS)
    combine.total_keep(orders, "order_id", payments.id, "order_id", "count", name="Payments", by="user:ana")
    assert _col(orders, 1, "Payments") == 2 and _col(orders, 4, "Payments") == 0


def test_a_looked_up_column_needs_one_row_per_key_in_the_other_sheet(env):
    from aughor.sheets import combine, service
    orders, payments = _make(env, "Orders", ORDERS), _make(env, "Payments", PAYMENTS)
    # o1 is paid in two parts: which payment's type would an order read?
    with pytest.raises(service.Refused, match="repeat in Payments"):
        combine.link_keep(orders, "order_id", payments.id, "order_id", bring=[payments.column("payment_type").id],
                          by="user:ana")


NEWER = """order_id,customer_id,order_status,price
o1,c1,delivered,10.00
o2,c2,delivered,20.00
o3,c9,delivered,not a price
o5,c3,created,55.50
"""


def test_a_newer_file_is_previewed_cell_by_cell_then_applied_and_undone_as_one_change(env):
    from aughor.sheets import combine, files, model, projection, service
    orders = _make(env, "Orders", ORDERS)
    newer = env / "orders_november.csv"
    newer.write_text(NEWER)
    token = files.stage(newer, newer.name)
    seen = combine.merge_preview(orders, token, "order_id")
    assert seen["rows_added"] == 1 and seen["cells_changed"] == 1 and seen["misfit"] == 1
    assert seen["kept_as_is"] == 1                          # o4 is not in the file: kept, never removed
    assert seen["changes"][0]["old"] == "shipped" and seen["changes"][0]["new"] == "delivered"
    out = combine.merge_apply(orders, token, "order_id", basis=seen["basis"], by="user:ana")
    s = model.get(orders.id)
    assert _col(s, 2, "order_status") == "delivered" and _col(s, 3, "price") == "30.00"
    assert projection.count(s) == 5 and projection.check(s)["same"]
    service.undo(s, by="user:ana")
    s = model.get(orders.id)
    assert _col(s, 2, "order_status") == "shipped" and projection.count(s) == 4
    assert out["change_id"] and projection.check(s)["same"]


def test_a_merge_refuses_a_preview_the_sheet_has_moved_on_from(env):
    from aughor.sheets import combine, files, model, service
    orders = _make(env, "Orders", ORDERS)
    newer = env / "n.csv"
    newer.write_text(NEWER)
    token = files.stage(newer, newer.name)
    seen = combine.merge_preview(orders, token, "order_id")
    service.set_cells(orders, [{"row": 1, "column": "price", "value": "11"}], by="user:bo")
    with pytest.raises(service.Refused, match="changed since this preview"):
        combine.merge_apply(model.get(orders.id), token, "order_id", basis=seen["basis"], by="user:ana")


def test_a_removed_sheet_leaves_what_read_it_empty_not_wrong(env):
    from aughor.sheets import combine, model, service
    orders, customers = _make(env, "Orders", ORDERS), _make(env, "Customers", CUSTOMERS)
    combine.link_keep(orders, "customer_id", customers.id, "customer_id",
                      bring=[customers.column("customer_state").id], by="user:ana")
    assert _col(orders, 2, "customer_state") == "RJ"
    service.remove(model.get(customers.id), by="user:ana")
    assert _col(orders, 2, "customer_state") is None


def test_a_records_total_says_how_many_rows_it_adds_up(env):
    from aughor.sheets import combine, model, record
    orders = _make(env, "orders", ORDERS)
    payments = _make(env, "payments", PAYMENTS)
    combine.total_keep(orders, "order_id", payments.id, "order_id", "sum", "payment_value", name="Paid", by="user:ana")
    fields = {f["name"]: f for f in record.record(model.get(orders.id), 1)["fields"]}
    assert fields["Paid"]["source"] == "sum of payment_value over 2 rows of payments"
    fields = {f["name"]: f for f in record.record(model.get(orders.id), 3)["fields"]}
    assert fields["Paid"]["source"] == "no row of payments has this row's key, so it is empty"
