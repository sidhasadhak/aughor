"""Wave V5 — the invalidation registry is ENFORCED, not just documented.

**Scope corrected during the build.** The arc doc scoped V5 as *"replace `bootstrap.py`'s
hand-maintained call list with a registry"*. Reading the code first showed a registry already
exists and is good: ``aughor/kernel/registries/purge_hooks`` with
``register_purge_hook`` / ``register_schema_purge_hook``, orchestrated by
``aughor/db/purge.py``, which keeps the platform from importing the agent. Building a second
registry beside it would have been Wave V's own headline mistake — dialect #14.

The real gap is narrower and sharper: ``purge.py``'s docstring *instructs* an author to
"register a hook … otherwise a deleted catalog orphans it", and **nothing failed when they
forgot**. A written instruction is not a ratchet. So V5 ships the check instead of a
duplicate bus — putting the check on the dangerous side rather than on every call site, which
is the lesson Wave R paid for (the error frame ×15, the guard battery ×5).

An orphaned store is not a tidiness problem: a re-created connection that reuses an id
inherits the previous tenant's intelligence.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _force_register():
    """Register the real agent plugins, defeating bootstrap's idempotence guard.

    ``register_agent_plugins`` returns early once ``_REGISTERED`` is set, and something has
    already called it by the time this test module runs — so clearing the registry and
    calling again would silently register nothing (which is how the vacuous-pass guard below
    earned its place).
    """
    from aughor.agent import bootstrap
    from aughor.kernel.registries import purge_hooks

    purge_hooks.clear()
    bootstrap._REGISTERED = False
    bootstrap.register_agent_plugins()


@pytest.fixture
def _registered():
    """Report which modules the registered hooks reach, then restore a POPULATED registry.

    Teardown matters here: leaving the registry cleared while bootstrap's guard still says
    "registered" would hand every later test in the session an empty purge cascade.
    """
    from aughor.kernel.registries import purge_hooks

    _force_register()
    try:
        yield purge_hooks.registered_hook_names()
    finally:
        _force_register()


#: Connection-keyed stores that deliberately have NO purge hook, with the reason.
#: A one-way ratchet: this baseline may shrink, never grow.
_EXEMPT = {
    # Caches keyed by something other than the connection, or global by design.
    "schema_cache",       # keyed by schema fingerprint + scope; purging is a no-op
    "suggestions_cache",  # keyed by schema fingerprint; evicted by its own cap
    "matcache",           # purged inline by the platform half of purge.py
    "data_catalog",       # in-process dict, dies with the process
    "idempotency",        # TTL-swept, not connection-keyed
    "pool",              # physical connections, evicted by _shared.invalidate_schema_cache
    "rebuild",            # Wave V2: forgotten via briefing.invalidate's own cascade
    "freeze",             # Wave V4: a pin dies with the artifact it pins
}


def _modules_exposing_an_invalidator() -> dict[str, list[str]]:
    """Every module that offers a connection-scoped invalidate/purge entry point."""
    found: dict[str, list[str]] = {}
    for path in (REPO / "aughor").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        src = path.read_text()
        fns = re.findall(
            r"^def (invalidate|purge_connection|purge_schema|clear_schema)\b", src, re.M)
        if fns:
            found.setdefault(path.stem, []).extend(fns)
    return found


def test_every_store_with_an_invalidator_is_registered_or_exempt():
    """The ratchet: a new connection-keyed store must join the purge cascade.

    Coverage is read from ``bootstrap.py``'s source — the registration point, and where a
    forgotten registration actually is. ``purge.py`` already *asks* authors to register a
    hook; this makes forgetting a red test rather than a privacy incident found later.
    """
    covered = _cascade_source()
    unregistered = {
        mod: fns for mod, fns in _modules_exposing_an_invalidator().items()
        if mod not in _EXEMPT and not re.search(rf"\b{re.escape(mod)}\b", covered)
    }
    assert not unregistered, (
        "these modules expose a connection-scoped invalidator but nothing in the delete "
        f"cascade reaches them: {sorted(unregistered)}. Register an agent hook in "
        "aughor/agent/bootstrap.py (register_purge_hook / register_schema_purge_hook), or "
        "purge it inline in aughor/db/purge.py if the PLATFORM owns it — or add the module "
        "to _EXEMPT with the reason it is not connection-keyed."
    )


def _cascade_source() -> str:
    """The whole delete cascade, both halves.

    ``purge.py``'s design splits it deliberately: *"the platform purges what it owns inline
    … and delegates every AGENT-owned store to registered purge hooks"*, so checking only
    bootstrap would flag platform-owned stores as orphaned. Found by this very ratchet, which
    reported ``type_overrides`` before learning to read ``purge.py:108`` too.
    """
    return "\n".join((
        (REPO / "aughor" / "agent" / "bootstrap.py").read_text(),
        (REPO / "aughor" / "db" / "purge.py").read_text(),
    ))


def test_the_ratchet_can_actually_fire():
    """Guards against a vacuous pass: a fabricated store must NOT look covered."""
    assert not re.search(r"\btotally_made_up_store\b", _cascade_source())


def test_exempt_baseline_has_not_grown():
    """Never raise a ratchet baseline — the repo rule, applied to this ratchet too."""
    assert len(_EXEMPT) <= 8


def test_the_registry_actually_has_hooks_registered(_registered):
    """Guards the ratchet against passing vacuously: if registration silently broke,
    `reachable` would be empty and every module would look 'covered' by an empty set."""
    assert len(_registered["conn"]) > 5, _registered["conn"]
    assert len(_registered["schema"]) > 2, _registered["schema"]


def test_registered_hook_names_are_the_real_labels(_registered):
    conn = set(_registered["conn"])
    for expected in ("ontology", "briefs", "monitors", "automations", "evidence"):
        assert expected in conn, (expected, sorted(conn))


def test_repeat_registration_cannot_duplicate_hooks():
    """A second registration must not double the hook list — duplicate hooks would
    double-count a purge and report more deleted than there was."""
    from aughor.agent import bootstrap
    from aughor.kernel.registries import purge_hooks

    _force_register()
    first = len(purge_hooks._CONN)
    assert first > 5, "guard against asserting equality of two empty lists"

    bootstrap.register_agent_plugins()          # guard should make this a no-op
    assert len(purge_hooks._CONN) == first

    _force_register()                           # a genuine re-register also stays level
    assert len(purge_hooks._CONN) == first
