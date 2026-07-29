"""Wave G4 — usage caps: the algebra, and the refusal that names its number.

The three carrying tests are the two algebra rules and the no-clawback guarantee. Getting
either rule backwards is a real outage or a real overspend, which is why they are asserted
separately rather than through one combined scenario.
"""
from __future__ import annotations

import pytest

from aughor.govern.usage_caps import (
    ACTIONS,
    METRICS,
    SCOPES,
    CapDecision,
    UsageCap,
    effective_limit,
    evaluate,
)


def _cap(scope="org", subject="*", metric="calls", limit=100.0, action="alert",
         window_hours=24) -> UsageCap:
    return UsageCap(scope=scope, subject=subject, metric=metric, limit=limit,
                    window_hours=window_hours, action=action)


# ── most-permissive WITHIN a scope ──────────────────────────────────────────────────

def test_the_larger_limit_wins_within_one_scope():
    """Two rows about one subject and metric are two statements about one allowance, and
    the larger is the operator's latest intent. Taking the smaller would mean raising a
    limit does nothing until somebody finds and deletes the old row."""
    assert effective_limit([_cap(limit=100), _cap(limit=500)]) == 500


def test_effective_limit_of_nothing_is_none():
    assert effective_limit([]) is None


def test_a_raise_does_not_silently_disable_the_gate():
    """A `block` anywhere in the merged group survives. The permissive rule is about HOW
    MUCH is allowed, never about whether a breach is enforced — otherwise raising a limit
    quietly downgrades the cap to an alert."""
    d = evaluate([_cap(limit=100, action="block"), _cap(limit=500, action="alert")],
                 {"calls": 600})
    assert not d.allowed and d.blocked_by is not None
    assert d.blocked_by.cap.limit == 500      # the permissive limit...
    assert d.blocked_by.cap.action == "block"  # ...with the restrictive action


# ── most-restrictive ACROSS scopes ──────────────────────────────────────────────────

def test_both_scopes_bind_at_once():
    """An org cap and a user cap describe the pool and one person's share of it. The
    permissive reading here would let one generous personal limit drain the org."""
    caps = [_cap(scope="org", limit=100, action="block"),
            _cap(scope="user", subject="*", limit=1000, action="block")]
    d = evaluate(caps, {"calls": 150}, user_id="alice")
    assert not d.allowed
    assert d.blocked_by.cap.scope == "org"     # the pool is what is actually exhausted


def test_a_user_cap_binds_even_when_the_org_is_fine():
    caps = [_cap(scope="org", limit=10_000, action="block"),
            _cap(scope="user", subject="*", limit=10, action="block")]
    d = evaluate(caps, {"calls": 50}, user_id="alice")
    assert not d.allowed and d.blocked_by.cap.scope == "user"


def test_the_coarser_scope_is_reported_first():
    """When both are breached, name the pool rather than an incidental personal limit."""
    caps = [_cap(scope="user", subject="*", limit=5, action="block"),
            _cap(scope="org", limit=10, action="block")]
    d = evaluate(caps, {"calls": 100}, user_id="alice")
    assert d.blocked_by.cap.scope == "org"
    assert len(d.alerts) == 1 and d.alerts[0].cap.scope == "user"


# ── applicability ───────────────────────────────────────────────────────────────────

def test_a_wildcard_subject_matches_any_subject_in_its_scope():
    assert _cap(scope="org", subject="*").applies_to(org_id="acme", user_id="")


def test_a_named_subject_matches_only_itself():
    cap = _cap(scope="org", subject="acme")
    assert cap.applies_to(org_id="acme", user_id="")
    assert not cap.applies_to(org_id="other", user_id="")


def test_a_user_cap_does_not_apply_when_there_is_no_user():
    """user_id is 0% populated in local mode (measured in G3a). A per-user cap that
    applied to an anonymous caller would block everything the moment it was declared."""
    assert not _cap(scope="user", subject="*").applies_to(org_id="acme", user_id="")
    d = evaluate([_cap(scope="user", subject="*", limit=1, action="block")],
                 {"calls": 999}, user_id="")
    assert d.allowed and d.considered == 0


def test_an_unknown_metric_or_scope_is_ignored_not_enforced():
    d = evaluate([UsageCap(scope="galaxy", subject="*", metric="calls", limit=1,
                           action="block"),
                  UsageCap(scope="org", subject="*", metric="vibes", limit=1,
                           action="block")], {"calls": 999})
    assert d.allowed and d.considered == 0


# ── the decision ────────────────────────────────────────────────────────────────────

def test_usage_at_the_limit_is_allowed():
    """The limit is an allowance, not a fence one short of it."""
    assert evaluate([_cap(limit=100, action="block")], {"calls": 100}).allowed


def test_one_over_the_limit_is_not():
    assert not evaluate([_cap(limit=100, action="block")], {"calls": 101}).allowed


