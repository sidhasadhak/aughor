"""
ACTION: token expansion — M12b planner integration.

The planner writes  ACTION:action_id()  inside its SQL list instead of raw SQL.
plan_and_execute calls expand_actions() before execution, substituting the full
pre-verified SQL template from the ontology.  This enforces business rules
(active filters, correct date columns, standard aggregations) automatically without
the model needing to re-derive them from the schema on every query.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.ontology.models import OntologyGraph

# Matches ACTION:action_id() or ACTION:action_id(ignored_params)
_ACTION_PATTERN = re.compile(r"ACTION:(\w+)\([^)]*\)", re.IGNORECASE)


def expand_actions(
    sql_list: list[str],
    graph: Optional[OntologyGraph],
) -> tuple[list[str], list[str]]:
    """Substitute ACTION:name() tokens in SQL strings with their full templates.

    Returns (expanded_sqls, notes) where notes records each substitution made.
    Unknown ACTION: tokens are left as-is (the executor will error and self-correct).
    If graph is None or has no actions, returns sql_list unchanged with no notes.
    """
    if not graph or not graph.actions:
        return sql_list, []

    expanded: list[str] = []
    all_notes: list[str] = []

    for sql in sql_list:
        result, notes = _expand_one(sql, graph)
        expanded.append(result)
        all_notes.extend(notes)

    return expanded, all_notes


def _expand_one(sql: str, graph: OntologyGraph) -> tuple[str, list[str]]:
    notes: list[str] = []

    def _replace(m: re.Match) -> str:
        action_id = m.group(1)
        action = graph.actions.get(action_id)
        if action is None:
            return m.group(0)  # unknown — leave for executor to catch
        notes.append(
            f"ACTION:{action_id}() → {action.display_name}"
            + (
                f" (rules: {'; '.join(action.business_rules_enforced)})"
                if action.business_rules_enforced else ""
            )
        )
        return f"({action.sql_template})"

    return _ACTION_PATTERN.sub(_replace, sql), notes


def build_actions_prompt_section(graph: Optional[OntologyGraph]) -> str:
    """Build the ONTOLOGY ACTIONS block for injection into PLAN_QUERIES_PROMPT.

    Returns an empty string when there are no actions so the placeholder
    in the prompt template collapses cleanly.
    """
    if not graph or not graph.actions:
        return ""

    lines: list[str] = [
        "ONTOLOGY ACTIONS — pre-verified SQL templates with business rules enforced:",
        "Instead of writing raw SQL for the operations below, use ACTION:action_id() syntax.",
        "The runtime substitutes the full SQL before execution.",
        "",
    ]

    for action in graph.actions.values():
        entity_tag = f"[{action.entity}]" if action.entity else ""
        lines.append(f"ACTION:{action.id}()  {entity_tag}  — {action.description}")
        if action.business_rules_enforced:
            lines.append(f"  Rules: {'; '.join(action.business_rules_enforced)}")
        lines.append(f"  Returns: {action.returns}")

    lines.append("")
    lines.append(
        "Only use ACTION: tokens listed above. "
        "For any query not covered, write standard SQL as usual."
    )
    lines.append("")

    return "\n".join(lines)
