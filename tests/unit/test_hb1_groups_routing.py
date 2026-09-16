"""HB-1 — groups and grants, the routing half (§3.18).

Properties:
  * one ladder, additive, no deny — an unknown level covers nothing (fail-closed);
  * the built-in roles wear a level per securable kind, and an
    AGENT principal gets no role default — only grants reach it;
  * a member is a principal string, so people and agents ride one rule;
  * ``may`` is the union of role defaults + group grants + own grants over the meaning
    chain (parents + the grant-bearing ``domain`` tag), and its explain NAMES the
    grant that granted;
  * the wave receipt: a person in two function groups receives, through each
    group's channel, exactly what each group subscribes to — resolved by
    ``route``, no model anywhere.
"""
from __future__ import annotations

import pytest

from aughor.briefing.models import BriefSubscription
from aughor.metastore.models import (
    agent_principal,
    domain_securable,
    group_principal,
    principal_kind,
    securable_kind,
    thing_securable,
    user_principal,
)
from aughor.metastore.store import add_grant
from aughor.rbac import groups as g
from aughor.rbac import store as rbac_store
from aughor.rbac.access import may, securable_chain
from aughor.rbac.levels import (
    EDIT,
    LADDER,
    MANAGE,
    OWN,
    RUN,
    SUBSCRIBE,
    VIEW,
    is_level,
    level_covers,
    role_default_level,
)
from aughor.rbac.routing import owner_principal, route


# ── The ladder ────────────────────────────────────────────────────────────────

def test_ladder_orders_and_covers():
    assert LADDER == (VIEW, SUBSCRIBE, EDIT, MANAGE, OWN)
    assert level_covers(OWN, VIEW)
    assert level_covers(SUBSCRIBE, VIEW)
    assert not level_covers(VIEW, SUBSCRIBE)
    assert level_covers(EDIT, EDIT)


def test_run_is_subscribe_not_a_sixth_rung():
    assert RUN == SUBSCRIBE
    assert level_covers("run", VIEW)
    assert level_covers(EDIT, "run")
    assert is_level("run")


def test_unknown_level_covers_nothing_and_is_covered_by_nothing():
    assert not level_covers("admin", VIEW)   # a typo is a refusal, never a grant
    assert not level_covers(OWN, "everything")
    assert not is_level("admin")


def test_role_defaults_map_the_three_roles():
    assert role_default_level("viewer", "metric") == VIEW
    assert role_default_level("analyst", "promise") == EDIT
    assert role_default_level("owner", "automation") == OWN
    assert role_default_level("not-a-role", "metric") is None  # fail-closed


# ── Vocabulary ────────────────────────────────────────────────────────────────

def test_ontology_things_are_securables():
    assert thing_securable("promise", "dispatch-24h") == "promise:dispatch-24h"
    assert securable_kind("promise:dispatch-24h") == "promise"
    assert securable_kind("domain:supply-chain") == "domain"
    assert securable_kind("catalog:c1") == "catalog"   # the old vocabulary keeps
    assert securable_kind("nonsense") == ""
    with pytest.raises(ValueError):
        thing_securable("tables", "x")  # a typo cannot mint an unmatchable securable


def test_principal_kinds():
    assert principal_kind(user_principal("ana@corp")) == "user"
    assert principal_kind(group_principal("finance")) == "group"
    assert principal_kind(agent_principal("ua_1")) == "agent"
    assert principal_kind("Ana (logistics)") == ""


def test_chain_walks_parents_then_the_domain_tag():
    chain = securable_chain(
        "promise:dispatch-24h",
        parents=["process:order-to-delivery"],
        tags={"domain": "supply-chain", "tier": "internal"},
    )
    assert chain == ["promise:dispatch-24h", "process:order-to-delivery",
                     "domain:supply-chain"]  # tier is gating, never grant-bearing


# ── Groups + membership ───────────────────────────────────────────────────────

