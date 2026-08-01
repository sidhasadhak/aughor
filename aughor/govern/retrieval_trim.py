"""Wave G5 — trim retrieved context by clearance, and SAY what was withheld.

G2 built the tag plane and the clearance decision; this is where it bites. Three retrieval
paths feed a prompt with facts about tables — the connection-graph read-back, trusted query
patterns, and glossary/synonym resolution — and none of them asked whether the caller may
see the tables involved.

**The rule this wave exists to honour.** A permission-trimmed answer that comes back empty
teaches its reader that the data does not exist. That is the pinned anti-pattern from
docs/GENIE_DOCS_TEARDOWN_2026-07-26.md, and it is worse than a refusal: the reader stops
asking. So trimming here
always produces two things — what survived, and a sentence naming what did not and which
clearance would restore it. A caller may withhold the rows. It may not withhold the fact
that rows were withheld.

**Withholding a node withholds its edges too.** A join edge names both of its endpoints, so
keeping an edge whose far end was trimmed leaks the very table name the clearance protects
— and leaks it in the most load-bearing position, as a fact the prompt treats as ground
truth. The edge sweep is not tidiness; it is the actual boundary.

**Trimming happens at RETRIEVAL, never at rendering.** A blocked fact must not reach the
prompt at all: once it is in the context window the model may repeat it, and a redaction
applied to the output is a redaction applied after the leak. This module is therefore
called by the builders, not by the formatters.

Pure and store-free: :func:`partition` takes the securables and the clearances. Resolving a
caller's clearances and reading tags is the caller's half.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Optional, Sequence, TypeVar

from aughor.govern.tags import ClearanceDecision

T = TypeVar("T")


@dataclass
class TrimResult:
    """What survived, what did not, and the sentence that says so."""

    kept: list = field(default_factory=list)
    withheld: list = field(default_factory=list)
    #: securable → the decision that blocked it, for the receipt.
    decisions: dict = field(default_factory=dict)

    @property
    def trimmed(self) -> bool:
        return bool(self.withheld)

    def notice(self) -> str:
        """The out-of-band sentence. Empty when nothing was withheld.

        Names the count and the clearances rather than the objects: telling a reader that
        `salaries` exists is exactly what the tag was protecting, so the notice says how
        much was withheld and what would unblock it, not what it was.
        """
        if not self.withheld:
            return ""
        needed = sorted({r.clearance
                         for d in self.decisions.values() for r in d.missing})
        n = len(self.withheld)
        return (f"[{n} item{'s' if n != 1 else ''} withheld by data governance — "
                f"access requires {', '.join(needed) or 'additional clearance'}]")

    def to_dict(self) -> dict:
        return {"kept": len(self.kept), "withheld": len(self.withheld),
                "trimmed": self.trimmed, "notice": self.notice(),
                "clearances_required": sorted(
                    {r.clearance for d in self.decisions.values() for r in d.missing})}


def partition(
    items: Sequence[T],
    securables_of: Callable[[T], object],
    clearances: Iterable[str],
    *,
    check: Optional[Callable[[str, Iterable[str]], ClearanceDecision]] = None,
    bypass: bool = False,
) -> TrimResult:
    """Split ``items`` into what the caller may see and what it may not.

    ``securables_of`` returns the securable(s) an item is about — one string, a sequence
    of them, or ``None``/empty when the item is not about a governed object. **Several is
    the normal case, not an edge case:** a graph table node is an ontology *entity*, and an
    entity can be backed by more than one physical table. An item is withheld when ANY of
    its securables is blocked, because showing an entity whose backing table is restricted
    shows the restricted thing.

    An item whose securables cannot be determined is KEPT rather than withheld: the tag
    plane is opt-in per object, and failing closed on an unresolvable name would make
    enabling the flag a platform-wide outage instead of a policy (the same default G2
    chose).

    ``check`` is injectable so the policy can be exercised without a store.
    """
    if check is None:
        from aughor.govern.tags import check as _check

        def check(securable: str, held: Iterable[str]) -> ClearanceDecision:  # noqa: E306
            return _check(securable, held, bypass=bypass)

    held = list(clearances)
    result = TrimResult()
    for item in items:
        raw = securables_of(item)
        securables = ([raw] if isinstance(raw, str) else list(raw or []))
        securables = [s for s in securables if s]
        if not securables:
            result.kept.append(item)
            continue
        blocked: list[tuple[str, ClearanceDecision]] = []
        for securable in securables:
            decision = check(securable, held)
            if not decision.allowed:
                blocked.append((securable, decision))
        if blocked:
            result.withheld.append(item)
            for securable, decision in blocked:
                result.decisions[securable] = decision
        else:
            result.kept.append(item)
    return result


def sweep_edges(edges: Sequence, kept_node_ids: set[str]) -> list:
    """Drop edges with an endpoint that did not survive the trim.

    A join edge names both endpoints, so an edge kept across a trimmed boundary leaks the
    protected table's name as prompt ground truth — the leak the node trim was for.
    """
    return [e for e in edges
            if getattr(e, "from_id", None) in kept_node_ids
            and getattr(e, "to_id", None) in kept_node_ids]


def securable_for_table(connection_id: str, schema_name: str, table: str) -> str:
    """The securable a graph table node is about, in the metastore's one vocabulary."""
    from aughor.metastore.models import table_securable

    bare = str(table or "").split(".")[-1]
    return table_securable(connection_id, schema_name or "", bare)


#: The clearances the running code holds. A contextvar for exactly the reason
#: ``org/context.py`` uses one: retrieval happens deep inside call chains that have no
#: ``Request``, and threading a clearance list through every one of them is how a site
#: gets missed. Defaults empty.
_current_clearances: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "aughor_current_clearances", default=())


def caller_clearances() -> list[str]:
    """The clearances the current caller holds.

    **Nothing sets this yet, and that is deliberate rather than unfinished.** There is no
    ambient principal in this codebase — ``security.authz`` resolves one from a
    ``Request``, and retrieval runs far from any request object. Wiring a real source is
    the grant surface's job (G6) plus a deployment's identity setup, which G3a measured is
    absent in local mode (``user_id`` 0% populated).

    The consequence is worth stating plainly, because it is the conservative direction and
    somebody will hit it: with ``govern.clearances`` ON and no clearance source wired,
    every TAGGED object is withheld from everybody. Untagged objects are unaffected, tags
    are opt-in per object, and the flag is off by default — so this is a deployment that
    asked for denial and got it, not a silent regression. Use :func:`clearance_context` to
    supply clearances until a principal-backed source exists.
    """
    return [c for c in _current_clearances.get() if str(c).strip()]


def set_clearances(clearances: Iterable[str]):
    """Pin the caller's clearances; returns a token for :func:`reset_clearances`."""
    return _current_clearances.set(tuple(str(c) for c in clearances))


def reset_clearances(token) -> None:
    try:
        _current_clearances.reset(token)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "clearance context reset is best-effort",
                 counter="govern.clearance_context")


@contextmanager
def clearance_context(clearances: Iterable[str]) -> Iterator[None]:
    """Run a block with the given clearances held."""
    token = set_clearances(clearances)
    try:
        yield
    finally:
        reset_clearances(token)
