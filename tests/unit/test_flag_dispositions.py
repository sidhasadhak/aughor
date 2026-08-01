"""The disposition ratchet (flag strategy §5.1, 2026-07-31).

Every registered flag must live in EXACTLY ONE disposition. This is what converts
"off" from an accident into a decision, and it is deliberately a whole-registry
assertion: a new flag that declares no exit fails here, by name, before it can join
a list that had grown to 91 entries at ~1/day. The 2026-07-22 audit designed this
ratchet and deferred it "until every flag has a disposition" — the 2026-07-31 study
supplied them (docs/FLAG_STRATEGY_2026-07-31.md §4).
"""
from __future__ import annotations

from aughor.kernel.flags import (
    AUTO_ELIGIBLE,
    COST_LATENCY_PROFILE,
    EXPERIMENT,
    FLAG_DEFAULT,
    FLAG_ENV,
    GRADUATION_QUEUE,
    INTENTIONALLY_OFF,
    MIGRATION,
    flag_disposition,
    list_flags,
)

SETS = {
    "default_on": set(FLAG_DEFAULT),
    "auto": set(AUTO_ELIGIBLE),
    "intentionally_off": set(INTENTIONALLY_OFF),
    "experiment": set(EXPERIMENT),
    "performance_profile": set(COST_LATENCY_PROFILE),
    "migration": set(MIGRATION),
    "graduation_queue": set(GRADUATION_QUEUE),
}


def test_every_flag_has_exactly_one_disposition():
    """The ratchet itself. A failure names the flag, not a count."""
    for name in FLAG_ENV:
        homes = [k for k, s in SETS.items() if name in s]
        assert len(homes) == 1, (
            f"{name!r} is in {homes or 'NO disposition'} — every registered flag "
            f"must declare exactly one exit (aughor/kernel/flags.py §disposition ratchet)")


def test_no_disposition_names_a_ghost_flag():
    """A disposition entry for an unregistered name is a decision about nothing —
    usually a deleted flag whose tombstone was left behind, or a typo that would
    silently exempt the real flag from the ratchet."""
    for kind, members in SETS.items():
        ghosts = sorted(members - set(FLAG_ENV))
        assert not ghosts, f"{kind} names unregistered flag(s): {ghosts}"


def test_disposition_resolver_agrees_with_the_sets():
    for name in FLAG_ENV:
        want = next(k for k, s in SETS.items() if name in s)
        assert flag_disposition(name) == want, name


def test_reason_carrying_dispositions_have_reasons():
    """A disposition without a stated reason is a label, not a decision."""
    for d in (INTENTIONALLY_OFF, EXPERIMENT, MIGRATION, GRADUATION_QUEUE):
        for name, reason in d.items():
            assert isinstance(reason, str) and len(reason) >= 10, name


def test_list_flags_carries_the_disposition():
    """The Settings UI groups by kind — the API has to say which kind each flag is."""
    flags = list_flags()
    for name, row in flags.items():
        assert row["disposition"] == flag_disposition(name), name
        assert row["disposition"] != "undispositioned", name


def test_deleted_flags_stay_deleted():
    """Tombstones: re-registering one silently resurrects behaviour the strategy
    removed. ada.adversarial_verify — the always-challenge refuter tier (§4G);
    obs.mlflow — replaced by self-gating on AUGHOR_MLFLOW_TRACKING_URI (§4C)."""
    for tombstone in ("deep_analysis.adversarial_verify", "obs.mlflow", "search.rrf",
                      "ai_sql", "deep_analysis.evidence_stubs",
                      "explorer.synthesis_incremental", "plan.program",
                      "obs.prompt_capture"):
        assert tombstone not in FLAG_ENV, tombstone
        assert all(tombstone not in s for s in SETS.values()), tombstone
