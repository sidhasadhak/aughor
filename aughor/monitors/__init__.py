"""Proactive Monitors — M20.

Aughor volunteers problems before users ask questions by running metric
checks, anomaly detection and data-freshness validation on a schedule and
surfacing alerts in the UI.

Sub-modules
-----------
models    — Monitor + MonitorAlert Pydantic models
store     — SQLite-backed append-only alert ledger
runner    — execute a monitor against a live DB connection
scheduler — APScheduler wrapper; loads enabled monitors at startup
digest    — build a weekly/daily intelligence digest from alerts + KB
"""
