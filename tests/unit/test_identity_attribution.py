"""RC-4 — a governed record names a principal, or admits it does not know one.

The plane this wave fixes was not missing; it was LYING. `govern.actions.audit` filled an
absent actor with `current_org_id()`, so on the live ledger 34 of 67 governed decisions are
attributed to `default` — the TENANT, not a person. A blank prompts the question "who?"; a
plausible wrong value closes it. That is the defect, and the first test below is the one
that would have caught it.

The properties locked here:

* **The absent case is named, never borrowed.** No actor ⇒ `unattributed`, never the org.
* **A label is not an identity.** `"human"`, `"agent-ops"`, `"me"` — all present in the live
  ledger — do not become identities just because something has to go in the field.
* **Linking is an upgrade, not a precondition.** An unlinked `slack:U…` still attributes.
* **A body-supplied principal can never override an authenticated one.** This is the whole
  security surface of the feature: a headless door says who it acts FOR; no caller gets to
  say who it IS.

Hermetic: conftest temp DBs, the real store, the real ledger.
"""
from __future__ import annotations

import pytest

from aughor.identity import UNATTRIBUTED, Identity, attribution_key, parse_ref, resolve
from aughor.identity import store as ident_store


# ── the defect ───────────────────────────────────────────────────────────────────

def test_an_absent_actor_is_unattributed_never_the_org():
    """THE regression test for this wave. `actor or current_org_id()` put the tenant in
    the actor field, and an audit trail that answers 'who approved this refund?' with the
    org name reads as attributed while carrying no information at all."""
    from aughor.govern import actions as govern
    from aughor.org.context import current_org_id

    govern.audit("connection.delete", "conn-a", "approved")
    row = govern.recent_audit(5)[0]

    assert row["actor"] == UNATTRIBUTED
    assert row["actor"] != current_org_id(), "the tenant is not an actor"
    assert row["org_id"] == current_org_id(), "the tenant is still recorded, just not AS the actor"


def test_a_supplied_actor_survives_unchanged():
    """The fix must not eat information. `automation:<id>` is weak but real, and it is
    what the caller meant."""
    from aughor.govern import actions as govern
    govern.audit("connection.delete", "conn-b", "auto", actor="automation:abc-123")
    assert govern.recent_audit(5)[0]["actor"] == "automation:abc-123"


# ── parsing: a label is not an identity ──────────────────────────────────────────

@pytest.mark.parametrize("raw", ["slack:U08N9EQ80UT", "web:amit@example.com", "api:key-7"])
def test_well_formed_refs_parse(raw):
    ident = parse_ref(raw)
    assert ident is not None and ident.ref == raw


@pytest.mark.parametrize("raw", ["human", "agent-ops", "me", "", "default", ":U123", "slack:"])
def test_labels_and_junk_are_not_identities(raw):
    """Every one of these except the last two appears in the live ledger today. Promoting
    a label to an identity is how a trail acquires confident nonsense."""
    assert parse_ref(raw) is None


def test_external_id_may_contain_colons():
    """Only the FIRST colon splits, so a composite external key needs no escaping."""
    ident = parse_ref("slack:T01:U02")
    assert ident is not None
    assert ident.provider == "slack" and ident.external_id == "T01:U02"


def test_provider_is_normalised_but_a_bad_provider_is_refused():
    assert parse_ref("SLACK:U1").provider == "slack"
    assert parse_ref("has space:U1") is None
    assert parse_ref("9bad:U1") is None, "a provider must start with a letter"


# ── attribution_key: total, and ordered by how much it actually knows ────────────

def test_attribution_key_is_total():
    """Every input yields a usable key. Totality is the point: the defect came from an
    `or` reaching for whatever was in scope when the real value was missing."""
    for raw in ["", "   ", None]:
        assert attribution_key(raw) == UNATTRIBUTED


def test_unlinked_identity_still_attributes():
    assert attribution_key("slack:U08N9EQ80UT") == "slack:U08N9EQ80UT"


