"""Arc CP · CP-4 — the answer envelope.

The core answer path emits ONE typed structure per answer — headline, body, grid, chart
decision, caveats, follow-ups, provenance — and every delivery door SELECTS from it. What a
door takes is its own policy; what the core produces is not, and nothing here needs a model
call to shorten what it was handed. Platform-level: this package imports no agent package.
"""
from aughor.answer.envelope import (  # noqa: F401
    AnswerEnvelope, ChartDecision, EnvelopeFolder, Grid, Provenance, lift_tables,
)
