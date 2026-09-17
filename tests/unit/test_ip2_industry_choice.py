"""IP-2 — the industries chosen at install narrow every industry read, and change later without a restart.

ROADMAP §3.17 "Chosen at install"; §6 item 21, answer 1: skipping keeps every shipped package and detects each
connection's industry, and a pick narrows what a profile may resolve to. The installer's half — the question,
the flag and where it writes — is `tests/unit/test_installer.py`; this file is what the API does with the answer.
"""
from __future__ import annotations

import json

import pytest

from aughor.business_profile import metric_kb
from aughor.packs import industry_choice
from aughor.packs.industry_choice import UnknownIndustry, read_choice, readable_industries, write_choice
from aughor.playbook.models import PlaybookEntry

SHIPPED = ["airline", "food_delivery", "logistics", "manufacturing", "retail", "saas"]


@pytest.fixture()
def choice(tmp_path, monkeypatch):
    """Each test gets its own choice file: a choice written to the session's shared one would narrow
    every test that runs after it."""
    path = tmp_path / "state" / "industries.json"
    monkeypatch.setenv("AUGHOR_INDUSTRIES_FILE", str(path))
    return path


def test_with_no_choice_every_shipped_industry_is_available_as_before(choice):
    from aughor.packs.knowledge import industry_kbs

    assert not choice.exists() and not read_choice().chosen
    assert list(industry_choice.available_industries()) == SHIPPED
    assert readable_industries(None) is None                          # an unscoped read filters nothing
    assert metric_kb.load_industry_kbs() == industry_kbs()
    assert metric_kb.industry_id("Commercial airline") == "airline"


def test_a_choice_narrows_what_an_industry_text_resolves_to(choice):
    write_choice(["retail", "saas"], source="test")
    assert [kb["id"] for kb in metric_kb.load_industry_kbs()] == ["retail", "saas"]
    assert metric_kb.industry_id("Commercial airline") == ""          # known, not kept: shared knowledge only
    assert metric_kb.industry_id("B2B SaaS") == "saas"
    assert readable_industries(None) == {"", "retail", "saas"}
    assert readable_industries("retail") == {"", "retail"} and readable_industries("") == {""}


def test_none_keeps_only_what_every_industry_shares(choice):
    write_choice([], source="test")
    assert read_choice().chosen and read_choice().industries == ()
    assert metric_kb.load_industry_kbs() == ()
    assert readable_industries(None) == {""}


def test_a_read_that_knows_nothing_about_its_connection_sees_only_the_chosen_industries(choice, monkeypatch):
    from aughor.playbook import retriever

    plays = [PlaybookEntry(id=f"p_{kb}", source_kb_id=kb, trigger_metric="churn rate", trigger_condition="c",
                           recommendation="r", status="active")
             for kb in ("air_load_factor", "ec_return_rate", "customer_churn_analysis")]
    monkeypatch.setattr(retriever, "list_active_entries", lambda: plays)
    read = lambda: sorted(p.id for p in retriever.retrieve_for_metric_and_phases(["churn rate"], limit=9))  # noqa: E731
    assert read() == ["p_air_load_factor", "p_customer_churn_analysis", "p_ec_return_rate"]
    write_choice(["retail"], source="test")
    assert read() == ["p_customer_churn_analysis", "p_ec_return_rate"]


def test_rule_outs_name_only_a_chosen_industrys_metrics(choice):
    from aughor.playbook.rule_outs import match_metric

    assert [m.kb_id for m in match_metric("passenger load factor", None)] == ["air_load_factor"]
    write_choice(["retail"], source="test")
    assert match_metric("passenger load factor", None) == ()
    assert [m.kb_id for m in match_metric("total GMV", None)] == ["ec_gmv"]


def test_a_changed_choice_reaches_a_running_process(choice):
    """Settings and `aughor industries` write while the API runs: the cached vocabulary follows the file."""
    tokens = lambda: {t for t, _label, _formula in metric_kb.metric_vocabulary("")}  # noqa: E731
    assert "repeatpurchaserate" in tokens() and "availableseatkilometers" in tokens()   # retail's, airline's
    write_choice(["airline"], source="test")
    assert "repeatpurchaserate" not in tokens() and "availableseatkilometers" in tokens()
    write_choice(None, source="test")
    assert "repeatpurchaserate" in tokens()


