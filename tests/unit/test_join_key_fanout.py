"""Non-FK join fan-out — the class every FK-shaped detector is structurally blind to.

Source: the luxexperience Briefing of 2026-07-21 reported attributed GMV of
**102,870,539,329 EUR** from

    SELECT f.platform, d.type, SUM(f.attributed_gmv_eur)
    FROM marketing_campaigns f JOIN brand_collaborations d ON f.platform = d.platform
    GROUP BY f.platform, d.type

`platform` is a categorical column, not a key: every campaign matches every collaboration on
that platform, so each group is `SUM(all that platform's GMV) × (collaborations of that type)`.
The tell in the rendered table was two campaign types with byte-identical totals and a third at
exactly 3.0×.

Every one of `fanout.py`'s detectors routes through `fk_root()`, which recognises a key by its
NAME (`order_id` → `order`). `fk_root('platform')` is None, so all seven returned None and the
number shipped. `join_key_fanout` closes that hole — and does it EXECUTION-GROUNDED (the
cardinality oracle must have probed and found the joined table non-unique), so it cannot flag a
correct query on a naming guess.
"""
from __future__ import annotations

import sqlite3

from aughor.explorer.verify import verify_insight
from aughor.sql.fanout import join_key_fanout

# The exact shape from the brief.
FANNED_SQL = (
    "SELECT f.platform, d.type, SUM(f.attributed_gmv_eur) AS m_attributedgmveur "
    "FROM lux.marketing_campaigns f JOIN lux.brand_collaborations d ON f.platform = d.platform "
    "GROUP BY f.platform, d.type ORDER BY m_attributedgmveur DESC"
)

TABLE_COLS = {
    "lux.marketing_campaigns": ["campaign_id", "platform", "attributed_gmv_eur"],
    "lux.brand_collaborations": ["collab_id", "platform", "type"],
}


def _oracle(non_unique: set):
    """is_unique_on(table_bare, col) -> False for the listed (table, col), else None (unknown)."""
    def is_unique_on(bare: str, col: str):
        return False if (bare.lower(), col.lower()) in non_unique else None
    return is_unique_on


class TestFiresOnTheRealDefect:
    def test_flags_the_luxexperience_shape(self):
        why = join_key_fanout(
            FANNED_SQL, TABLE_COLS,
            is_unique_on=_oracle({("brand_collaborations", "platform")}))
        assert why is not None
        # names the fanning table, the key, and the inflated aggregate
        assert "brand_collaborations" in why
        assert "platform" in why
        assert "attributed_gmv_eur" in why

    def test_flags_avg_too(self):
        sql = ("SELECT d.type, AVG(f.attributed_gmv_eur) FROM lux.marketing_campaigns f "
               "JOIN lux.brand_collaborations d ON f.platform = d.platform GROUP BY d.type")
        why = join_key_fanout(sql, TABLE_COLS,
                              is_unique_on=_oracle({("brand_collaborations", "platform")}))
        assert why is not None and why.startswith("AVG(")

    def test_the_fk_shaped_detectors_really_are_blind_to_it(self):
        """Pins WHY this guard has to exist — if a sibling detector ever grows to cover the
        non-FK case, this test fails and the redundancy can be removed deliberately."""
        from aughor.sql.fanout import (
            avg_over_chasm_fanout, count_star_chasm_fanout, count_star_entity_fanout,
            cte_grain_mismatch_fanout, detect_fanout, dimension_ratio_chasm,
            sum_over_chasm_fanout,
        )
        for fn in (detect_fanout, sum_over_chasm_fanout, avg_over_chasm_fanout,
                   count_star_chasm_fanout, dimension_ratio_chasm, count_star_entity_fanout,
                   cte_grain_mismatch_fanout):
            assert fn(FANNED_SQL, TABLE_COLS) is None, f"{fn.__name__} unexpectedly fired"


