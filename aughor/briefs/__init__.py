"""Scheduled Brief delivery — push the Intelligence Digest to a connection's
stakeholders on a recurring schedule via a configured Action Hub trigger.

This is the 'push' half of backlog #4: intelligence that REACHES the user without
them opening the app. A BriefSubscription binds (connection, schedule, delivery
channel) — the channel is an existing Action Hub trigger (Slack / webhook / Jira),
so we reuse the whole delivery + retry + logging path rather than reinventing it.
"""
