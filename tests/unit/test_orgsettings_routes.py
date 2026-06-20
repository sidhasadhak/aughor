"""Org-settings + workspace-override API routes.

Calls the route handlers directly (stores path-isolated) — the persistence/resolution
is covered by test_orgsettings; here we assert the thin request->store->response wiring:
PUT validates via the OrgSettings model, GET round-trips, /effective merges a workspace
override, and the workspace router threads settings_override through create/update.
"""
import pytest

from aughor.orgsettings import store as S
from aughor.orgsettings.models import OrgSettings
from aughor.routers import orgsettings as R
from aughor.routers import workspace as WR
from aughor.workspace import store as WS


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_PATH", tmp_path / "org_settings.json")
    monkeypatch.setattr(WS, "_DB_PATH", tmp_path / "workspaces.db")


class TestOrgSettingsRoutes:
    def test_get_defaults(self):
        body = R.get_org_settings()
        assert body["currency_code"] == "" and body["fiscal_year_start_month"] == 1

    def test_put_then_get_round_trip(self):
        out = R.put_org_settings(OrgSettings(company_name="Acme", currency_code="gbp"))
        assert out["company_name"] == "Acme" and out["currency_code"] == "GBP"  # validated+normalized
        assert R.get_org_settings()["currency_code"] == "GBP"

    def test_put_rejects_bad_currency(self):
        with pytest.raises(Exception):
            OrgSettings(currency_code="POUND")  # model validation guards the PUT body

    def test_effective_no_workspace_is_app(self):
        R.put_org_settings(OrgSettings(currency_code="EUR"))
        assert R.get_effective_settings(None)["currency_code"] == "EUR"

    def test_effective_with_workspace_override(self):
        R.put_org_settings(OrgSettings(currency_code="USD"))
        ws = WR.create_workspace_endpoint(
            WR.CreateWorkspaceRequest(name="UK", settings_override={"currency_code": "GBP"})
        )
        assert R.get_effective_settings(ws["id"])["currency_code"] == "GBP"


class TestWorkspaceOverrideRoute:
    def test_create_with_override(self):
        ws = WR.create_workspace_endpoint(
            WR.CreateWorkspaceRequest(name="WS", settings_override={"timezone": "Europe/London"})
        )
        assert ws["settings_override"] == {"timezone": "Europe/London"}

    def test_update_sets_override(self):
        ws = WR.create_workspace_endpoint(WR.CreateWorkspaceRequest(name="WS"))
        updated = WR.update_workspace_endpoint(
            ws["id"], WR.UpdateWorkspaceRequest(settings_override={"industry": "Freight"})
        )
        assert updated["settings_override"] == {"industry": "Freight"}
