"""Two ends of one contract: the schema RENDERER's value-enumeration line and the
ground-first RESOLVER's parser of it must agree — proven on the real renderer over a
real (in-memory) DuckDB, not on a hand-typed fixture that encodes what the author
believed the format was.

They had drifted (found 2026-08-15): the renderer writes ``  -- col  [a, b]`` on its own
line, the parser read the list only inline on the column line, and `domains` was ALWAYS
empty on live schemas — so annotation-based entity binding, the resolver's whole
purpose, was dead, and every entity fell through to a DB probe whose "absent" produced
false abstains ("'First Class' is not present in this data" with the value sitting in
the schema). No test caught it because every resolver test typed its own schema string.

This guard renders with the shipped renderer and asserts the shipped parser sees every
enumeration the renderer wrote. If either side changes its line grammar, this fails.
"""
from __future__ import annotations

import duckdb

from aughor.db.schema_render import render_raw_schema
from aughor.semantic.answer_resolution import _parse_schema, resolve


def _demo_conn() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE orders AS SELECT * FROM (VALUES
            ('o1', 'First Class', 'Texas', 261.96),
            ('o2', 'Same Day', 'California', 14.62),
            ('o3', 'Standard Class', 'Texas', 731.94),
            ('o4', 'Second Class', 'Kentucky', 22.37)
        ) t(order_id, ship_mode, state, sales)
    """)
    return con


def test_parser_reads_every_enumeration_the_renderer_writes():
    con = _demo_conn()
    rendered = render_raw_schema(con)
    written = [ln for ln in rendered.splitlines() if ln.lstrip().startswith("-- ") and "[" in ln]
    assert written, f"the renderer wrote no value enumerations — fixture or renderer changed:\n{rendered}"

    tables, domains = _parse_schema(rendered)
    assert "orders" in tables or any(t.endswith("orders") for t in tables), tables
    parsed_cols = {col for _t, col, _v in domains}
    for line in written:
        col = line.split()[1]           # "  -- <col>  [..."
        assert col in parsed_cols, (
            f"renderer wrote an enumeration for {col!r} that the resolver's parser did not "
            f"read:\n  {line}\nparsed domains: {domains}")


def test_a_rendered_value_binds_without_a_db():
    # The end-to-end property the drift silently broke: an entity the renderer
    # enumerated resolves from the schema text alone — no probe, no abstain.
    rendered = render_raw_schema(_demo_conn())
    r = resolve("What is the total sales for orders shipped via First Class?", schema=rendered)
    assert not r.not_found, r.not_found
    assert [(b.noun, b.column, b.value) for b in r.entity_bindings] == [
        ("First Class", "ship_mode", "First Class")]
