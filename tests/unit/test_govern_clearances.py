"""Wave G2 — governed tags, clearances, and the refusal that says why.

Hermetic on both halves by design: the policy (:mod:`aughor.govern.tags`) is pure over
tag objects, and the store tests use the conftest-redirected ``AUGHOR_GOVERN_TAGS_DB``.

The two that carry the wave's argument are
:func:`test_a_refusal_names_what_would_unblock_it` (the Genie anti-pattern) and
:func:`test_a_descriptive_tag_is_not_a_lock` (why the gating set is explicit and small).
"""
from __future__ import annotations

import pytest

from aughor.govern.tags import (
    ClearanceDecision,
    Tag,
    evaluate,
    is_securable,
    requirements_for,
)
from aughor.metastore.models import (
    artifact_securable,
    securable_kind,
    securable_table,
    table_securable,
)


def _tag(key: str, value: str, securable: str = "table:c.s.salaries") -> Tag:
    return Tag(securable=securable, key=key, value=value, set_by="alice", set_at="2026-07-28")


# ── the securable vocabulary (extended, not duplicated) ─────────────────────────────

def test_table_securable_round_trips():
    s = table_securable("cat", "hr", "salaries")
    assert s == "table:cat.hr.salaries"
    assert securable_table(s) == ("cat", "hr", "salaries")


def test_a_dotted_table_name_survives_the_round_trip():
    """Table names contain dots in the wild; splitting naively would silently retarget
    the access decision at a different object."""
    s = table_securable("cat", "hr", "salaries.2026")
    assert securable_table(s) == ("cat", "hr", "salaries.2026")


def test_securable_kind_recognises_the_whole_vocabulary():
    assert securable_kind("catalog:c") == "catalog"
    assert securable_kind("schema:c.s") == "schema"
    assert securable_kind(table_securable("c", "s", "t")) == "table"
    assert securable_kind(artifact_securable("brief", "b1")) == "artifact"
    assert securable_kind("nonsense") == ""
    assert securable_kind("") == ""


def test_is_securable_rejects_a_bare_id():
    assert is_securable("table:c.s.t")
    assert not is_securable("c.s.t")


# ── which tags gate ─────────────────────────────────────────────────────────────────

def test_a_descriptive_tag_is_not_a_lock():
    """`domain=finance` is a fact about the object, not a rule about its readers.

    The gating set is explicit and small precisely so that labelling the warehouse does
    not quietly become denying access to it.
    """
    assert requirements_for([_tag("domain", "finance"), _tag("owner", "cfo")]) == []


def test_restricted_tier_requires_its_clearance():
    reqs = requirements_for([_tag("tier", "restricted")])
    assert [r.clearance for r in reqs] == ["clearance.restricted"]


def test_an_unknown_tier_does_not_invent_a_lock():
    """A typo must not silently deny access to real data — an unrecognised tier is a
    description, and the failure mode of guessing is worse than the failure mode of not."""
    assert requirements_for([_tag("tier", "restrictd")]) == []


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
def test_pii_truthiness(value):
    assert requirements_for([_tag("pii", value)])


@pytest.mark.parametrize("value", ["false", "0", "no", ""])
def test_pii_falsiness_does_not_gate(value):
    assert requirements_for([_tag("pii", value)]) == []


def test_requirements_are_order_stable():
    """A decision that reorders its own reasons makes its receipts un-diffable."""
    a = requirements_for([_tag("tier", "restricted"), _tag("pii", "true")])
    b = requirements_for([_tag("pii", "true"), _tag("tier", "restricted")])
    assert a == b


# ── the decision ────────────────────────────────────────────────────────────────────

def test_an_untagged_securable_is_allowed():
    """Governance is opt-in per object; deny-by-default would make enabling the flag a
    platform-wide outage rather than a policy."""
    d = evaluate("table:c.s.public", [], [])
    assert d.allowed and d.requirements == [] and d.reason == ""


def test_a_held_clearance_opens_the_gate():
    d = evaluate("table:c.s.salaries", [_tag("tier", "restricted")], ["clearance.restricted"])
    assert d.allowed
    assert d.requirements and not d.missing


def test_a_missing_clearance_closes_it():
    d = evaluate("table:c.s.salaries", [_tag("tier", "restricted")], ["clearance.pii"])
    assert not d.allowed
    assert [r.clearance for r in d.missing] == ["clearance.restricted"]


def test_every_requirement_must_be_satisfied():
    d = evaluate("table:c.s.salaries",
                 [_tag("tier", "restricted"), _tag("pii", "true")],
                 ["clearance.restricted"])
    assert not d.allowed
    assert [r.clearance for r in d.missing] == ["clearance.pii"]


def test_clearances_are_matched_case_insensitively():
    d = evaluate("table:c.s.salaries", [_tag("tier", "restricted")], ["Clearance.Restricted"])
    assert d.allowed


def test_a_refusal_names_what_would_unblock_it():
    """The pinned anti-pattern: a permission-trimmed answer that comes back empty teaches
    its reader that the data does not exist. The rows may be withheld; the reason may not.
    """
    d = evaluate("table:c.s.salaries", [_tag("tier", "restricted")], [])
    assert not d.allowed
    assert "table:c.s.salaries" in d.reason
    assert "tier=restricted" in d.reason
    assert "clearance.restricted" in d.reason


