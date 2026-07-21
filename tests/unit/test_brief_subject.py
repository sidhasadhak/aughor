"""The brief's SUBJECT is the dataset, not the organization reading it.

Live symptom: a Netflix title-catalog brief opened *"LuxExperience has aggressively scaled
content production by over 1,200%…"*. Org settings (`company_name`, `hq_location`, `industry`)
are WORKSPACE-GLOBAL, so every schema's brief was stamped with one company — and since the
narrator was given the org's identity and never the dataset's, it attributed the data to the org.

The per-schema `BusinessProfile` already carries `industry` / `business_model` / `summary`; it
was loaded for the right scope and then dropped (only its north-star tokens and currency ever
reached the prompt). This just stops throwing the rest away, and reframes the org block as the
reader rather than the owner.
"""
from __future__ import annotations

from aughor.knowledge.briefing import _dataset_subject


class _Profile:
    industry = "Media & Streaming Content Catalog"
    business_model = "ad-supported"
    summary = "A catalog of Netflix titles with ratings, countries and release years."


def test_subject_block_carries_the_dataset_characterization():
    out = _dataset_subject(_Profile())
    assert "Media & Streaming Content Catalog" in out
    assert "ad-supported" in out
    assert "catalog of Netflix titles" in out


def test_subject_block_tells_the_narrator_not_to_attribute_to_the_org():
    """The instruction is the guard — without it the model conflates the two identities."""
    out = _dataset_subject(_Profile()).lower()
    assert "this dataset" in out
    assert "do not attribute" in out


def test_dict_profiles_work_too():
    """The profile arrives as a model OR a dict depending on the caller."""
    out = _dataset_subject({"industry": "DTC Beauty", "summary": "Skincare storefront."})
    assert "DTC Beauty" in out
    assert "Skincare storefront." in out


def test_partial_profile_still_produces_a_subject():
    assert "Retail" in _dataset_subject({"industry": "Retail"})
    assert "Just a summary." in _dataset_subject({"summary": "Just a summary."})


def test_no_profile_is_silent_not_invented():
    """An unprofiled schema must add NOTHING — a fabricated subject would be worse than none."""
    for empty in (None, {}, {"industry": "", "summary": "", "business_model": ""}):
        assert _dataset_subject(empty) == ""


def test_missing_attributes_do_not_raise():
    class Bare:
        pass

    assert _dataset_subject(Bare()) == ""


# ── The org block is the READER, not the subject ──────────────────────────────


def test_org_block_is_labelled_as_the_reader(monkeypatch):
    from aughor.orgsettings import store

    monkeypatch.setattr(store, "effective_settings", lambda ws=None: store.OrgSettings(
        company_name="LuxExperience", hq_location="Munich", industry="Ecommerce",
        currency_code="EUR",
    ))
    out = store.org_context(None)
    assert out.startswith("ORGANIZATION reading this brief:")
    assert "LuxExperience" in out


def test_unconfigured_org_still_contributes_nothing(monkeypatch):
    from aughor.orgsettings import store

    monkeypatch.setattr(store, "effective_settings", lambda ws=None: store.OrgSettings())
    assert store.org_context(None) == ""
