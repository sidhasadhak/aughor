"""TJ-4 (2026-09-26): the manifest the owner installs asks for the reaction scope and event.

The handler lives in the TypeScript bot (`bots/slack/src/bot.ts`); this pins the Python side:
without `reactions:read` and `reaction_added` in the manifest, no reaction ever reaches it.
"""
from __future__ import annotations

from aughor.slackbots.manifest import BOT_EVENTS, BOT_SCOPES, render_manifest


def test_the_manifest_asks_for_reactions():
    assert "reactions:read" in BOT_SCOPES
    assert "reaction_added" in BOT_EVENTS and "reaction_removed" not in BOT_EVENTS
    m = render_manifest(name="Aughor")
    assert "reactions:read" in m["oauth_config"]["scopes"]["bot"]
    assert "reaction_added" in m["settings"]["event_subscriptions"]["bot_events"]