def test_an_allowed_decision_has_no_reason_to_give():
    assert evaluate("table:c.s.t", [], []).reason == ""


def test_bypass_still_records_what_it_bypassed():
    """The owner ladder goes THROUGH the same function, so a bypass is visible in the
    receipt instead of being an absent call."""
    d = evaluate("table:c.s.salaries", [_tag("tier", "restricted")], [], bypass=True)
    assert d.allowed
    assert d.requirements and not d.missing


def test_decision_serializes_for_a_receipt():
    d = evaluate("table:c.s.salaries", [_tag("pii", "true")], [])
    out = ClearanceDecision.to_dict(d)
    assert out["allowed"] is False and out["missing"] and out["reason"]


# ── the flag ────────────────────────────────────────────────────────────────────────

def test_check_is_allow_for_an_untagged_securable():
    """Governance is opt-in per object: an untagged securable is always allowed, so
    callers can wire the check in unconditionally. This is what made hardwiring the
    flag safe — a deployment that tags nothing sees no change."""
    from aughor.govern import tags as T

    d = T.check("table:c.s.never-tagged-anything", [])
    assert d.allowed and d.requirements == []


def test_clearance_enforcement_is_unconditional():
    """The flag was hardwired 2026-08-02; pinned so a re-introduced switch faces this."""
    from aughor.kernel.flags import FLAG_ENV

    assert "govern.clearances" not in FLAG_ENV


# ── the store ───────────────────────────────────────────────────────────────────────

class TestTagStore:
    def test_set_and_read_back(self):
        from aughor.govern import tag_store

        tag_store.set_tag("table:c.s.salaries", "tier", "restricted", set_by="alice")
        tags = tag_store.tags_for("table:c.s.salaries")
        assert [(t.key, t.value, t.set_by) for t in tags] == [("tier", "restricted", "alice")]

    def test_a_tag_without_an_author_is_refused(self):
        """An access-control fact that cannot say who asserted it is not evidence, and
        defaulting the author to 'system' would launder exactly that."""
        from aughor.govern import tag_store

        with pytest.raises(ValueError, match="who set it"):
            tag_store.set_tag("table:c.s.x", "tier", "restricted", set_by="")

    def test_a_malformed_securable_is_refused(self):
        from aughor.govern import tag_store

        with pytest.raises(ValueError, match="not a securable"):
            tag_store.set_tag("salaries", "tier", "restricted", set_by="alice")

    def test_setting_the_same_key_replaces_and_re_stamps(self):
        from aughor.govern import tag_store

        tag_store.set_tag("table:c.s.r", "tier", "restricted", set_by="alice")
        tag_store.set_tag("table:c.s.r", "tier", "confidential", set_by="bob")
        tags = tag_store.tags_for("table:c.s.r")
        assert len(tags) == 1
        assert (tags[0].value, tags[0].set_by) == ("confidential", "bob")

    def test_clear_removes_the_gate(self):
        """A retracted tag must stop gating — a tombstone that still reads as present
        would keep denying access after governance decided it should not."""
        from aughor.govern import tag_store

        tag_store.set_tag("table:c.s.cleared", "pii", "true", set_by="alice")
        assert tag_store.clear_tag("table:c.s.cleared", "pii", cleared_by="alice")
        assert tag_store.tags_for("table:c.s.cleared") == []
        assert requirements_for(tag_store.tags_for("table:c.s.cleared")) == []

    def test_clearing_a_missing_tag_reports_it_did_nothing(self):
        from aughor.govern import tag_store

        assert tag_store.clear_tag("table:c.s.never", "pii") is False

    def test_orgs_do_not_see_each_others_tags(self):
        from aughor.govern import tag_store

        tag_store.set_tag("table:c.s.iso", "pii", "true", set_by="alice", org_id="org-a")
        assert tag_store.tags_for("table:c.s.iso", org_id="org-a")
        assert tag_store.tags_for("table:c.s.iso", org_id="org-b") == []

    def test_list_filters_by_key_and_kind(self):
        from aughor.govern import tag_store

        tag_store.set_tag("table:c.s.t1", "pii", "true", set_by="alice", org_id="org-f")
        tag_store.set_tag("catalog:c", "pii", "true", set_by="alice", org_id="org-f")
        tag_store.set_tag("table:c.s.t1", "domain", "hr", set_by="alice", org_id="org-f")
        assert len(tag_store.list_tags(key="pii", org_id="org-f")) == 2
        assert len(tag_store.list_tags(securable_prefix="table:", org_id="org-f")) == 2

    def test_check_reads_the_store_end_to_end(self, monkeypatch):
        from aughor.govern import tag_store
        from aughor.govern import tags as T

        tag_store.set_tag("table:c.s.e2e", "tier", "restricted", set_by="alice",
                          org_id="org-e2e")
        blocked = T.check("table:c.s.e2e", [], org_id="org-e2e")
        assert not blocked.allowed and "clearance.restricted" in blocked.reason
        allowed = T.check("table:c.s.e2e", ["clearance.restricted"], org_id="org-e2e")
        assert allowed.allowed
