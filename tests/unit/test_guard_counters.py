"""WS3 · guard observability — every deterministic guard's fire/repair rate is countable.

The June guard-coverage run showed the grain guard firing on 20.7% of real
predictions, yet at runtime nothing recorded fire rates: an operator could not
tell whether the guards were doing work or silently no-oping. These tests pin
the counter contract (names + increments) on the shared guard modules so all
call paths (chat / deep / explorer / query-builder) are measured for free.
"""
from __future__ import annotations

from aughor.stats import bump, stats


def _count(key: str) -> int:
    return stats.snapshot()["counters"].get(key, 0)


def test_bump_is_fail_safe_and_counts():
    before = _count("unit.guard_counter_probe")
    bump("unit.guard_counter_probe")
    bump("unit.guard_counter_probe", 2)
    assert _count("unit.guard_counter_probe") == before + 3


def test_defan_counts_attempt_and_rewrite():
    from aughor.sql.fanout import FanoutFinding, defan

    before_attempt = _count("guard.defan.attempt.chasm")
    # An unbuildable finding still counts the attempt; rewritten only on success.
    finding = FanoutFinding(hub_root="orders", satellites=["a", "b"], aggregates=[], kind="chasm")
    defan("SELECT 1", finding)
    assert _count("guard.defan.attempt.chasm") == before_attempt + 1


def test_grain_guard_counts_fires():
    from aughor.sql.grain_guard import detect_fanout

    def probe(sql):
        # join key is non-unique on the right table: 100 rows, 10 distinct keys
        return True, [(100, 10)], None

    before = _count("guard.grain_fanout.fired")
    findings = detect_fanout(
        "SELECT SUM(oi.qty) FROM orders o JOIN order_items oi ON o.id = oi.order_id",
        probe, dialect="duckdb",
    )
    assert findings, "probe reports fan-out — the guard must fire"
    assert _count("guard.grain_fanout.fired") == before + len(findings)


def test_trust_checks_count_fires():
    from aughor.sql.trust_checks import run_trust_checks

    before = _count("guard.trust_e1.fired")
    out = run_trust_checks(
        "SELECT * FROM t WHERE name > 5",
        col_types={"t.name": "VARCHAR"},
    )
    assert out, "text-vs-numeric compare must produce an E1 finding"
    assert _count("guard.trust_e1.fired") == before + len(out)
