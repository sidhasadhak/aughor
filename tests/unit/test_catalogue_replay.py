"""Arc OC-2's falsifier, read again with every census reading (2026-10-10).

"Replay the declarations' history: every past change that broke a consumer must class as ERR or WARN — one miss and the
catalogue is wrong." It was replayed once, by hand, over theLook's twelve changes on 2026-10-09: thin, to be re-run as
history grows. `compatibility.replay` re-runs it over every change a reader saw (drafts skipped), and for a process or a
rule judges *moved* from the definitions consumers compile — its segments, rate, lags and overdue list; its filters —
not from the field names the catalogue classes by, so the two can disagree. The census journals it each day.
"""
from __future__ import annotations

import copy

import pytest

from aughor.kernel import lifecycle
from aughor.ontology import compatibility as C
from aughor.ontology.history import KIND, element_key

PROCESS = {"display_name": "Order fulfilment", "entity": "Order", "stages": [
    {"name": "placed", "timestamp": "created_at"},
    {"name": "shipped", "timestamp": "shipped_at", "promise": {"name": "dispatch", "within_days": 2}}]}
RULE = {"entity": "Order", "kind": "value_set", "property": "status", "values": ["Complete"]}


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    ledger = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: ledger))


def _keep(kind: str, target: str, *versions: tuple[str, dict]) -> None:
    for state, fields in versions:
        lifecycle.record(KIND, element_key("c1", "s", kind, target), {"target_kind": kind, "target_id": target,
                         "fields": fields}, state, by="ana", conn_id="c1")


def _with(**change) -> dict:
    out = copy.deepcopy(PROCESS)
    for key, value in change.items():
        if key == "within_days":
            out["stages"][1]["promise"]["within_days"] = value
        else:
            out[key] = value
    return out


def test_every_change_a_reader_saw_is_classed_and_what_it_moved_is_read_from_the_compiled_definitions():
    _keep("process", "order_fulfilment",
          ("published", _with()),
          ("draft", _with(within_days=9)),                                  # never in force: not a change anyone saw
          ("published", _with(within_days=3)),                              # the promise moved
          ("published", _with(display_name="Fulfilment")),                  # words only... and the promise back to 2
          ("published", _with(leaves={"property": "status", "values": ["Cancelled"]})),
          ("archived", _with(leaves={"property": "status", "values": ["Cancelled"]})))
    _keep("rule", "completed", ("published", RULE), ("published", {**RULE, "values": ["Complete", "Shipped"]}))
    out = C.replay()
    assert out["changes"] == 5 and out["judged"] == 4 and out["withdrawals"] == 1 and out["unread"] == 0
    assert out["moved"] == 4 and out["misses"] == []
    assert out["by_class"]["SAFE"] == 1                                     # the withdrawal nothing relied on
    assert sum(out["by_class"].values()) == 5


def test_a_promise_added_under_its_own_name_renames_the_stages_lag_and_is_warned():
    """Found by this replay's first run over theLook's kept history: adding the *dispatch* promise on stage *shipped*
    renamed `shipped_lag_days` to `dispatch_lag_days`, and the catalogue had classed it SAFE."""
    bare = {**PROCESS, "stages": PROCESS["stages"][:1] + [{"name": "shipped", "timestamp": "shipped_at"}]}
    _keep("process", "p", ("published", bare), ("published", _with()), ("published", _with(display_name="x")))
    out = C.replay()
    assert (out["changes"], out["moved"], out["misses"]) == (2, 1, [])
    cls, reasons = C.classify("process", bare, _with())
    assert cls == "WARN" and "shipped_lag_days → dispatch_lag_days" in reasons[0]["why"]
    same = copy.deepcopy(bare)
    same["stages"][1]["promise"] = {"name": "shipped", "within_days": 2}
    assert C.classify("process", bare, same)[0] == "SAFE"                    # named for its stage: nothing renamed


def test_one_change_that_moved_a_definition_and_was_classed_safe_is_a_miss(monkeypatch):
    """The falsifier's teeth: a catalogue that read a moved promise as safe is named, with what moved."""
    _keep("process", "order_fulfilment", ("published", _with()), ("published", _with(within_days=3)))
    monkeypatch.setattr(C, "classify", lambda kind, before, after, **k: ("SAFE", [{"class": "SAFE", "why": "x"}]))
    (miss,) = C.replay()["misses"]
    assert miss["element"].endswith("/process/order_fulfilment") and (miss["from"], miss["to"]) == (1, 2)
    assert miss["moved"] == ["dispatch_breach_rate", "late_dispatch", "overdue_dispatch"]


def test_the_census_journals_the_replay_with_each_reading(monkeypatch):
    from aughor.ontology import census
    _keep("rule", "completed", ("published", RULE), ("published", {**RULE, "values": ["Complete", "Shipped"]}))
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "ontology.census")
    monkeypatch.setattr(census, "take_census", lambda: {"totals": {}, "scopes": [], "not_built": [], "leaned_on": {},
                                                        "keyed": {}, "replay": census._replay()})
    assert census.record_if_due() is not None
    (kept,) = census.history()
    assert kept["replay"]["changes"] == 1 and kept["replay"]["by_class"]["MEANING"] == 1
