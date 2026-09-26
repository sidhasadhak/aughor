"""Idea 4 · learn when each table's numbers stop changing.

A daily reading (`sampler`) counts each recent day per table; the learner (`learn`) finds
the age after which a day's count stops moving; the store (`store`) keeps the readings and
answers ``learned_lag_days(connection)`` — the lag a scheduled briefing, an anomaly
monitor, a deep run's window and the conversation all read, so they speak only about
settled days and call newer ones what they are: still settling. A person's explicit
`observation_lag_days` on a step still wins over the learned value.
"""
from aughor.settling.learn import Observation, SettlingVerdict, settle_lag  # noqa: F401
from aughor.settling.store import connection_lag, learned_lag_days, summary, verdicts  # noqa: F401