def test_alert_records_the_breach_and_still_allows():
    d = evaluate([_cap(limit=10, action="alert")], {"calls": 99})
    assert d.allowed
    assert len(d.alerts) == 1 and d.alerts[0].over_by == 89


def test_no_caps_means_no_opinion():
    d = evaluate([], {"calls": 10**9})
    assert d.allowed and d.considered == 0 and d.reason == ""


def test_a_missing_metric_reads_as_zero_usage():
    assert evaluate([_cap(metric="cost_usd", limit=1, action="block")], {}).allowed


def test_the_refusal_names_the_number_and_the_window():
    """Withhold the work, never the reason — the same rule as G2's clearance block."""
    d = evaluate([_cap(limit=100, action="block", window_hours=24)], {"calls": 1043})
    assert not d.allowed
    assert "1043" in d.reason and "100" in d.reason and "24h" in d.reason
    assert "already running is unaffected" in d.reason


def test_the_decision_carries_the_typed_error_class():
    """`budget_exceeded` joins the R4 tail so a caller can branch on it."""
    d = evaluate([_cap(limit=1, action="block")], {"calls": 2})
    assert d.to_dict()["error_class"] == "budget_exceeded"
    assert CapDecision(allowed=True).to_dict()["error_class"] is None


def test_there_is_no_abort_path():
    """Enforcement is pre-flight ONLY. Killing an in-flight run destroys work the user
    already paid for and leaves a partial artifact claiming it completed."""
    import aughor.govern.usage_caps as UC

    assert not [n for n in dir(UC) if n in ("abort", "cancel", "kill", "revoke_running")]


# ── the flag and the store ──────────────────────────────────────────────────────────

def test_check_allows_unconditionally_when_the_flag_is_off(monkeypatch):
    import aughor.govern.usage_caps as UC

    monkeypatch.setattr(UC, "enabled", lambda: False)
    assert UC.check(org_id="acme").allowed


def test_the_flag_is_registered():
    from aughor.kernel.flags import FLAG_ENV, FLAG_META

    assert "govern.usage_caps" in FLAG_ENV and "govern.usage_caps" in FLAG_META


class TestCapStore:
    def test_set_and_list(self):
        from aughor.govern import cap_store

        cap_store.set_cap("org", "*", "calls", 500, set_by="alice", org_id="o1")
        caps = cap_store.list_caps(org_id="o1")
        assert [(c.scope, c.metric, c.limit) for c in caps] == [("org", "calls", 500.0)]

    def test_a_cap_without_an_author_is_refused(self):
        from aughor.govern import cap_store

        with pytest.raises(ValueError, match="who set it"):
            cap_store.set_cap("org", "*", "calls", 5, set_by="")

    @pytest.mark.parametrize("kwargs,match", [
        ({"scope": "galaxy"}, "unknown cap scope"),
        ({"metric": "vibes"}, "unknown cap metric"),
        ({"action": "explode"}, "unknown cap action"),
        ({"limit": -1}, "cannot be negative"),
    ])
    def test_malformed_caps_are_refused(self, kwargs, match):
        from aughor.govern import cap_store

        args = {"scope": "org", "subject": "*", "metric": "calls", "limit": 5.0,
                "set_by": "alice", **kwargs}
        with pytest.raises(ValueError, match=match):
            cap_store.set_cap(**args)

    def test_replacing_a_cap_re_stamps_it(self):
        from aughor.govern import cap_store

        cap_store.set_cap("org", "*", "calls", 100, set_by="alice", org_id="o2")
        cap_store.set_cap("org", "*", "calls", 900, set_by="bob", org_id="o2")
        caps = cap_store.list_caps(org_id="o2")
        assert len(caps) == 1 and caps[0].limit == 900.0

    def test_clear_removes_the_cap(self):
        """A retired cap that still read as present would keep refusing work after the
        operator lifted it."""
        from aughor.govern import cap_store

        cap_store.set_cap("org", "*", "calls", 100, set_by="alice", org_id="o3")
        assert cap_store.clear_cap("org", "*", "calls", cleared_by="alice", org_id="o3")
        assert cap_store.list_caps(org_id="o3") == []

    def test_orgs_do_not_see_each_others_caps(self):
        from aughor.govern import cap_store

        cap_store.set_cap("org", "*", "calls", 100, set_by="alice", org_id="iso-a")
        assert cap_store.list_caps(org_id="iso-b") == []

    def test_windows_are_independent_rows(self):
        """A daily and a monthly cap on the same metric are different policies."""
        from aughor.govern import cap_store

        cap_store.set_cap("org", "*", "calls", 100, window_hours=24, set_by="a",
                          org_id="o4")
        cap_store.set_cap("org", "*", "calls", 2000, window_hours=720, set_by="a",
                          org_id="o4")
        assert len(cap_store.list_caps(org_id="o4")) == 2


def test_the_vocabularies_are_small_and_stated():
    assert METRICS and SCOPES == ("org", "user") and ACTIONS == ("alert", "block")
