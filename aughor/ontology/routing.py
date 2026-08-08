"""Table-routing guidance — "for this kind of question, query that table instead".

The one reader of the ``use_instead`` override field (see
:mod:`aughor.ontology.overrides`), shared by every place that narrows the schema
before it reaches a model. It exists as its own module for two reasons:

* **There is more than one door to the prompt.** The vector retriever
  (``semantic/retriever.py``) and the schema linker (``tools/schema_linker.py``,
  reached from four call sites) both cut the schema down independently. Enforcing at
  one while the other drops the preferred table is the both-ends-exist-but-the-
  feature-doesn't failure this repo has hit before, so both consume this one helper.
* **It must stay import-clean.** ``aughor/ontology/*`` may not import ``aughor/llm/*``
  (``tests/unit/test_ontology_llm_boundary.py``) — knowledge stores stay
  deterministic and hermetic. Nothing here touches a model or a network.

Two properties are deliberate and load-bearing:

**Additive only.** A rule contributes the preferred table to a keep-set; it never
removes the deprecated one. Scope matching is a substring heuristic over the user's
words, so a wrong match must degrade to "the model saw one extra table", never to
"the model lost the table holding the answer".

**Unbound is inert.** A rule whose named table did not existence-bind is ignored
outright. That is what makes a typo — or a view on a connection whose schema
rendering excludes views — harmless instead of a prompt pointing at nothing.

Data-gated, no flag: a connection with no ``use_instead`` overrides gets an empty
rule list, and every consumer's behaviour is then byte-identical by construction.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Scope words are matched on word boundaries, lowercased.
_WORD_RE = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class RoutingRule:
    """One bound "prefer ``preferred`` over ``deprecated``" instruction."""

    #: The entity's own table — the one a question would otherwise land on.
    deprecated: str
    #: The table to add to the schema instead. Existence-bound at write time.
    preferred: str
    #: Free text describing WHEN this applies ("general sales calculations"). Empty
    #: means always. Matched leniently — see :meth:`applies_to`.
    scope: str = ""
    #: Why, in the author's words. Shown to the model; never parsed.
    reason: str = ""
    #: Who said so and when, for the annotation's credit line.
    source: str = "human"
    edited_at: str = ""

    def applies_to(self, question: str) -> bool:
        """Whether this rule's scope matches ``question``.

        An empty scope always applies. Otherwise: any scope word of four or more
        characters appearing in the question is a match. Deliberately lenient in the
        permissive direction, because the cost of a false positive is one extra table
        in the prompt while the cost of a false negative is the guidance silently not
        working — which is how a human concludes the feature is broken and stops
        using it. Short words are dropped so "for", "the" and "and" cannot match
        everything.
        """
        if not self.scope.strip():
            return True
        q = question.lower()
        words = [w for w in _WORD_RE.findall(self.scope.lower()) if len(w) >= 4]
        return any(w in q for w in words) if words else True


def routing_rules(connection_id: str, schema_name: str = "") -> list[RoutingRule]:
    """Every BOUND routing rule for a connection, or ``[]``.

    ``schema_name`` empty means **every schema stored under this connection**, not the
    literal scope ``"default"``. That is not a shortcut: the override store is keyed by
    ``(connection, schema)`` but the schema linker — one of the two enforcement doors —
    is only ever handed a connection id, so a strict lookup would silently find nothing
    for exactly the connections whose schema is named. Widening is safe because a rule
    only fires when its deprecated table is already in the keep-set: a rule from
    another schema names a table this question never reached, so it stays silent.

    Never raises and never returns an unbound rule: the store is best-effort by design
    (a hand-edited YAML file must not blind the rest), and a routing rule that cannot
    be trusted is worse than no rule at all.
    """
    try:
        from aughor.ontology.overrides import (
            load_overrides,
            override_scopes,
            preferred_table,
        )
    except Exception:
        logger.debug("routing: override store unavailable", exc_info=True)
        return []

    rules: list[RoutingRule] = []
    try:
        if schema_name:
            overrides = load_overrides(connection_id or "default", schema_name)
        else:
            overrides = []
            for scope in override_scopes(connection_id or "default"):
                overrides.extend(load_overrides(connection_id or "default", scope))
    except Exception:
        logger.debug("routing: could not load overrides", exc_info=True)
        return []

    for ov in overrides:
        if ov.target_kind != "entity":
            continue
        value = ov.fields.get("use_instead")
        if not value:
            continue
        # The bind gate, applied at READ time as well as write time: an override file
        # can be copied between connections or hand-edited, and the binding recorded
        # on it is a claim about the DB it was bound against.
        if not ov.sql_field_ok("use_instead"):
            logger.debug("routing: skipping unbound use_instead on %s", ov.target_id)
            continue
        table = preferred_table(value)
        if not table:
            continue
        scope = str(value.get("scope") or "") if isinstance(value, dict) else ""
        reason = str(value.get("reason") or "") if isinstance(value, dict) else ""
        rules.append(RoutingRule(
            deprecated=ov.target_id, preferred=table, scope=scope, reason=reason,
            source=ov.source or "human", edited_at=(ov.edited_at or "")[:10],
        ))
    return rules


def preferred_for(question: str, tables, connection_id: str,
                  schema_name: str = "") -> list[str]:
    """Preferred tables to ADD, given the tables a narrowing step is about to keep.

    ``tables`` is any iterable of table names already in the keep-set. A rule fires
    when its deprecated table is in that set and its scope matches the question — so
    guidance only speaks when the question actually reached the table it is about.
    Returns names not already present, in rule order, deduped.
    """
    rules = routing_rules(connection_id, schema_name)
    if not rules:
        return []
    have = {_bare(t) for t in tables}
    out: list[str] = []
    for rule in rules:
        if _bare(rule.deprecated) not in have:
            continue
        if not rule.applies_to(question):
            continue
        if _bare(rule.preferred) in have or rule.preferred in out:
            continue
        out.append(rule.preferred)
    return out


def _bare(table: str) -> str:
    """Comparison key for a possibly schema-qualified table name."""
    return (table or "").strip().lower().rsplit(".", 1)[-1]
