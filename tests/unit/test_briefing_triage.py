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


def test_currency_is_eur_in_prompt(monkeypatch):
    out = _run(monkeypatch)
    assert out["currency_code"] == "EUR"
    assert "€" in _StubProvider.last_user


def test_org_currency_overrides_profile_in_brief(monkeypatch):
    # A set org currency (GBP) is AUTHORITATIVE over the profile's inferred EUR — the
    # brief reports GBP and the narrator is instructed in £, not the inferred €.
    _orgstore.save_org_settings(OrgSettings(currency_code="GBP"))
    out = _run(monkeypatch)
    assert out["currency_code"] == "GBP"
    assert "£" in _StubProvider.last_user
    assert "€" not in _StubProvider.last_user


def test_org_currency_rewrites_dollar_figures_in_narrative(monkeypatch):
    # The post-synthesis $→symbol rewrite uses the resolved org currency, so a narrator
    # that emits "$1.2M" is normalised to "£1.2M" in the served brief.
    _orgstore.save_org_settings(OrgSettings(currency_code="GBP"))

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
    assert "£1.2M" in out["narrative"]
    assert "$" not in out["narrative"]