class TestStaysSilentWhenItCannotProve:
    """The module's ethos: never flag a correct query. Every uncertainty is a bail."""

    def test_no_oracle_no_verdict(self):
        assert join_key_fanout(FANNED_SQL, TABLE_COLS, is_unique_on=None) is None

    def test_unknown_cardinality_no_verdict(self):
        assert join_key_fanout(FANNED_SQL, TABLE_COLS, is_unique_on=lambda b, c: None) is None

    def test_one_to_one_dimension_not_flagged(self):
        """fact ⋈ 1:1 dimension attaches exactly one row and multiplies nothing."""
        assert join_key_fanout(FANNED_SQL, TABLE_COLS, is_unique_on=lambda b, c: True) is None

    def test_pre_aggregated_cte_is_the_fix_not_the_defect(self):
        sql = ("WITH mc AS (SELECT platform, SUM(attributed_gmv_eur) g "
               "FROM lux.marketing_campaigns GROUP BY 1) "
               "SELECT mc.platform, SUM(mc.g) FROM mc "
               "JOIN lux.brand_collaborations d ON mc.platform = d.platform GROUP BY 1")
        assert join_key_fanout(sql, TABLE_COLS,
                               is_unique_on=_oracle({("brand_collaborations", "platform")})) is None

    def test_single_table_aggregate_not_flagged(self):
        sql = "SELECT platform, SUM(attributed_gmv_eur) FROM lux.marketing_campaigns GROUP BY 1"
        assert join_key_fanout(sql, TABLE_COLS, is_unique_on=lambda b, c: False) is None

    def test_count_distinct_is_fanout_safe(self):
        sql = ("SELECT d.type, COUNT(DISTINCT f.campaign_id) FROM lux.marketing_campaigns f "
               "JOIN lux.brand_collaborations d ON f.platform = d.platform GROUP BY d.type")
        assert join_key_fanout(sql, TABLE_COLS,
                               is_unique_on=_oracle({("brand_collaborations", "platform")})) is None

    def test_aggregate_over_the_fanning_table_itself_not_flagged(self):
        """Only the DUPLICATED side's measures inflate; the fanning table's own rows don't."""
        sql = ("SELECT f.platform, SUM(d.collab_id) FROM lux.marketing_campaigns f "
               "JOIN lux.brand_collaborations d ON f.platform = d.platform GROUP BY 1")
        assert join_key_fanout(
            sql, TABLE_COLS,
            is_unique_on=_oracle({("marketing_campaigns", "platform")})) is not None
        # ...and with only the OTHER side fanning, d's own measure is untouched by it
        assert join_key_fanout(
            sql, TABLE_COLS,
            is_unique_on=lambda b, c: False if b.lower() == "brand_collaborations" else True
        ) is None

    def test_a_filtered_join_bails(self):
        """A whole-table uniqueness probe is only sound evidence when the ON is pure equality.
        `AND d.type = 'exclusive_capsule'` can make the join 1:1 even though `brand_collaborations`
        is non-unique on `platform` across the whole table — the probe would prove a fan-out this
        query doesn't have. Rather than reason about the filter, stay silent."""
        sql = ("SELECT f.platform, SUM(f.attributed_gmv_eur) FROM lux.marketing_campaigns f "
               "JOIN lux.brand_collaborations d "
               "ON f.platform = d.platform AND d.type = 'exclusive_capsule' GROUP BY 1")
        assert join_key_fanout(sql, TABLE_COLS,
                               is_unique_on=_oracle({("brand_collaborations", "platform")})) is None

    def test_a_non_equality_join_bails(self):
        sql = ("SELECT f.platform, SUM(f.attributed_gmv_eur) FROM lux.marketing_campaigns f "
               "JOIN lux.brand_collaborations d ON f.platform > d.platform GROUP BY 1")
        assert join_key_fanout(sql, TABLE_COLS,
                               is_unique_on=_oracle({("brand_collaborations", "platform")})) is None

    def test_garbage_never_raises(self):
        assert join_key_fanout("not sql at all", TABLE_COLS, is_unique_on=lambda b, c: False) is None


