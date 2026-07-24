"""Wave A — the automation plane: declared condition → governed effect.

One engine replacing three that happened to agree (the monitor scheduler, the brief
scheduler, and the explorer's scan watermark). See
``docs/WAVE_A_AUTOMATIONS_ARC.md`` for the arc and its decision gates.
"""
from aughor.automations.models import (
    Automation,
    AutomationRun,
    Condition,
    Effect,
    EffectOutcome,
)

__all__ = ["Automation", "AutomationRun", "Condition", "Effect", "EffectOutcome"]