def test_a_linked_identity_resolves_to_the_platform_user():
    ident_store.put_link("slack", "U08N9EQ80UT", "amit@example.com", linked_by="admin")
    assert attribution_key("slack:U08N9EQ80UT") == "amit@example.com"


def test_an_unparseable_actor_is_passed_through_not_discarded():
    """`agent-ops` is weak, but it is information the caller supplied."""
    assert attribution_key("agent-ops") == "agent-ops"


# ── the link store ───────────────────────────────────────────────────────────────

def test_link_round_trip_and_relink():
    ident_store.put_link("slack", "U1", "a@example.com")
    assert ident_store.get_link("slack", "U1") == "a@example.com"
    ident_store.put_link("slack", "U1", "b@example.com")     # idempotent upsert, not a duplicate
    assert ident_store.get_link("slack", "U1") == "b@example.com"
    assert ident_store.delete_link("slack", "U1") is True
    assert ident_store.get_link("slack", "U1") is None


def test_links_for_user_answers_the_continuity_question():
    """'Which external identities is this person?' — the query Slack↔web continuity asks."""
    ident_store.put_link("slack", "U9", "same@example.com")
    ident_store.put_link("web", "same@example.com", "same@example.com")
    got = {r["provider"] for r in ident_store.links_for_user("same@example.com")}
    assert got == {"slack", "web"}


def test_resolve_survives_a_broken_link_store(monkeypatch):
    """Attribution must never be the reason a governed action fails — `slack:U…` is still
    an honest answer when the table cannot be read."""
    monkeypatch.setattr("aughor.identity.store.get_link",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    ident = resolve("slack:U1")
    assert ident is not None and ident.attribution_key == "slack:U1"
    assert ident.linked is False


def test_identity_model_never_returns_an_empty_key():
    assert Identity(provider="slack", external_id="U1").attribution_key == "slack:U1"
    assert Identity(provider="slack", external_id="U1", user_id="a@b").attribution_key == "a@b"


# ── the /ask seam: attribution flows ambiently, and cannot be spoofed ────────────

async def _drain(gen):
    return [e async for e in gen]


def test_ask_pins_the_asker_so_telemetry_attributes_it():
    """`trace_identity()` already reads `current_user_id()` — nobody was SETTING it on a
    headless door, which is why LF-2's user field was empty while the machinery looked
    fine. This drives the real wrapper and asserts the contextvar is live mid-stream.
    """
    import asyncio
    from aughor.org.context import current_user_id
    from aughor.routers.investigations import _stream_with_session

    seen: list[str] = []

    async def _body():
        seen.append(current_user_id())
        yield "frame"

    # A deliberately UNLINKED id: an earlier test in this file links U08N9EQ80UT, and
    # reusing it here would assert the linked value while looking like a wrapper bug.
    asyncio.run(_drain(_stream_with_session("s1", _body(), "slack:UASKER1")))
    assert seen == ["slack:UASKER1"]
    assert current_user_id() == "", "the pin must not leak past the stream"


def test_a_body_principal_never_overrides_an_authenticated_one():
    """THE security invariant. A headless door says who it acts FOR; no caller gets to
    say who it IS. With a verified identity already in scope, the body field is ignored.
    """
    import asyncio
    from aughor.org.context import current_user_id, reset_user_id, set_user_id
    from aughor.routers.investigations import _stream_with_session

    seen: list[str] = []

    async def _body():
        seen.append(current_user_id())
        yield "frame"

    token = set_user_id("real@example.com")     # as the identity middleware would
    try:
        asyncio.run(_drain(_stream_with_session("s2", _body(), "slack:ATTACKER")))
    finally:
        reset_user_id(token)

    assert seen == ["real@example.com"], "a body field must not win over a verified identity"


def test_no_principal_leaves_the_asker_unset():
    """Absent identity stays absent — the wrapper invents nothing."""
    import asyncio
    from aughor.org.context import current_user_id
    from aughor.routers.investigations import _stream_with_session

    seen: list[str] = []

    async def _body():
        seen.append(current_user_id())
        yield "frame"

    asyncio.run(_drain(_stream_with_session("s3", _body(), "")))
    assert seen == [""]