def test_an_id_no_package_carries_is_refused_on_write_and_ignored_on_read(choice):
    with pytest.raises(UnknownIndustry, match="no industry package carries banking"):
        write_choice(["retail", "banking"], source="test")
    assert not choice.exists()
    choice.parent.mkdir(parents=True)
    choice.write_text(json.dumps({"industries": ["retail", "banking"]}), encoding="utf-8")
    now = read_choice()
    assert (now.industries, now.ignored) == (("retail",), ("banking",))


@pytest.mark.parametrize("content", ["{not json", "[]", '{"industries": "retail"}'])
def test_an_unreadable_choice_keeps_every_industry_and_says_why(choice, content):
    choice.parent.mkdir(parents=True)
    choice.write_text(content, encoding="utf-8")
    now = read_choice()
    assert not now.chosen and now.problem
    assert list(industry_choice.available_industries()) == SHIPPED


def test_the_file_is_written_whole_in_the_shape_the_installer_writes(choice):
    write_choice(["saas", "retail", "retail"], source="settings")
    assert json.loads(choice.read_text(encoding="utf-8"))["industries"] == ["retail", "saas"]
    assert sorted(p.name for p in choice.parent.iterdir()) == ["industries.json"]      # no temp file left
    assert industry_choice.describe(read_choice()) == "Retail and e-commerce, SaaS"


def test_a_changed_choice_drops_only_the_profiles_that_resolve_differently(choice, tmp_path, monkeypatch):
    from aughor.business_profile import store

    monkeypatch.setattr(store, "_DATA_DIR", tmp_path / "profiles")
    for key, industry in {"air": "Commercial airline", "shop": "E-commerce retail",
                          "clinic": "Hospital group", "blank": ""}.items():
        store._family().put(key, {"profile": {"industry": industry}, "recipes": []})

    assert metric_kb.refresh_profiles_for_choice(None, ("retail",)) == 1               # the airline one moves
    assert store._family().keys_with_prefix("") == ["blank", "clinic", "shop"]
    assert metric_kb.refresh_profiles_for_choice(("retail",), ("retail", "saas")) == 0  # nothing moves


def test_settings_reads_and_changes_the_choice(choice, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.business_profile import store

    monkeypatch.setattr(store, "_DATA_DIR", tmp_path / "profiles")
    store._family().put("air", {"profile": {"industry": "Airline"}, "recipes": []})
    client = TestClient(app)

    got = client.get("/org-settings/industries").json()
    assert got["industries"] is None and [i["id"] for i in got["shipped"]] == SHIPPED
    assert {"id": "retail", "name": "Retail and e-commerce"}.items() <= got["shipped"][4].items()

    put = client.put("/org-settings/industries", json={"industries": ["retail"]})
    assert put.status_code == 200, put.text
    assert (put.json()["industries"], put.json()["source"], put.json()["profiles_refreshed"]) == (["retail"], "settings", 1)
    assert client.get("/org-settings/industries").json()["industries"] == ["retail"]

    refused = client.put("/org-settings/industries", json={"industries": ["banking"]})
    assert refused.status_code == 422 and "banking" in refused.json()["detail"]
    assert client.put("/org-settings/industries", json={"industries": None}).json()["industries"] is None


def test_the_cli_lists_and_changes_the_choice(choice, tmp_path, monkeypatch):
    from click.testing import CliRunner

    from aughor import cli
    from aughor.business_profile import store

    monkeypatch.setattr(store, "_DATA_DIR", tmp_path / "profiles")
    runner = CliRunner()
    listed = runner.invoke(cli.cli, ["industries"])
    assert listed.exit_code == 0 and "Retail and e-commerce" in listed.output
    assert "every industry, detected per connection" in listed.output

    assert runner.invoke(cli.cli, ["industries", "retail", "saas"]).exit_code == 0
    assert (read_choice().industries, read_choice().source) == (("retail", "saas"), "cli")
    assert runner.invoke(cli.cli, ["industries", "Food delivery,", "2"]).exit_code == 0
    assert read_choice().industries == ("food_delivery",)
    assert runner.invoke(cli.cli, ["industries", "none"]).exit_code == 0 and read_choice().industries == ()
    assert runner.invoke(cli.cli, ["industries", "all"]).exit_code == 0 and not read_choice().chosen

    refused = runner.invoke(cli.cli, ["industries", "banking"])
    assert refused.exit_code == 1 and "No industry package is called banking." in refused.output
    assert not read_choice().chosen
