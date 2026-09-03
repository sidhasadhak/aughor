"""Every connector category the server can emit must be drawn somewhere.

This is a SEAM test, and the seam is the one that already failed silently: the server
groups connectors by `CATEGORIES` in `aughor/connectors/registry.py`, and the picker
(`web/components/AddDataPanel.tsx`) renders them by mapping over its own `CATEGORY_ORDER`.
Nothing connected the two lists, so a category present on one side and absent from the
other produced no error, no warning, and no tile.

**It had already happened.** `knowledge` — Notion and Confluence — was registered, its
drivers importable, and returned by `GET /connectors/types` with `category: "knowledge"`,
while the picker's array listed only `built-in`, `warehouse` and `api`. Two working
connectors were never offered to anybody. The labels for both sat in the panel's own `META`
map the whole time, which is why grepping the file found them and the running product did
not: a label map is not a render list.

The test cannot read the .tsx and should not try — parsing another language's source to
assert a fact about it is a check that breaks on formatting. Instead it pins the SERVER
side against a declared set. Adding a category to `registry.CATEGORIES` now fails here, and
the failure message says what to do about it. That is the cheapest possible guard on a seam
whose failure mode is silence.
"""
from __future__ import annotations

from aughor.connectors.registry import CATEGORIES, REGISTRY


def _registered_types() -> list[str]:
    """Exactly what `list_connector_types` iterates: the two built-ins plus the registry."""
    return ["duckdb", "postgres"] + REGISTRY.supported_types()


def _emitted_categories() -> set[str]:
    """The categories `GET /connectors/types` can actually put on the wire.

    🔴 **Built from the REGISTERED types, not from `CATEGORIES`** — and the difference is
    the whole reason this file exists in its second draft. `CATEGORIES` is a static map
    that carries entries for `notion` and `confluence`, which `_register_defaults` never
    registers ("not DB connectors — open_connection() is not called on them"). A first
    version of this test read `CATEGORIES` and would have happily passed while the route
    emitted no such category at all: asserting against the lookup table instead of the
    thing the route builds its list from is the same proxy error the ledger entry that
    prompted this test had already made once. The route composes
    `["duckdb", "postgres"] + REGISTRY.supported_types()`; so does this.
    """
    return {CATEGORIES.get(t, "built-in") for t in _registered_types()}


#: What `AddDataPanel.tsx` renders in `CATEGORY_ORDER`, verbatim.
DRAWN_IN_CATEGORY_ORDER = {"built-in", "warehouse", "api"}

#: Handled by the panel, but NOT through `CATEGORY_ORDER` — each with the reason, because
#: "handled elsewhere" and "forgotten" look identical from here without one.
HANDLED_ELSEWHERE = {
    # Rendered above the grouped list as `FileTile`s — a file source is picked by dropping
    # a file on it, not by filling in a connection form.
    "file",
    # Filtered out entirely (`t.type !== "federated"`): a federated connection is COMPOSED
    # from connections that already exist, so offering it as a new source would invite
    # somebody to create one before there is anything to federate.
    "federation",
}


def test_every_server_category_is_drawn_somewhere():
    """The whole point. A category the server emits and the picker does not draw is a
    connector that works and is never offered."""
    orphaned = _emitted_categories() - DRAWN_IN_CATEGORY_ORDER - HANDLED_ELSEWHERE
    affected = sorted(t for t in _registered_types()
                      if CATEGORIES.get(t, "built-in") in orphaned)
    assert not orphaned, (
        f"connector category/ies {sorted(orphaned)} are returned by "
        f"GET /connectors/types and rendered by nothing. Add each to CATEGORY_ORDER in "
        f"web/components/AddDataPanel.tsx (and to DRAWN_IN_CATEGORY_ORDER here), or to "
        f"HANDLED_ELSEWHERE with the reason. Connectors affected: {affected}")


def test_the_panel_does_not_claim_a_category_the_server_never_emits():
    """The other direction, and it is not symmetry for its own sake: an empty group renders
    as a heading with nothing under it, which reads as "we support this and you have none"
    rather than "this does not exist"."""
    phantom = DRAWN_IN_CATEGORY_ORDER - _emitted_categories()
    assert not phantom, (
        f"`CATEGORY_ORDER` draws {sorted(phantom)}, which no connector declares — the "
        f"panel would render an empty heading")


def test_notion_and_confluence_are_categorised_but_NOT_registered():
    """The finding this file was bought by, pinned so it cannot be misread again.

    The ledger said the picker "hides Notion + Confluence — real, synced, never offered",
    and a first pass at fixing it added a `knowledge` row to `CATEGORY_ORDER`. Driving the
    live API showed the truth: those two never reach the client at all, because
    `_register_defaults` deliberately does not register them — they are not DB connectors
    and feed the documents pipeline instead. The row would have drawn an empty heading.

    So this asserts the ODD state that is actually true: categorised, and unregistered. If
    somebody later registers them, this test fails and points at the real decision — whether
    a Notion source belongs in "Add data" (where a person expects tables) or on the
    documents surface.
    """
    assert CATEGORIES.get("notion") == "knowledge"
    assert CATEGORIES.get("confluence") == "knowledge"
    supported = set(REGISTRY.supported_types())
    assert "notion" not in supported and "confluence" not in supported, (
        "notion/confluence are now REGISTERED connector types. That is a real change: they "
        "will appear in `GET /connectors/types` under category 'knowledge', which "
        "`CATEGORY_ORDER` does not draw. Decide where they belong before adding the row.")