class TestEndToEndThroughTheEmissionGate:
    """Proves the WIRING on a real database with the real cardinality oracle — the guard is
    useless if `verify_insight` doesn't consult it."""

    SCHEMA = (
        "TABLE: marketing_campaigns (3 rows)\n"
        "  campaign_id  INTEGER\n"
        "  platform  TEXT\n"
        "  attributed_gmv_eur  REAL\n"
        "TABLE: brand_collaborations (6 rows)\n"
        "  collab_id  INTEGER\n"
        "  platform  TEXT\n"
        "  type  TEXT\n"
    )

    def _conn(self, tmp_path):
        from aughor.connectors.file.sqlite import SQLiteConnection

        db_file = tmp_path / "fanout.sqlite"
        seed = sqlite3.connect(str(db_file))
        seed.executescript("""
            CREATE TABLE marketing_campaigns (campaign_id INTEGER, platform TEXT, attributed_gmv_eur REAL);
            INSERT INTO marketing_campaigns VALUES (1,'NAP',100.0),(2,'NAP',200.0),(3,'MYT',50.0);
            CREATE TABLE brand_collaborations (collab_id INTEGER, platform TEXT, type TEXT);
            INSERT INTO brand_collaborations VALUES
              (1,'NAP','exclusive_capsule'),(2,'NAP','exclusive_capsule'),(3,'NAP','exclusive_capsule'),
              (4,'NAP','pop_up'),(5,'NAP','pre_launch'),(6,'MYT','exclusive_capsule');
        """)
        seed.commit()
        seed.close()

        conn = SQLiteConnection(dsn=str(db_file), connection_id="join_fanout_test")
        conn._insight_table_cols = {
            "marketing_campaigns": ["campaign_id", "platform", "attributed_gmv_eur"],
            "brand_collaborations": ["collab_id", "platform", "type"],
        }
        return conn, db_file

    def test_the_query_really_does_over_count(self, tmp_path):
        """Ground truth first: NAP's true GMV is 300, and the join reports 900/300/300 —
        the identical-pair + exact-3× signature seen in the real brief."""
        _conn, db_file = self._conn(tmp_path)
        raw = sqlite3.connect(str(db_file))
        assert raw.execute(
            "SELECT SUM(attributed_gmv_eur) FROM marketing_campaigns WHERE platform='NAP'"
        ).fetchone()[0] == 300.0
        got = dict(raw.execute(
            "SELECT d.type, SUM(f.attributed_gmv_eur) FROM marketing_campaigns f "
            "JOIN brand_collaborations d ON f.platform = d.platform "
            "WHERE f.platform='NAP' GROUP BY d.type").fetchall())
        raw.close()
        assert got == {"exclusive_capsule": 900.0, "pop_up": 300.0, "pre_launch": 300.0}

    def test_gate_drops_the_fanned_finding(self, tmp_path):
        conn, _ = self._conn(tmp_path)
        ok, why = verify_insight(
            [["NAP", "exclusive_capsule", "900.0"], ["NAP", "pop_up", "300.0"]],
            "Exclusive capsule collaborations drive attributed GMV at 900 EUR — 3x pop_up at 300.",
            "SELECT f.platform, d.type, SUM(f.attributed_gmv_eur) AS m "
            "FROM marketing_campaigns f JOIN brand_collaborations d ON f.platform = d.platform "
            "GROUP BY f.platform, d.type",
            conn=conn)
        assert not ok
        assert "fan-out" in why and "brand_collaborations" in why

    def test_gate_keeps_the_correct_single_table_finding(self, tmp_path):
        """The honest version of the same question must still pass — no over-blocking."""
        conn, _ = self._conn(tmp_path)
        ok, why = verify_insight(
            [["NAP", "300.0"], ["MYT", "50.0"]],
            "NET-A-PORTER leads attributed GMV at 300 EUR, ahead of Mytheresa at 50.",
            "SELECT platform, SUM(attributed_gmv_eur) AS m FROM marketing_campaigns "
            "GROUP BY platform ORDER BY m DESC",
            conn=conn)
        assert ok, why
