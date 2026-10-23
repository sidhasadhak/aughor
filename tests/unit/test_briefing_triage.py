"""End-to-end (real selection path) test for the CEO-grade brief.

Runs the ACTUAL ``generate_narrative`` over the five real missimi findings — only the
LLM narrator is stubbed — and asserts the triage flips the lead off the noise-level
ROAS split, suppresses the impossible turnover, demotes the anti-causal correlation,
and tells the narrator to write in the business's currency.
"""
import pytest

import aughor.llm.provider as provider_mod
from aughor.knowledge.briefing import BriefingNarrative, generate_narrative
from aughor.orgsettings import store as _orgstore
from aughor.orgsettings.models import OrgSettings


@pytest.fixture(autouse=True)
def _isolate_org_settings(tmp_path, monkeypatch):
    # Briefing currency resolves through org settings (override-wins), so isolate the
    # singleton per test — these assertions must not depend on a real data/org_settings.json.
    monkeypatch.setattr(_orgstore, "_PATH", tmp_path / "org_settings.json")


# The five findings exactly as the old brief surfaced them (see the briefing screenshot).
MISSIMI = {
    "DTC Beauty": [
        {"id": "f-roas", "domain": "DTC Beauty", "angle": "Growth", "confidence": 0.7, "novelty": 4,
         "finding": ("ROAS by channel differs between acquisition and retention campaigns: acquisition "
                     "shows higher ROAS in email_crm (6.30 vs 5.92), display (4.72 vs 5.12), affiliate "
                     "(4.42 vs 4.46), and paid_search (4.02 vs 3.65)."),
         "sql": "SELECT channel, campaign_type, roas FROM ..."},
        {"id": "f-turnover", "domain": "DTC Beauty", "angle": "Operations", "confidence": 0.7, "novelty": 3,
         "finding": ("Inventory turnover is significantly higher in mass-tier products (skincare_face at "
                     "3600.37) compared to premium-tier (skincare_face at 409.86)."),
         "sql": "SELECT tier, inventory_turnover FROM ..."},
        {"id": "f-stockout", "domain": "DTC Beauty", "angle": "Supply Chain", "confidence": 0.7, "novelty": 3,
         "finding": ("Stockout frequency decreases as lead_time_days increases from 5 to 14 days, with "
                     "notable drops to near-zero at lead times of 12, 21, 22, 25, and 26 days."),
         "sql": "SELECT lead_time_days, stockout_freq FROM ..."},
        {"id": "f-repeat", "domain": "DTC Beauty", "angle": "Retention", "confidence": 0.5, "novelty": 3,
         "finding": ("Fragrance for women has the highest repeat-purchase rate (16.87%) among categories "
                     "with the lowest return rate proxy (review score deviation of 0.0044)."),
         "sql": "SELECT category, repeat_purchase_rate FROM ..."},
        {"id": "f-affiliate", "domain": "DTC Beauty", "angle": "Growth", "confidence": 0.7, "novelty": 3,
         "finding": ("Affiliate marketing drives the highest share of new-customer orders at 86.8%, "
                     "followed closely by display (83.3%) and paid search (83.3%)."),
         "sql": "SELECT channel, new_customer_share FROM ..."},
    ]
}

PROFILE = {
    "north_star_metrics": [
        {"name": "Gross Margin Rate"}, {"name": "Repeat Purchase Rate"},
        {"name": "Average Order Value"}, {"name": "Review Sentiment"},
    ],
    "currency_code": "EUR",
}


class _StubProvider:
    """Captures the narrator prompt and returns a canned narrative citing [1]."""
    last_user = None

    def complete(self, system, user, response_model=None, temperature=0.0):
        _StubProvider.last_user = user
        return BriefingNarrative(
            narrative="Retention is the standout signal [1].",
            citations=[{"ref": "1", "insight_id": "", "domain": "DTC Beauty",
                        "angle": "Retention", "finding": ""}],
            headline_theme="Retention Leads Growth",
        )


def _run(monkeypatch):
    monkeypatch.setattr(provider_mod, "get_provider", lambda *_a, **_k: _StubProvider())
    return generate_narrative(MISSIMI, patterns=[], connection_id="missimi", profile=PROFILE)


def test_impossible_turnover_is_suppressed(monkeypatch):
    out = _run(monkeypatch)
    {h["finding"][:20]: h for h in out["held_back"]}
    turnover = next(h for h in out["held_back"] if "turnover" in h["finding"].lower())
    assert turnover["severity"] == "implausible"


def test_anti_causal_correlation_is_demoted(monkeypatch):
    out = _run(monkeypatch)
    stockout = next(h for h in out["held_back"] if "Stockout" in h["finding"])
    assert stockout["severity"] == "confound"


def test_two_signals_held_back_rest_synthesised(monkeypatch):
    out = _run(monkeypatch)
    assert len(out["held_back"]) == 2          # turnover (suppressed) + stockout (demoted)
    # The narrator prompt carries only the 3 trusted findings, none of the held-back two.
    prompt = _StubProvider.last_user
    assert "3600.37" not in prompt and "Stockout frequency" not in prompt


def test_lead_flips_off_the_noise_level_roas_split(monkeypatch):
    _run(monkeypatch)
    prompt = _StubProvider.last_user
    # The "[1]" lead line must NOT be the ROAS split (its contrasts are noise: 4.42 vs 4.46).
    next(ln for ln in prompt.splitlines() if ln.strip().startswith("[1]"))
    after_lead = prompt.split("[1]", 1)[1].split("[2]", 1)[0]
    assert "ROAS by channel" not in after_lead
    # It should be the watched-metric finding (repeat-purchase rate).
    assert "repeat-purchase rate" in after_lead


