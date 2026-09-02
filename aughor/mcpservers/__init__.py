"""VA-9d · the MCP consumer — servers this deployment may CALL.

The mirror of :mod:`aughor.mcp`, which is the server we ARE. Kept as a separate package
for that reason: one named `mcp` meaning both directions would make every import a
question, and the two have opposite threat models — that one is a surface we expose, this
one is a set of third parties we reach.

The layering is `integrations/`'s, and for its reason:

    models.py   what a server and a discovered tool are, and `classify` — the one place
                the read-only-first posture is decided
    store.py    the allowlist, and the roster discovered against it
    session.py  transport only (stdio · streamable HTTP), no policy
    discover.py tools/list + classification + health, through govern.outbound
    call.py     THE door — allowlist, roster, read-only gate, cap, span, audit

`call.py` being the only way through is what makes the four gates impossible to forget.
"""
