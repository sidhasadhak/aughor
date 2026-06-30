"""Platform contracts — the stable, agent-agnostic types and seams the Data
Intelligence Platform exposes to whatever Agent runs within it.

These are the things both planes agree on: the shape of a query-execution result
(:mod:`execution`) and the host-capability surface the platform hands the agent
(:mod:`host`). They live on the **platform** side so the data plane (``db`` /
``connectors``) can speak them **without importing the agent** — the agent imports
*down* into the platform, never the reverse (see ``test_platform_agent_boundary``).
"""
