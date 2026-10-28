"""What an organisation allows Aughor to do — the four choices that were flags (ROADMAP §3.65, 2026-10-28).

Each is an admin's setting in the organisation settings, off by default. While a setting has never been set, the
environment variable of the flag it replaced still answers, so an install that ran one through its env keeps it until
an admin decides; once set, the setting is the answer and the variable is not read.
"""
from __future__ import annotations

import os

#: Each setting → the variables of the flags it replaced.
FORMER_ENV: dict[str, tuple[str, ...]] = {
    "share_aggregates": ("AUGHOR_AGGREGATES_SHARE",),
    "outside_row_model": ("AUGHOR_SEMOPS_JEV_CHEAP_TIER",),
    "reason_to_read_runs": ("AUGHOR_GOVERN_JUSTIFICATIONS",),
    "scheduled_model_work": ("AUGHOR_AGENTS_TESTING_CENTRE", "AUGHOR_AGENTS_LEARNING_LOOP"),
}

#: Where a person changes them, for the sentences that say a thing is off.
WHERE = "Settings ▸ Organization ▸ What Aughor may do"


def allows(setting: str) -> bool:
    """Whether the organisation allows ``setting`` — its admin's answer, or while unset the former flag's variable."""
    from aughor.orgsettings.store import load_org_settings
    if setting not in FORMER_ENV:
        raise KeyError(f"unknown organisation setting {setting!r}")
    value = getattr(load_org_settings(), setting)
    if value is not None:
        return bool(value)
    return any(os.getenv(var, "").strip().lower() in ("1", "true", "yes", "on") for var in FORMER_ENV[setting])
