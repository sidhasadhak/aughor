"""The interval a prediction states holds about as often as it says (2026-11-06, `record/scenario.band`).

Measured on the live install: the history method's "80%" held 45% of the time — calibration error 0.40 over
101 settled predictions, misses on one side. Two faults, both in the formula: ``mean ± 1.28·sd`` is an interval
for the MEAN, not for the next reading, and it takes six windows' spread as exact. The fix is the prediction
interval for one new reading (t on n − 1 degrees of freedom × sd·√(1 + 1/n)) floored by split conformal —
never narrower than the method's own largest miss on the same windows. On 782 rolling origins of
LuxExperience's real weekly and monthly series it held 81% (the old band 65%).

Here the right answer is known exactly: readings drawn independently from one normal distribution, where a
correct 80% interval holds 80% of the time and the old one cannot.
"""
from __future__ import annotations

import math
import random

from aughor.record import scenario as S


def _rolling_coverage(series: list[float], rule) -> float:
    held = n = 0
    for t in range(6, len(series)):
        low, high = rule(series[t - 6:t])
        held += low <= series[t] <= high
        n += 1
    return held / n


def _old(prior: list[float]) -> tuple[float, float]:
    mu, sd = S._mean(prior), S._sd(prior)
    return mu - 1.2816 * sd, mu + 1.2816 * sd


def _new(prior: list[float]) -> tuple[float, float]:
    _, low, high = S.band(prior)
    return low, high


def test_on_readings_with_a_known_distribution_the_band_holds_what_it_states():
    rng = random.Random(20261106)
    series = [rng.gauss(100.0, 10.0) for _ in range(6006)]
    old, new = _rolling_coverage(series, _old), _rolling_coverage(series, _new)
    assert old < 0.76, old                       # the old "80%" cannot hold 80% here — it is about 0.74
    assert 0.78 <= new <= 0.90, new              # the new one does; the conformal floor makes it a little wider


def test_the_floor_is_the_methods_own_largest_miss():
    """A jump the spread understates: the band is no narrower than the worst it already missed by."""
    xs = [100.0, 101.0, 99.0, 100.0, 140.0, 100.0]
    mu, low, high = S.band(xs)
    misses = [abs(xs[i] - S._mean(xs[:i])) for i in range(2, len(xs))]
    assert math.isclose(high - mu, max(misses)) and math.isclose(mu - low, max(misses))


def test_where_past_misses_are_small_the_t_interval_stands():
    """Each reading after the second sat exactly where the ones before it pointed: no miss to floor the band with,
    so the t interval is the band. (A series that merely LOOKS steady usually floors it: the largest of four
    misses is often past t·sd·√(1+1/n), which is why the band is wider than the t interval alone.)"""
    xs = [90.0, 110.0, 100.0, 100.0, 100.0, 100.0]
    mu, low, high = S.band(xs)
    t_half = S._T80[5] * S._sd(xs) * math.sqrt(1 + 1 / 6)
    assert math.isclose(high - mu, t_half, rel_tol=1e-9)


def test_the_backtest_judges_the_band_it_states():
    """The Briefing prints "the interval held k of m": k must count THIS band, not the old one."""
    xs = [100.0, 101.0, 99.0, 100.0, 140.0, 100.0, 102.0]
    bt = S.backtest(xs)
    held = sum(1 for i in range(2, len(xs)) if (lambda b: b[1] <= xs[i] <= b[2])(S.band(xs[:i])))
    assert bt["held"] == held and bt["cases"] == len(xs) - 2


def test_every_caller_draws_the_one_band(monkeypatch):
    """Methods 3 and 4, a segment's comparison and the Briefing's expected band all read `band` — none keeps its
    own copy of the formula (the Briefing kept one until 2026-11-06)."""
    import inspect

    from aughor.briefing import expected
    for fn in (S.history_of, S.intervention, S.comparison):
        assert "band(" in inspect.getsource(fn), fn.__name__
    src = inspect.getsource(expected.expected_next)
    assert "S.band(" in src and "_sd(" not in src