def test_group_crud_and_membership_is_org_scoped():
    org_a, org_b = "hb1-org-a", "hb1-org-b"
    g.upsert_group(org_a, "supply-chain", "Supply chain", channel_trigger_id="trg_ops")
    assert g.get_group(org_a, "supply-chain").channel_trigger_id == "trg_ops"
    assert g.get_group(org_b, "supply-chain") is None  # DATA-06

    g.add_member(org_a, "supply-chain", user_principal("ana@corp"))
    g.add_member(org_a, "supply-chain", agent_principal("ua_watcher"))  # agents belong
    assert g.list_members(org_a, "supply-chain") == [
        agent_principal("ua_watcher"), user_principal("ana@corp")]
    assert g.groups_of(org_a, user_principal("ana@corp")) == ["supply-chain"]
    assert g.groups_of(org_b, user_principal("ana@corp")) == []

    assert g.delete_group(org_a, "supply-chain")
    assert g.get_group(org_a, "supply-chain") is None
    assert g.groups_of(org_a, user_principal("ana@corp")) == []  # membership went too


def test_member_must_be_a_person_or_an_agent():
    org = "hb1-org-members"
    g.upsert_group(org, "finance", "Finance")
    with pytest.raises(ValueError):
        g.add_member(org, "finance", "workspace:w1")
    with pytest.raises(ValueError):
        g.add_member(org, "finance", group_principal("ops"))  # no nesting in slice 1
    with pytest.raises(KeyError):
        g.add_member(org, "no-such-group", user_principal("a@b"))


def test_group_id_is_a_slug():
    assert g.valid_group_id("supply-chain")
    assert not g.valid_group_id("Supply Chain")
    assert not g.valid_group_id("a:b")  # would break the group:<id> principal string
    with pytest.raises(ValueError):
        g.upsert_group("hb1-org-slug", "Not A Slug", "x")


# ── may() — the one union ─────────────────────────────────────────────────────

def test_identity_off_is_owner_everywhere():
    d = may(None, EDIT, "metric:m1", org_id="hb1-org-x")
    assert d.allowed and d.level == OWN


def test_role_default_reaches_a_person_and_never_an_agent():
    org = "hb1-org-defaults"
    rbac_store.assign_role(org, "vera@corp", "viewer")
    ok = may(user_principal("vera@corp"), VIEW, "metric:m1", org_id=org)
    assert ok.allowed
    assert any("role viewer holds view" in line for line in ok.explain)

    no = may(user_principal("vera@corp"), EDIT, "metric:m1", org_id=org)
    assert not no.allowed
    assert no.level == VIEW  # names what was held, not just "no"

    # The same role string assigned to an agent id grants an agent nothing via
    # role defaults — an agent holds only what a grant or a group gives it.
    agent = agent_principal("ua_probe")
    nothing = may(agent, VIEW, "metric:m1", org_id=org)
    assert not nothing.allowed


def test_group_grant_reaches_members_through_the_domain_tag():
    org = "hb1-org-tag"
    g.upsert_group(org, "supply-chain", "Supply chain", channel_trigger_id="trg_sc")
    g.add_member(org, "supply-chain", user_principal("omar@corp"))
    add_grant(group_principal("supply-chain"), domain_securable("supply-chain"),
              SUBSCRIBE, org_id=org)

    d = may(user_principal("omar@corp"), SUBSCRIBE, "promise:dispatch-24h",
            org_id=org, tags={"domain": "supply-chain"})
    assert d.allowed
    assert any("group:supply-chain" in line and "domain:supply-chain" in line
               for line in d.explain)  # explain NAMES the grant

    # Without the tag the promise is uncovered — the grant sits on the domain.
    bare = may(user_principal("omar@corp"), SUBSCRIBE, "promise:dispatch-24h", org_id=org)
    assert not bare.allowed


def test_union_is_additive_and_the_max_wins():
    org = "hb1-org-union"
    rbac_store.assign_role(org, "uma@corp", "viewer")            # view everywhere
    g.upsert_group(org, "pricing", "Pricing")
    g.add_member(org, "pricing", user_principal("uma@corp"))
    add_grant(group_principal("pricing"), "metric:price-realisation", MANAGE, org_id=org)

    d = may(user_principal("uma@corp"), EDIT, "metric:price-realisation", org_id=org)
    assert d.allowed and d.level == MANAGE  # the group's manage outranks the role's view


