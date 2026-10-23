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

* (2026-10-23) only a PERSON's confirmation labels a figure, per dataset; the profile's inferred
  code is a proposal and the org's preference describes the organisation — neither labels a number;
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


# ── the figure's unit: a person's confirmation, per dataset (2026-10-23) ──────────

PROFILES = {("workspace", "olist"): "BRL", ("workspace", "main"): "EUR", ("8233e4fd", None): "USD"}


@pytest.fixture
def profiles(monkeypatch, tmp_path):
    """The profiles' INFERRED codes — Olist's reais and a franchise's euros on ONE connection, as
    measured on the user's instance (2026-10-23), and theLook's dollars on another. Each test keeps
    its confirmations in its own settings file."""
    import aughor.business_profile.store as pstore
    import aughor.db.registry as registry
    monkeypatch.setattr(registry, "_SETTINGS_PATH", tmp_path / "connection_settings.json")
    monkeypatch.setattr(pstore, "load_raw", lambda conn, schema=None: (
        {"profile": {"currency_code": PROFILES[(conn, schema)], "confidence": 0.97}}
        if (conn, schema) in PROFILES else None))
    yield


def test_an_inferred_currency_labels_no_figure(profiles, monkeypatch):
    """The Olist study's Gap 14, and the user's decision: the profile's code is the MODEL's inference
    — a proposal beside a Confirm door, never the unit in front of a number. Until a person confirms,
    a figure is a plain amount (no "R$", no default "$")."""
    _org(monkeypatch, currency="USD")
    got = S.data_currency("workspace", "olist", inferred="BRL")
    assert (got["code"], got["status"], got["inferred"]) == ("", "inferred", "BRL")
    assert S.figure_currency("workspace", "olist") == ""
    assert S.currency_symbol(S.figure_currency("workspace", "olist")) == ""      # never "$"


def test_a_confirmation_labels_its_own_dataset_and_no_other(profiles):
    """Per DATASET, not per workspace: one connection held Olist in BRL and `main` in EUR, so a
    workspace currency would have printed one of them in the other's money."""
    S.confirm_currency("workspace", "olist", "brl", actor="amit")
    assert S.figure_currency("workspace", "olist") == "BRL"
    assert S.figure_currency("workspace", "main") == ""                      # still unconfirmed
    from aughor.routers import profile as R
    assert R.get_dataset_currency("workspace", "main")["inferred"] == "EUR"
    held = S.data_currency("workspace", "olist")
    assert (held["status"], held["confirmed_by"]) == ("confirmed", "amit") and held["confirmed_at"]


def test_a_person_may_state_another_currency_and_clear_it(profiles):
    S.confirm_currency("8233e4fd", None, "USD", actor="amit")
    S.confirm_currency("8233e4fd", None, "EUR", actor="amit")
    from aughor.db.registry import get_connection_settings
    assert get_connection_settings("8233e4fd")[S.CURRENCIES_KEY][""]["was"] == "USD"   # the change is kept
    assert S.figure_currency("8233e4fd") == "EUR"
    S.confirm_currency("8233e4fd", None, "", actor="amit")
    assert S.data_currency("8233e4fd", inferred="USD")["status"] == "inferred"
    with pytest.raises(ValueError, match="three-letter ISO 4217"):
        S.confirm_currency("8233e4fd", None, "dollars", actor="amit")


def test_the_org_currency_labels_no_figure(profiles, monkeypatch):
    """2026-09-23 stopped the org's preference relabelling the data's own currency (nothing converts).
    It no longer fills in either: an org GBP over an unconfirmed dataset is still a plain amount."""
    _org(monkeypatch, currency="GBP")
    assert S.figure_currency("workspace", "olist") == ""
    assert S.figure_currency("nowhere", None) == ""
    assert S.data_currency("nowhere")["status"] == "unknown"


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


# ── the doors ────────────────────────────────────────────────────────────────────

def test_a_person_confirms_through_the_profile_door(profiles, monkeypatch):
    """`PUT /business-profile/currency` writes the person's word with who said it; `GET` reads the
    proposal and the confirmation the Profile page shows."""
    from fastapi import HTTPException

    from aughor.routers import profile as R
    monkeypatch.setattr("aughor.security.authz.caller", lambda: "amit")
    before = R.get_dataset_currency("workspace", "olist")
    assert (before["status"], before["inferred"], before["code"]) == ("inferred", "BRL", "")
    after = R.put_dataset_currency(R._CurrencyBody(code="BRL"), "workspace", "olist")
    assert (after["status"], after["code"], after["confirmed_by"]) == ("confirmed", "BRL", "amit")
    with pytest.raises(HTTPException) as refused:
        R.put_dataset_currency(R._CurrencyBody(code="reais"), "workspace", "olist")
    assert refused.value.status_code == 422


@pytest.mark.parametrize("value, said", [(13494400.74, "13,494,400.74"), (13494400.0, "13,494,400"),
                                         (0.142134, "0.1421"), (2.5, "2.50")])
def test_a_reading_is_never_in_scientific_notation(value, said):
    """Gap 23: the approval panel read Olist's GMV as "1.34944e+07" where the decision was taken."""
    from aughor.semantic.definition_report import plain_reading
    assert plain_reading(value) == said
