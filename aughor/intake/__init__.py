"""KI-1 (§3.10) — the knowledge-intake lane: bundle in, plan, human verdict, fan out.

Any source becomes typed candidate objects; a staged review lane holds them; a human
accepts, edits or dismisses each; accepted objects fan out to the EXISTING stores,
each write passing through that store's own governance. Nothing auto-applies.
"""
