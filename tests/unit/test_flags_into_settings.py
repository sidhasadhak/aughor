"""Flags into settings (ROADMAP §3.65, the user, 2026-10-28: "not having any feature flags at all.. most of it comes as
a default feature like always on and cannot be turned off.. and some of them can be turned on off based on the
requirements of the organisation").

A flag that is part of the platform is on whatever a saved override says, is never offered as a switch, and refuses a
change by name; the four choices an organisation makes are its admin's settings, off by default, reading the former
flag's variable only while never set.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.kernel import flags as F
from aughor.orgsettings import allows as A
from aughor.orgsettings.store import load_org_settings, save_org_settings


def test_an_always_on_flag_is_on_whatever_a_saved_override_says(monkeypatch):
    monkeypatch.delenv("AUGHOR_STATE_BACKUPS", raising=False)
    F.Ledger.default().kv_put(F._STORE, "state.backups", False)   # a row an operator saved before 2026-10-28
    try:
        assert F.flag_enabled("state.backups") is True and F.flag_state("state.backups") == "on"
        row = F.list_flags()["state.backups"]
        assert row["value"] is True and row["override"] is None and row["disposition"] == "always_on"
    finally:
        F.Ledger.default().kv_put(F._STORE, "state.backups", None)


def test_an_always_on_flag_refuses_a_change_by_name():
    with pytest.raises(F.AlwaysOn, match="state.backups is part of the platform now"):
        F.set_flag("state.backups", False)
    with pytest.raises(F.AlwaysOn):
        F.clear_flag("state.backups")


@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


def test_the_flags_door_refuses_an_always_on_flag_and_still_switches_one_that_is_not(client):
    r = client.put("/system/flags/state.backups", json={"state": "off"})
    assert r.status_code == 409 and "part of the platform now" in r.text
    r = client.put("/system/flags/monitors.recovery", json={"state": "on"})
    assert r.status_code == 200 and r.json()["value"] is True
    client.put("/system/flags/monitors.recovery", json={"state": "auto"})


def test_until_its_off_path_is_deleted_an_explicit_falsy_variable_still_turns_one_off(monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_BACKUPS", "0")
    assert F.flag_enabled("state.backups") is False
    monkeypatch.delenv("AUGHOR_STATE_BACKUPS")
    assert F.flag_enabled("state.backups") is True


#: Stage 2 (ROADMAP §3.65): flags made unconditional — their off paths deleted, gone from the registry.
UNCONDITIONAL = {
    # the dashboards area, 2026-10-28
    "dashboard.app_pieces", "dashboard.breakdowns", "dashboard.builder", "dashboard.composed", "dashboard.marks",
    "dashboard.queries", "dashboard.questions", "dashboard.shapes", "dashboard.variables", "dashboard.wiring",
    "ontology.dashboard_pieces", "ontology.object_dashboards", "packs.dashboard_templates", "canvas.ask_about_chosen",
    # the sheets area, 2026-10-28
    "sheets.core", "sheets.grid", "sheets.views", "sheets.combine", "sheets.everywhere", "sheets.chat",
    "sheets.model_columns", "sheets.sharing",
}


def test_every_flag_that_was_on_is_always_on_and_the_settings_left_the_registry():
    assert len(F.ALWAYS_ON) == 63 - len(UNCONDITIONAL) and all(F.ALWAYS_ON.values())
    for gone in ("aggregates.share", "semops.jev_cheap_tier", "govern.justifications", "agents.testing_centre",
                 "agents.learning_loop"):
        assert gone not in F.FLAG_ENV, gone
    for gone in UNCONDITIONAL:
        assert gone not in F.FLAG_ENV and gone not in F.ALWAYS_ON and gone not in F.FLAG_META, gone


@pytest.fixture
def settings():
    before = load_org_settings()
    yield
    save_org_settings(before)


@pytest.mark.parametrize("setting", sorted(A.FORMER_ENV))
def test_a_setting_is_off_until_an_admin_sets_it(setting, settings, monkeypatch):
    for var in A.FORMER_ENV[setting]:
        monkeypatch.delenv(var, raising=False)
    assert getattr(load_org_settings(), setting) is None and A.allows(setting) is False
    save_org_settings(load_org_settings().model_copy(update={setting: True}))
    assert A.allows(setting) is True


@pytest.mark.parametrize("setting", sorted(A.FORMER_ENV))
def test_while_unset_the_former_variable_answers_and_once_set_the_setting_does(setting, settings, monkeypatch):
    var = A.FORMER_ENV[setting][-1]
    monkeypatch.setenv(var, "1")
    assert A.allows(setting) is True
    save_org_settings(load_org_settings().model_copy(update={setting: False}))
    assert A.allows(setting) is False


def test_an_unknown_setting_is_refused():
    with pytest.raises(KeyError):
        A.allows("share_everything")