def test_unknown_level_is_refused_before_any_lookup():
    d = may(user_principal("x@y"), "sudo", "metric:m1", org_id="hb1-org-x")
    assert not d.allowed
    assert "unknown level" in d.explain[0]


def test_agent_in_a_group_inherits_the_groups_grants():
    org = "hb1-org-agent"
    g.upsert_group(org, "ops", "Ops")
    g.add_member(org, "ops", agent_principal("ua_scout"))
    add_grant(group_principal("ops"), "automation:a1", RUN, org_id=org)
    d = may(agent_principal("ua_scout"), RUN, "automation:a1", org_id=org)
    assert d.allowed


# ── route() — the wave receipt ────────────────────────────────────────────────

def test_receipt_two_groups_each_channel_gets_exactly_its_subscriptions():
    """A person in two function groups receives, through each group's channel,
    exactly what each group subscribes to — and the why names the grant."""
    org = "hb1-org-receipt"
    g.upsert_group(org, "supply-chain", "Supply chain", channel_trigger_id="trg_ops")
    g.upsert_group(org, "finance", "Finance", channel_trigger_id="trg_fin")
    person = user_principal("dana@corp")
    g.add_member(org, "supply-chain", person)
    g.add_member(org, "finance", person)

    # Supply chain subscribes to its domain; finance owns one metric.
    add_grant(group_principal("supply-chain"), domain_securable("supply-chain"),
              SUBSCRIBE, org_id=org)

    breach = route("promise:dispatch-24h", org_id=org,
                   parents=["process:order-to-delivery"],
                   tags={"domain": "supply-chain"})
    assert [(d.group_id, d.channel_trigger_id) for d in breach] == [("supply-chain", "trg_ops")]
    assert any("domain:supply-chain" in w for w in breach[0].why)

    drift = route("metric:cost-base", org_id=org, owner="group:finance")
    assert [(d.group_id, d.channel_trigger_id) for d in drift] == [("finance", "trg_fin")]
    assert breach[0].channel_trigger_id != drift[0].channel_trigger_id
    # Dana sits in both groups and gets each finding once, on the right channel —
    # nothing about the person appears in either resolution: routing is by group.


def test_owner_free_text_stays_display_only():
    assert owner_principal("group:finance") == "group:finance"
    assert owner_principal("Ana (logistics)") is None
    dests = route("metric:m2", org_id="hb1-org-freetext", owner="Ana (logistics)")
    assert dests == []  # honest text routes nothing, silently breaks nothing


def test_a_grant_naming_a_deleted_group_routes_nothing():
    org = "hb1-org-gone"
    add_grant(group_principal("ghost"), "metric:m3", SUBSCRIBE, org_id=org)
    assert route("metric:m3", org_id=org) == []


def test_direct_user_grant_routes_without_a_channel():
    org = "hb1-org-direct"
    add_grant(user_principal("solo@corp"), "rule:dach", SUBSCRIBE, org_id=org)
    dests = route("rule:dach", org_id=org)
    assert [(d.principal, d.channel_trigger_id, d.group_id) for d in dests] == [
        (user_principal("solo@corp"), "", "")]


def test_route_dedupes_owner_and_subscriber_into_one_destination():
    org = "hb1-org-dedupe"
    g.upsert_group(org, "ops", "Ops", channel_trigger_id="trg_o")
    add_grant(group_principal("ops"), "process:o2d", SUBSCRIBE, org_id=org)
    dests = route("process:o2d", org_id=org, owner="group:ops")
    assert len(dests) == 1
    assert len(dests[0].why) == 2  # owner AND the subscribe grant, both named


# ── BriefSubscription — subject and reader ────────────────────────────────────

def test_brief_subscription_gains_subject_and_reader_additively():
    old = BriefSubscription(conn_id="c1", name="weekly", trigger_id="t1")
    assert old.subject == "" and old.reader == ""  # stored rows mean what they did

    new = BriefSubscription(conn_id="c1", name="ops brief", trigger_id="t1",
                            subject="domain:supply-chain", reader="group:supply-chain")
    round_tripped = BriefSubscription(**new.to_dict())
    assert round_tripped.subject == "domain:supply-chain"
    assert round_tripped.reader == "group:supply-chain"
