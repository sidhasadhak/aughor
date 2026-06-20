"""Org/workspace settings — singleton persistence, hybrid resolution, override-wins.

The app-level OrgSettings is a JSON singleton; a Workspace may override a subset.
effective_settings() merges with precedence (workspace override > app default), and
resolve_currency/resolve_industry make an explicitly-set org value AUTHORITATIVE over
the per-connection BusinessProfile inference (the user's chosen semantics). Both
stores are path-isolated per test so the real data/ dir is never touched.
"""
import pytest

from aughor.orgsettings import store as S
from aughor.orgsettings.models import OrgSettings
from aughor.workspace import store as WS


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_PATH", tmp_path / "org_settings.json")
    monkeypatch.setattr(WS, "_DB_PATH", tmp_path / "workspaces.db")


class TestSingleton:
    def test_defaults_when_unconfigured(self):
        s = S.load_org_settings()
        assert s.currency_code == "" and s.industry == "" and s.company_name == ""
        assert s.fiscal_year_start_month == 1

    def test_save_load_round_trip(self):
        S.save_org_settings(OrgSettings(company_name="Acme", currency_code="gbp", hq_location="London, UK"))
        s = S.load_org_settings()
        assert s.company_name == "Acme"
        assert s.currency_code == "GBP"      # normalized to upper
        assert s.hq_location == "London, UK"

    def test_currency_validator_rejects_bad_code(self):
        with pytest.raises(Exception):
            OrgSettings(currency_code="POUND")

    def test_malformed_file_falls_back_to_defaults(self, tmp_path):
        (tmp_path / "org_settings.json").write_text("{ not json")
        assert S.load_org_settings().currency_code == ""


class TestEffectiveSettings:
    def test_app_level_when_no_workspace(self):
        S.save_org_settings(OrgSettings(currency_code="EUR"))
        assert S.effective_settings().currency_code == "EUR"

    def test_workspace_override_beats_app(self):
        S.save_org_settings(OrgSettings(currency_code="USD", company_name="Acme"))
        ws = WS.create_workspace("WS-UK", settings_override={"currency_code": "GBP"})
        eff = S.effective_settings(ws.id)
        assert eff.currency_code == "GBP"    # override wins
        assert eff.company_name == "Acme"    # untouched field inherits app-level

    def test_empty_override_does_not_blank_app(self):
        S.save_org_settings(OrgSettings(currency_code="USD"))
        ws = WS.create_workspace("WS", settings_override={"currency_code": ""})
        assert S.effective_settings(ws.id).currency_code == "USD"

    def test_unknown_workspace_uses_app(self):
        S.save_org_settings(OrgSettings(currency_code="JPY"))
        assert S.effective_settings("nope").currency_code == "JPY"


class TestOverrideWins:
    def test_currency_org_set_beats_profile(self):
        S.save_org_settings(OrgSettings(currency_code="GBP"))
        assert S.resolve_currency("EUR") == "GBP"

    def test_currency_unset_falls_to_profile(self):
        assert S.resolve_currency("EUR") == "EUR"

    def test_currency_both_unset_defaults_usd(self):
        assert S.resolve_currency("") == "USD"

    def test_industry_org_set_beats_profile(self):
        S.save_org_settings(OrgSettings(industry="Commercial Aviation"))
        assert S.resolve_industry("DTC Beauty") == "Commercial Aviation"

    def test_industry_unset_falls_to_profile(self):
        assert S.resolve_industry("DTC Beauty") == "DTC Beauty"

    def test_workspace_currency_override_in_resolve(self):
        S.save_org_settings(OrgSettings(currency_code="USD"))
        ws = WS.create_workspace("WS", settings_override={"currency_code": "INR"})
        assert S.resolve_currency("EUR", workspace_id=ws.id) == "INR"


class TestWorkspaceOverridePersistence:
    def test_create_round_trips_override(self):
        ws = WS.create_workspace("WS", settings_override={"timezone": "Europe/London"})
        assert WS.get_workspace(ws.id).settings_override == {"timezone": "Europe/London"}

    def test_update_sets_override(self):
        ws = WS.create_workspace("WS")
        assert ws.settings_override == {}
        WS.update_workspace(ws.id, settings_override={"currency_code": "GBP"})
        assert WS.get_workspace(ws.id).settings_override == {"currency_code": "GBP"}

    def test_update_preserves_override_when_omitted(self):
        ws = WS.create_workspace("WS", settings_override={"industry": "Freight"})
        WS.update_workspace(ws.id, name="Renamed")   # no settings_override arg
        got = WS.get_workspace(ws.id)
        assert got.name == "Renamed"
        assert got.settings_override == {"industry": "Freight"}

    def test_default_override_is_empty_dict(self):
        ws = WS.create_workspace("Plain")
        assert WS.get_workspace(ws.id).settings_override == {}


class TestOrgContext:
    def test_empty_when_unconfigured(self):
        assert S.org_context() == ""

    def test_includes_identity_and_localization(self):
        S.save_org_settings(OrgSettings(
            company_name="Acme", hq_location="London, UK", website="https://acme.com",
            industry="DTC Beauty", currency_code="GBP",
        ))
        ctx = S.org_context()
        assert ctx.startswith("ORGANIZATION:")
        assert "Acme" in ctx and "London, UK" in ctx and "https://acme.com" in ctx
        assert "DTC Beauty" in ctx and "GBP" in ctx

    def test_partial_only_what_is_set(self):
        S.save_org_settings(OrgSettings(currency_code="EUR"))
        ctx = S.org_context()
        assert "reports in EUR" in ctx
        assert "HQ" not in ctx  # nothing else declared
