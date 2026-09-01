"""DS-11 — the roster's own invariants: what stops a closed set from quietly opening.

`operations.py` is data, and data is exactly what nobody re-reads. These are the four
properties that make it safe to add a seventh row without re-deriving the whole design —
each one a mistake a new entry can make in one line and nobody notices for a quarter:

* **Every URL placeholder is a declared path param.** A `{foo}` with no `in_path` param
  behind it is never substituted, so the literal braces travel to the provider — and a
  path param with no placeholder is silently sent as a query key instead.
* **Every operation's scopes are covered by its provider's `default_scopes`.** A row that
  needs a scope a fresh grant never asks for is a row that dims for every user on every
  install, forever, with no way to fix it from the UI.
* **Nothing declares a `publishes` key it cannot fill.**
* **A write is a write.** `writes` is set from what the operation DOES, not from the verb,
  and a write must carry HIGH risk or the approval gate lets it through.
"""
from __future__ import annotations

import pytest

from aughor.integrations.operations import (
    OPERATIONS, ResultShape, build_request, extract, get_operation,
)
from aughor.integrations.providers import PROVIDERS


def test_the_guard_actually_parsed_something():
    """Vacuous-pass guard: an empty roster lets every assertion below iterate nothing."""
    assert len(OPERATIONS) >= 6, f"only {len(OPERATIONS)} operations — the roster is not loaded"


@pytest.mark.parametrize("op", OPERATIONS, ids=lambda o: o.id)
def test_every_url_placeholder_is_a_declared_path_param(op):
    declared = {p.name for p in op.params if p.in_path}
    assert set(op.path_params) == declared, (
        f"{op.id}: URL placeholders {op.path_params} vs declared path params {declared}")


@pytest.mark.parametrize("op", OPERATIONS, ids=lambda o: o.id)
def test_every_operation_is_reachable_with_the_scopes_its_provider_asks_for(op):
    """Otherwise the row dims for every user on every install and no button fixes it."""
    provider = PROVIDERS.get(op.provider)
    assert provider is not None, f"{op.id} names provider '{op.provider}', which is not one"
    granted = set(provider.default_scopes.split())
    assert set(op.scopes) <= granted, (
        f"{op.id} needs {sorted(set(op.scopes) - granted)}, which "
        f"{provider.name}'s default_scopes never request")


@pytest.mark.parametrize("op", OPERATIONS, ids=lambda o: o.id)
def test_a_write_carries_the_risk_that_makes_the_gate_fire(op):
    """`guard` only stops a HIGH-risk action. A write at LOW risk is a write with a gate
    in front of it that opens for everyone — worse than no gate, because it reads as one."""
    if op.writes:
        assert op.risk == "high", f"{op.id} changes something at {op.provider} at {op.risk} risk"


@pytest.mark.parametrize("op", OPERATIONS, ids=lambda o: o.id)
def test_the_declared_keys_are_the_keys_extract_can_actually_fill(op):
    """`publishes` is what `validate_chain` refuses an unknown binding against, so a key
    listed and never produced would refuse the right bindings and satisfy none of them."""
    payload = {}
    if op.result.items_path:
        payload[op.result.items_path] = []
    got = extract(op, payload)
    assert set(got) == set(op.publishes), f"{op.id}: {sorted(got)} vs {sorted(op.publishes)}"


@pytest.mark.parametrize("op", OPERATIONS, ids=lambda o: o.id)
def test_a_bindable_path_param_still_cannot_reach_outside_its_segment(op):
    """The closed URL set's whole guarantee, asserted per row rather than once: a new
    operation with a path param inherits the encoding without anyone remembering to."""
    if not op.path_params:
        return
    params = {p.name: ("../../x" if p.in_path else (p.default or "v")) for p in op.params}
    url, _query, _body = build_request(op, {k: v for k, v in params.items() if v is not None})
    assert "/../" not in url and not url.endswith("/..")
    assert "%2F" in url, f"{op.id}: a path value was not percent-encoded"


def test_ids_are_unique_and_the_lookup_agrees_with_the_roster():
    ids = [op.id for op in OPERATIONS]
    assert len(ids) == len(set(ids)), "two operations share an id; a step would pick one"
    assert all(get_operation(i) is not None for i in ids)
    assert get_operation("nope") is None and get_operation("") is None


def test_a_list_operation_declares_which_key_is_the_list():
    """The half `/automations/vocabulary` cannot answer. Before DS-11 nothing in the
    automation plane published a list, so the client's rule was "open set ⇒ fannable";
    a closed set containing one needs the list NAMED or a fan-out cannot be validated."""
    for op in OPERATIONS:
        if op.result.items_path:
            assert op.list_keys == ("items",), op.id
            assert "items" in op.publishes and "count" in op.publishes
        else:
            assert op.list_keys == (), op.id


def test_an_item_is_reduced_to_its_declared_fields():
    """The bound on what a remote read drags into a stored run. Graph returns WHOLE
    messages here, bodies included, and a run history is read by people and kept."""
    op = get_operation("graph.messages.list")
    got = extract(op, {"value": [{"id": "1", "subject": "hi", "webLink": "u",
                                  "receivedDateTime": "t",
                                  "body": {"content": "x" * 100_000}}]})
    assert got["items"] == [{"id": "1", "subject": "hi", "receivedDateTime": "t",
                             "webLink": "u"}]


def test_an_item_with_nothing_to_reduce_survives_whole():
    """A list of bare ids has no fields to keep; dropping it would lose the list."""
    op = get_operation("gmail.messages.list").model_copy(
        update={"result": ResultShape(items_path="messages")})
    assert extract(op, {"messages": ["a", "b"]})["items"] == ["a", "b"]
