"""A Briefing's money symbol is the currency a PERSON confirmed for its dataset (2026-10-23).

Before, the symbol was the workspace's currency override, then the app's, then the profile's
inferred code, then USD — so an org preference relabelled warehouse figures it never converted
(2026-09-23) and a model's guess printed as fact (the Olist run, Gap 14: "$" over reais). Now
`_profile_signals` asks one thing, `figure_currency(connection, schema)`: a person's confirmation
for that dataset, or nothing — and nothing is a plain amount.
"""
from aughor.knowledge import briefing as B


def test_the_symbol_is_the_datasets_confirmed_currency(monkeypatch):
    seen = {}

    def _confirmed(conn_id, schema=None):
        seen.update(conn=conn_id, schema=schema)
        return "EUR"

    monkeypatch.setattr("aughor.orgsettings.figure_currency", _confirmed)
    _tokens, sym = B._profile_signals({"currency_code": "USD", "north_star_metrics": []}, "c1", "olist")
    assert seen == {"conn": "c1", "schema": "olist"}       # asked about THIS dataset
    assert sym == "€"                                       # the person's EUR, not the profile's USD


def test_an_unconfirmed_currency_is_no_symbol_not_the_profiles_guess(monkeypatch):
    monkeypatch.setattr("aughor.orgsettings.figure_currency", lambda conn_id, schema=None: "")
    _tokens, sym = B._profile_signals({"currency_code": "BRL"}, "c1", "olist")
    assert sym == ""
