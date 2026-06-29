"""Platform extension registries — the seams the Agent plugs into.

The Data Intelligence Platform owns these registries (purge hooks, schema
annotators, ingestion sinks, post-execute hooks) but never imports the Agent. The
Agent contributes its intelligence by *registering* into them at startup (see
``aughor.agent.bootstrap.register_agent_plugins``). With nothing registered, the
platform degrades to its raw, agent-free behaviour — which is exactly the
"platform runs without the agent" plug-and-play property.
"""
