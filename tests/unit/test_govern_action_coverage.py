"""Wave G1 — a declared governed action must actually be enforced.

**The gap this closes.** ``govern.actions._RISK`` declared 11 mutating actions and their risk
tiers. Only four of them were ever passed to :func:`aughor.govern.guard`, so with
``AUGHOR_ACTION_APPROVAL`` on — the only configuration in which governance means anything — an
operator was promised that high-risk actions require approval and got it for **three of the
seven HIGH actions**. Dropping a schema, dropping a table, importing an ontology tree and
approving a metric all walked straight past the gate they were classified for. Nothing was
broken; the declaration simply had no enforcement behind it, which is the flag-drift shape one
layer up (a capability that is declared, believed, and absent).

Two checks, because neither alone is enough:

- :func:`test_every_declared_action_is_enforced` is the **ratchet**. It reads the guarded
  action names out of the router sources, so a newly declared action with no call site fails
  here rather than in production six months later. Coverage drift re-accumulates — #199
  cleared 19 stale flags and it came back as 23 — so the check has to be structural.
- :class:`TestApprovalActuallyBlocks` is the **behaviour**. A name appearing in a source file
  proves a string exists, not that a request is refused; these drive the real dependency and
  assert the 428.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aughor.govern.actions import ActionRisk, _RISK, classify

ROUTERS = Path(__file__).resolve().parents[2] / "aughor" / "routers"


def _guarded_action_names() -> set[str]:
    """Every action name the routers can pass to ``guard`` — literals and mapped values.

    A guard called with a name looked up from a module-level mapping is still enforcement.
    Reading only literal arguments would report those as gaps and pressure the code into the
    shape the checker can parse, which is how a check starts dictating design instead of
    describing it. Mapping constants are named ``*GUARDED*`` by convention and their string
    values count.
    """
    names: set[str] = set()
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            # govern.guard("x", …) / guard("x", …)
            if isinstance(node, ast.Call):
                fn = node.func
                fname = (fn.attr if isinstance(fn, ast.Attribute)
                         else fn.id if isinstance(fn, ast.Name) else "")
                if fname == "guard" and node.args:
                    a0 = node.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        names.add(a0.value)
            # GUARDED_* = {"verb": "action.name", …}
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any("GUARDED" in t for t in targets) and isinstance(node.value, ast.Dict):
                    names.update(v.value for v in node.value.values
                                 if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return names


def test_every_declared_action_is_enforced():
    """The ratchet: declaring a risk tier and never gating the action is the bug."""
    guarded = _guarded_action_names()
    missing = sorted(set(_RISK) - guarded)
    assert not missing, (
        f"{len(missing)} action(s) are declared in govern.actions._RISK but never passed to "
        f"govern.guard(): {missing}. A declared risk tier with no call site is a promise the "
        f"platform does not keep — wire the guard at the mutation site, or remove the "
        f"declaration."
    )


def test_high_risk_actions_are_all_gated():
    """Named separately because HIGH is the tier that BLOCKS; a gap here is a security gap,
    not merely a missing audit row."""
    guarded = _guarded_action_names()
    high = {a for a, r in _RISK.items() if r == ActionRisk.HIGH}
    assert not (high - guarded), f"unenforced HIGH-risk actions: {sorted(high - guarded)}"


def test_an_undeclared_action_still_classifies_high():
    """The fail-safe the anti-pattern table calls read-by-default: unknown ⇒ HIGH."""
    assert classify("something.nobody.declared") == ActionRisk.HIGH


class TestApprovalActuallyBlocks:
    """A source-level name proves a string exists. These prove a request is refused."""

    @pytest.fixture(autouse=True)
    def _approval_on(self, monkeypatch):
        monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")

    @pytest.mark.parametrize("action", sorted(a for a, r in _RISK.items()
                                              if r == ActionRisk.HIGH))
    def test_high_action_refuses_without_a_grant(self, action, monkeypatch):
        from fastapi import HTTPException

        from aughor import govern

        monkeypatch.setattr(govern.actions, "is_allowed", lambda a, s: False)
        with pytest.raises(HTTPException) as exc:
            govern.guard(action, "scope-with-no-grant")
        assert exc.value.status_code == 428
        assert exc.value.detail["error"] == "approval_required"
        assert exc.value.detail["action"] == action

    @pytest.mark.parametrize("action", sorted(a for a, r in _RISK.items()
                                              if r == ActionRisk.LOW))
    def test_low_action_is_allowed_and_audited(self, action, monkeypatch):
        """LOW is auto-allowed — the guard is there for the trail, not the block."""
        seen: list[tuple] = []
        from aughor import govern

        monkeypatch.setattr(govern.actions, "audit",
                            lambda a, s, d, **k: seen.append((a, s, d)))
        govern.guard(action, "any-scope")          # must not raise
        assert seen and seen[0][0] == action and seen[0][2] == "auto"

    def test_approval_off_is_a_no_op_for_every_action(self, monkeypatch):
        """The default posture: governance is opt-in, so a fresh clone is unchanged by G1."""
        monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
        from aughor import govern

        for action in _RISK:
            govern.guard(action, "scope")          # must not raise for any tier