def _confirmed(monkeypatch, code: str) -> None:
    """A person confirmed ``code`` for the dataset (2026-10-23: only that labels a figure)."""
    monkeypatch.setattr("aughor.orgsettings.figure_currency", lambda conn_id, schema=None: code)


def test_a_confirmed_currency_is_in_prompt(monkeypatch):
    _confirmed(monkeypatch, "EUR")
    out = _run(monkeypatch)
    assert out["currency_code"] == "EUR"
    assert "€" in _StubProvider.last_user


def test_the_brief_prints_no_currency_nobody_confirmed(monkeypatch):
    """INVERTED twice. 2026-09-23: an org GBP no longer relabelled the data's EUR (nothing converts).
    2026-10-23 (the Olist study's Gap 14, the user's decision): the profile's EUR is the model's
    inference, a proposal — until a person confirms a currency for the dataset the brief prints plain
    amounts and the narrator is told to say so, never a default "$" and never the guess."""
    _orgstore.save_org_settings(OrgSettings(currency_code="GBP"))
    out = _run(monkeypatch)                                   # PROFILE says EUR; nothing confirmed
    assert out["currency_code"] == ""
    prompt = _StubProvider.last_user
    assert "No person has confirmed this data's currency" in prompt
    assert "€" not in prompt and "£" not in prompt


@pytest.mark.parametrize("confirmed, expected", [("EUR", "€1.2M"), ("", "1.2M")])
def test_dollar_figures_follow_the_confirmed_currency(monkeypatch, confirmed, expected):
    # The post-synthesis "$" rewrite uses the dataset's CONFIRMED currency: a confirmed EUR turns
    # "$1.2M" into "€1.2M"; none drops the "$" — the amount stands plain, never in dollars it was
    # never shown to be in. The org's declared GBP plays no part.
    _orgstore.save_org_settings(OrgSettings(currency_code="GBP"))
    _confirmed(monkeypatch, confirmed)

    class _DollarNarrator:
        def complete(self, system, user, response_model=None, temperature=0.0):
            return BriefingNarrative(
                narrative="Revenue rose to $1.2M this quarter [1].",
                citations=[{"ref": "1", "insight_id": "", "domain": "DTC Beauty",
                            "angle": "Retention", "finding": ""}],
                headline_theme="Growth",
            )

    monkeypatch.setattr(provider_mod, "get_provider", lambda *_a, **_k: _DollarNarrator())
    out = generate_narrative(MISSIMI, patterns=[], connection_id="missimi", profile=PROFILE)
    assert expected in out["narrative"]
    assert "$" not in out["narrative"]


# ── col_types → narrative: a non-additive aggregate is held back BEFORE synthesis ──────
# A grounded-but-void finding: SUM over a VARCHAR fiscal-year label. DuckDB coerces the
# year-strings and sums them, so the query "succeeds" with a big, meaningless number that
# used to headline the brief. The type guard (knowledge.triage check 0) suppresses it — but
# ONLY when generate_narrative is given the connection's column types (the #182 wiring that
# stamped the cards, now threaded into the narrator's own selection path).
_TYPE_VOID = {
    "Customer": [
        {"id": "f-signup", "domain": "Customer", "angle": "Growth", "confidence": 0.7, "novelty": 4,
         "finding": "Signups total 2,493,788 across the base, concentrated in the enterprise tier.",
         "sql": "SELECT tier, SUM(signup_fy) AS signups FROM customers GROUP BY tier"},
        {"id": "f-clean", "domain": "Customer", "angle": "Retention", "confidence": 0.6, "novelty": 3,
         "finding": "Repeat-purchase revenue reached 4.1M among returning customers.",
         "sql": "SELECT SUM(revenue) FROM orders"},
    ]
}
_COL_TYPES = {"signup_fy": "VARCHAR", "customers.signup_fy": "VARCHAR",
              "revenue": "DECIMAL(18,2)", "orders.revenue": "DECIMAL(18,2)"}


def test_col_types_suppress_sum_over_varchar_before_the_narrator(monkeypatch):
    monkeypatch.setattr(provider_mod, "get_provider", lambda *_a, **_k: _StubProvider())
    out = generate_narrative(_TYPE_VOID, patterns=[], connection_id="c",
                             profile=PROFILE, col_types=_COL_TYPES)
    signup = next(h for h in out["held_back"] if "Signups total" in h["finding"])
    assert signup["severity"] == "implausible"
    assert "signup_fy" in signup["reason"]          # names the offending column
    # The narrator prompt never carries the type-void number → the AI prose can't cite it.
    assert "2,493,788" not in _StubProvider.last_user
    # The clean SUM(revenue) finding (numeric column) is untouched.
    assert not any("Repeat-purchase revenue" in h["finding"] for h in out["held_back"])


def test_narrative_type_guard_no_ops_without_col_types(monkeypatch):
    # Omitting col_types must leave behaviour byte-identical to before the wiring: the
    # aggregate-type guard simply cannot fire, so the SUM(varchar) finding is NOT held back
    # on type grounds. Guards the "omit → no regression" contract for every other caller.
    monkeypatch.setattr(provider_mod, "get_provider", lambda *_a, **_k: _StubProvider())
    out = generate_narrative(_TYPE_VOID, patterns=[], connection_id="c", profile=PROFILE)
    assert not any("Signups total" in h["finding"] for h in out["held_back"])
