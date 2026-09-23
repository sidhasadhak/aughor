"""A currency symbol states what a number IS, so it follows the data — not the reader.

theLook is a USD dataset. The workspace declares EUR. On 2026-09-23 a chart posted into a
real Slack channel carried a revenue axis reading "€0 · €20.0K · €40.0K" over dollars, and
the answer beside it said in plain words that it had applied no currency conversion. Both
halves were working as written: the workspace setting was documented as AUTHORITATIVE over
the per-connection value, and the profile had itself inferred `EUR` from theLook's customer
country column.

The fact that settles it: **nothing in this tree converts currency.** Searching for an
exchange rate finds two comments in the profiler about column NAMING and no converter. So a
declared reporting currency applied to a warehouse figure does not report it in that
currency — it relabels it, and the number is then wrong by whatever the rate is.

What these guard:

* the DATA's currency wins wherever a figure is labelled, and the org's applies only when
  the data declares none — the mutation `eff or data` restores the live defect exactly;
* `resolve_industry` is UNTOUCHED and still lets the org win, because an industry is a
  claim about the organisation and needs no conversion to be true. A test that only
  asserted the new currency order would pass just as well if someone had inverted both;
* the org's own statement about itself SURVIVES — `org_context` still says "reports in
  EUR", because that sentence is about the organisation and is read straight from the
  settings rather than through the resolver.
"""
from __future__ import annotations

import pytest

from aughor.orgsettings import store as S


def _org(monkeypatch, *, currency: str = "", industry: str = "") -> None:
    """Pin the effective workspace settings the resolvers read."""
    class _S:
        currency_code = currency
        company_name = ""
        website = ""
        hq_location = ""
        fiscal_year_start_month = 1
    _S.industry = industry
    monkeypatch.setattr(S, "effective_settings", lambda *a, **k: _S())


# ── the figure's unit ────────────────────────────────────────────────────────────

def test_the_datas_currency_wins_over_the_orgs(monkeypatch):
    """The live defect, as a test. A EUR workspace reading a USD warehouse must print
    dollars, because no step between the two converted anything.

    The mutation this kills is the previous line of code, `eff or profile_currency` — it
    returns "EUR" here and is exactly what shipped the euro-signed dollar chart.
    """
    _org(monkeypatch, currency="EUR")
    assert S.resolve_currency("USD") == "USD"


def test_the_org_applies_when_the_data_declares_nothing(monkeypatch):
    """Not a reversal of the org setting — a narrowing. With no claim about the data, the
    declared reporting currency is the best statement available."""
    _org(monkeypatch, currency="EUR")
    assert S.resolve_currency("") == "EUR"


def test_usd_when_neither_says_anything(monkeypatch):
    _org(monkeypatch, currency="")
    assert S.resolve_currency("") == "USD"


@pytest.mark.parametrize("raw,expected", [("gbp", "GBP"), ("  jpy  ", "JPY"), ("", "EUR")])
def test_the_datas_code_is_normalised_before_it_wins(monkeypatch, raw, expected):
    """A lowercase or padded code from a store is still a declaration; only a genuinely
    empty one falls through to the org."""
    _org(monkeypatch, currency="EUR")
    assert S.resolve_currency(raw) == expected


# ── what must NOT have changed ───────────────────────────────────────────────────

def test_industry_still_lets_the_org_win(monkeypatch):
    """The guard against over-correcting. An industry is a claim about the ORGANISATION and
    needs nothing converted to be true, so the user's "org setting is authoritative" choice
    stands there untouched. Inverting both would have passed every test above."""
    _org(monkeypatch, industry="Luxury Fashion E-commerce")
    assert S.resolve_industry("Multi-Category E-commerce Retail") == "Luxury Fashion E-commerce"


def test_the_org_still_states_its_own_reporting_currency(monkeypatch):
    """`org_context` describes the organisation, and "reports in EUR" is TRUE of it however
    theLook's dollars are labelled. It reads the setting directly, so this sentence must
    survive the change — losing it would trade one wrong statement for a missing one."""
    _org(monkeypatch, currency="EUR")
    assert "reports in EUR" in S.org_context()
