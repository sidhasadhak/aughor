"""ON-0 — the prompt-reach audit: which ontology fields can change what a model sees.

The question Arc ON (ROADMAP §3.15) opens with is not "what does the ontology store" but
"what of it reaches an agent". Reading renderers answers that by recollection, and the
recollection rots (the ledger's own lesson, three times in one week). This module answers
it by MEASUREMENT, with one definition that cannot be argued with:

    a field REACHES a prompt block iff changing its value changes the block's text.

So the audit builds one fully-populated fixture graph, renders every prompt block on the
answer path that is a pure function of the graph, then mutates each leaf field of the
ontology model in turn — every instance at that path at once — and re-renders. A block
whose text moved is a block that field reaches. Booleans flip, literals switch to a
sibling value, strings and lists grow a sentinel, so a field that only gates output
(``verified``) is caught exactly like one that is printed (``filter_sql``).

What is deliberately NOT measured here, and why it is still named in the report:

* blocks that are functions of OTHER stores (human synonyms, routing rules, the metrics
  catalog) — they are not graph fields, so "reach" is not the question for them;
* prompt text assembled inline inside a pipeline node (the planner's APPROVED METRIC
  FORMULAS in ``agent/nodes.py``, the explorer's Phase-8 entity prose in
  ``explorer/agent.py``) — an inline site cannot be rendered in isolation, which is
  precisely why the deep-analysis intake block was extracted into
  :func:`aughor.ontology.semantic_block.render_entity_context` so it COULD be. Each
  remaining inline site is listed in :data:`INLINE_SITES` so the count is honest.

Deterministic, no model, no database: runs in a unit test, which is what makes it a
ratchet (``tests/unit/test_ontology_prompt_reach.py`` pins the measured reach and refuses
a change that silently shrinks it).

    python -m aughor.ontology.prompt_reach            # the table
    python -m aughor.ontology.prompt_reach --json     # machine-readable
    python -m aughor.ontology.prompt_reach --census   # declared actions on disk
"""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union, get_args, get_origin

from pydantic import BaseModel

from aughor.ontology.models import (
    ActionParameter,
    ComputedProperty,
    DefinitionSource,
    EntityProperty,
    KineticAction,
    OntologyEntity,
    OntologyGraph,
    OntologyInterface,
    OntologyMetric,
    OntologyRelationship,
    QueryTemplate,
    Segment,
    SideEffect,
    SubmissionCriterion,
)

#: The sentinel every string/list mutation carries. Distinctive on purpose: a renderer
#: that echoes a field verbatim shows it, and no fixture value contains it.
MUT = "ZZMUT"

#: The columns the fixture's two tables carry — the "currently rendered schema" the
#: relationship block existence-binds against. Must agree with :func:`fixture_graph`.
FIXTURE_TABLE_COLS: dict[str, list[str]] = {
    "orders": ["order_id", "customer_id", "order_status", "order_value", "created_at"],
    "customers": ["customer_id", "full_name", "country", "signup_date"],
}


# ── The fixture: one graph with every field populated ────────────────────────────────

def fixture_graph() -> OntologyGraph:
    """A graph in which EVERY field holds a distinctive, non-default value.

    Non-default matters: a renderer that only prints a field when it is set would read
    as "unreached" on a sparse fixture, and the audit would under-count. Every gate a
    renderer has (``verified``, ``has_lifecycle``, a non-``RELATES_TO`` verb, a
    ``join_confidence`` the block admits) is OPEN here, so the only way a field reads
    as unreached is that no renderer looks at it.
    """
    order = OntologyEntity(
        id="Order",
        display_name="Customer Order",
        description="A confirmed purchase progressing from placed to delivered or canceled.",
        source_tables=["orders"],
        identity_key="order_id",
        grain_verified=True,
        domain="Commerce",
        entity_type="business_object",
        has_lifecycle=True,
        lifecycle_column="order_status",
        lifecycle_states=["placed", "shipped", "delivered", "canceled"],
        terminal_states=["delivered", "canceled"],
        active_filter="order_status NOT IN ('delivered', 'canceled')",
        use_instead={"table": "customers", "scope": "customer counts",
                     "reason": "orders repeats a customer per purchase"},
        segments={
            "all_orders": Segment(id="all_orders", display_name="All Orders",
                                  description="Every order row", filter_sql="",
                                  is_default=True, source="lifecycle", verified=True,
                                  verification_note="trivial"),
            "active_orders": Segment(id="active_orders", display_name="Active Orders",
                                     description="Orders not yet closed",
                                     filter_sql="order_status NOT IN ('delivered', 'canceled')",
                                     is_default=False, source="lifecycle", verified=True,
                                     verification_note="executed"),
        },
        created_at_col="created_at",
        default_filters=["exclude test orders"],
        exclude_when=["the order is a warranty replacement"],
        properties={
            "order_value": EntityProperty(
                name="order_value", display_name="Order Value", data_type="DECIMAL",
                semantic_type="measure", description="Gross order total before refunds",
                is_primary_key=False, is_foreign_key=False, is_nullable=True,
                null_rate=0.02, null_meaning="not yet priced", is_derived=False,
                value_interpretation="currency", measure_grain="per_line", unit="USD",
                sample_values=["12.50", "99.00"], distribution_shape="skewed_right",
                p25=10.0, p50=40.0, p75=120.0,
            ),
        },
        computed_properties=[ComputedProperty(
            id="days_since_order", label="Days Since Order",
            formula_sql="DATEDIFF('day', created_at, NOW())", unit="days",
            verified=True, verification_note="executed")],
        implements=["HasLifecycle"],
        exploration_insights=["32% of orders never reach a terminal state"],
    )
    customer = OntologyEntity(
        id="Customer", display_name="Customer",
        description="A person or organisation that has placed at least one order.",
        source_tables=["customers"], identity_key="customer_id", grain_verified=True,
        domain="Customer", entity_type="reference_data", created_at_col="signup_date",
    )
    rel = OntologyRelationship(
        id="Order_placed_by_Customer", from_entity="Order", to_entity="Customer",
        verb="placed by", cardinality="N:1",
        join_sql="orders.customer_id = customers.customer_id",
        from_table="orders", from_col="customer_id", to_table="customers", to_col="customer_id",
        join_confidence="verified", nullable=True, value_overlap=0.98,
    )
    metric = OntologyMetric(
        id="revenue", display_name="Revenue", description="Recognised order revenue",
        entity="Order", formula_sql="SUM(order_value)", grain="order", unit="USD",
        tables=["orders"], known_divergent_calculations=["SUM(order_items.line_total)"],
        target_value=1_000_000.0, warning_threshold=800_000.0, critical_threshold=600_000.0,
        target_period="monthly", benchmark_source="internal: FY plan",
        verified=True, verification_note="executed",
        definitions=[DefinitionSource(
            formula_sql="SUM(order_value)", source_asset="Finance dashboard",
            source_kind="dashboard", author="finance@example.com",
            recorded_at="2026-09-01", use_count=7, certified=True, verified=True,
            verification_note="executed")],
    )
    template = QueryTemplate(
        id="active_orders_count", display_name="Active order count",
        description="Count of orders not yet closed", entity="Order",
        action_type="aggregate",
        sql_template="SELECT COUNT(*) FROM orders WHERE order_status NOT IN ('delivered', 'canceled')",
        parameters=[ActionParameter(name="since", display_name="Since", data_type="DATE",
                                    required=False, description="Lower bound on created_at",
                                    default_value="2026-01-01")],
        business_rules_enforced=["exclude terminal states"],
        returns="one row, one integer", source_table="orders", origin="structural", usage_count=3,
    )
    action = KineticAction(
        id="flag_order_for_review", display_name="Flag order for review",
        description="Mark an order for a human look", entity="Order", kind="side_effect",
        params=[ActionParameter(name="order_id", display_name="Order", data_type="INTEGER",
                                required=True, description="The order to flag",
                                default_value=None)],
        rule="",
        submission_criteria=[SubmissionCriterion(expr="order_id > 0",
                                                 message="An order id is positive.")],
        side_effects=[SideEffect(kind="notify", config={"channel": "ops"})],
        risk="high", parallel_safe=False, origin="manual",
    )
    iface = OntologyInterface(
        id="HasLifecycle", display_name="Has Lifecycle",
        description="Any entity with a named status machine",
        property_patterns=["a status column with terminal states"],
        implementing_entities=["Order"],
    )
    return OntologyGraph(
        connection_id="fixture", schema_name="default", schema_fingerprint="fx",
        generated_at="2026-09-10T00:00:00+00:00", enriched=True, enrichment_version=3,
        validated=True, validation_version=2,
        entities={"Order": order, "Customer": customer},
        relationships={rel.id: rel},
        metrics={metric.id: metric},
        actions={template.id: template},
        kinetic_actions={action.id: action},
        interfaces={iface.id: iface},
        entity_to_tables={"Order": ["orders"], "Customer": ["customers"]},
        table_to_entity={"orders": "Order", "customers": "Customer"},
        relationship_index={"Order": [rel.id], "Customer": [rel.id]},
    )


# ── The blocks: every pure graph → prompt-text renderer on the answer path ───────────

@dataclass(frozen=True)
class Block:
    name: str
    #: Where it rides — the phase and scope a reader needs to know how often it is seen.
    rides: str
    #: The consumer that puts it in front of a model, ``file:line``.
    consumer: str
    render: Callable[[OntologyGraph], str]


def _entity_model(g: OntologyGraph) -> str:
    from aughor.ontology.builder import render_ontology_annotations
    return render_ontology_annotations(g)


def _relationships(g: OntologyGraph) -> str:
    from aughor.ontology.semantic_block import render_relationship_block
    return render_relationship_block(g, FIXTURE_TABLE_COLS)


def _semantic_layer(g: OntologyGraph) -> str:
    from aughor.ontology.semantic_block import render_semantic_layer
    return render_semantic_layer(g, list(FIXTURE_TABLE_COLS))


def _query_templates(g: OntologyGraph) -> str:
    from aughor.ontology.actions import build_actions_prompt_section
    return build_actions_prompt_section(g)


def _metric_contract(g: OntologyGraph) -> str:
    """What survives RESOLUTION into the one metric contract the planner renders.

    The planner's APPROVED METRIC FORMULAS line prints the contract's label, key, sql,
    caveats and wrong-usage examples (``agent/nodes.py``), never the OntologyMetric — so
    for a metric field the honest question is whether it reaches the contract at all.
    """
    from aughor.semantic.contracts import SemanticContract
    return json.dumps(
        [SemanticContract.from_ontology_metric(m).model_dump(mode="json")
         for m in g.metrics.values()],
        sort_keys=True, default=str)


def _actions_declared(g: OntologyGraph) -> str:
    from aughor.actions.propose import build_kinetic_actions_section
    return build_kinetic_actions_section(g)


def _intake_entity_context(g: OntologyGraph) -> str:
    from aughor.ontology.semantic_block import entity_intake_fields, render_entity_context
    return "\n".join(render_entity_context(entity_intake_fields(e)) for e in g.entities.values())


BLOCKS: tuple[Block, ...] = (
    Block("entity_model", "heavy phase · schema-wide (every chat + deep prompt once intelligence is built)",
          "aughor/agent/schema_annotators.py:262", _entity_model),
    Block("relationships", "heavy phase · schema-wide; question-scoped again on /ask",
          "aughor/routers/investigations.py:1859", _relationships),
    Block("semantic_layer", "question-scoped · /ask (verified-gated)",
          "aughor/routers/investigations.py:1841", _semantic_layer),
    Block("query_templates", "planner · deep analysis",
          "aughor/agent/nodes.py:662", _query_templates),
    Block("metric_contract", "resolution → the planner's APPROVED METRIC FORMULAS",
          "aughor/semantic/canonical.py:137 → aughor/agent/nodes.py:683", _metric_contract),
    Block("actions_declared", "proposer · after every deep synthesis (data-gated)",
          "aughor/agent/investigate.py:3787 → aughor/actions/propose.py:62", _actions_declared),
    Block("intake_entity_context", "deep analysis · baseline plan",
          "aughor/agent/investigate.py (intake → baseline plan)", _intake_entity_context),
)

#: Prompt sites the harness cannot render in isolation, named so the count stays honest.
INLINE_SITES: tuple[tuple[str, str], ...] = (
    ("aughor/agent/nodes.py:683-700", "APPROVED METRIC FORMULAS — renders the resolved contract "
                                      "(label · key · sql · caveats · wrong-usage), measured here as `metric_contract`"),
    ("aughor/explorer/agent.py:2605-2615", "Phase-8 hypothesis prose — entity display_name · source_tables · "
                                           "description; relationship verb · cardinality (exploration path, not the answer path)"),
)


# ── The walk: every leaf field of the model, and one mutation per leaf ───────────────

def _is_model(t: Any) -> bool:
    return isinstance(t, type) and issubclass(t, BaseModel)


def _leaf_paths(obj: BaseModel, prefix: str = "") -> list[tuple[str, str, Any]]:
    """(path, owning model name, annotation) for every leaf under ``obj``.

    Path grammar: ``a.b`` a field, ``a.*.b`` a field on every value of a dict,
    ``a[].b`` a field on every element of a list.
    """
    out: list[tuple[str, str, Any]] = []
    for name, info in type(obj).model_fields.items():
        value = getattr(obj, name)
        ann = info.annotation
        path = f"{prefix}{name}"
        if isinstance(value, BaseModel):
            out += _leaf_paths(value, path + ".")
        elif isinstance(value, dict) and value and all(isinstance(v, BaseModel) for v in value.values()):
            out += _leaf_paths(next(iter(value.values())), path + ".*.")
        elif isinstance(value, list) and value and all(isinstance(v, BaseModel) for v in value):
            out += _leaf_paths(value[0], path + "[].")
        else:
            out.append((path, type(obj).__name__, ann))
    return out


def _mutated(value: Any, ann: Any) -> Any:
    """A different, VALID value for ``ann`` — the one change that decides reach."""
    origin, args = get_origin(ann), get_args(ann)
    if origin is Literal:
        for alt in args:
            if alt != value:
                return alt
        raise ValueError(f"Literal with one value cannot be mutated: {ann}")
    if origin is Union:  # Optional[X]
        inner = [a for a in args if a is not type(None)]
        if value is None:
            return _fresh(inner[0])
        return _mutated(value, inner[0])
    if ann is bool or isinstance(value, bool):
        return not value
    if ann is int:
        return int(value or 0) + 1
    if ann is float:
        return float(value or 0.0) + 0.5
    if ann is str:
        return f"{value} {MUT}".strip()
    if origin is list or ann is list:
        return list(value or []) + [MUT]
    if origin is dict or ann is dict:
        out = dict(value or {})
        out[MUT] = MUT
        return out
    raise TypeError(f"no mutation rule for {ann!r} (value {value!r})")


def _fresh(t: Any) -> Any:
    """A set value for a field that is None in the fixture."""
    origin = get_origin(t)
    if t is str:
        return MUT
    if t is int:
        return 1
    if t is float:
        return 0.5
    if t is bool:
        return True
    if origin is list or t is list:
        return [MUT]
    if origin is dict or t is dict:
        return {MUT: MUT}
    raise TypeError(f"no fresh value for {t!r}")


def _apply(obj: Any, parts: list[str], ann: Any) -> None:
    """Mutate the leaf at ``parts`` on EVERY instance reachable from ``obj``."""
    head, rest = parts[0], parts[1:]
    if head == "*":
        for v in obj.values():
            _apply(v, rest, ann)
        return
    if head.endswith("[]"):
        for v in getattr(obj, head[:-2]):
            _apply(v, rest, ann)
        return
    if not rest:
        setattr(obj, head, _mutated(getattr(obj, head), ann))
        return
    _apply(getattr(obj, head), rest, ann)


def _split(path: str) -> list[str]:
    return path.split(".")


# ── The audit ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reach:
    path: str
    model: str
    blocks: tuple[str, ...]   # the blocks whose text changed; () = reaches nothing

    @property
    def reached(self) -> bool:
        return bool(self.blocks)


@dataclass(frozen=True)
class Audit:
    rows: tuple[Reach, ...]
    #: Every block rendered non-empty on the fixture — a renderer that silently returned
    #: "" would make every field under it read as unreached, so the audit checks.
    rendered: dict[str, int]

    @property
    def reached(self) -> list[Reach]:
        return [r for r in self.rows if r.reached]

    @property
    def unreached(self) -> list[Reach]:
        return [r for r in self.rows if not r.reached]

    def by_model(self) -> dict[str, tuple[int, int]]:
        """model → (reached, total)."""
        out: dict[str, list[int]] = {}
        for r in self.rows:
            slot = out.setdefault(r.model, [0, 0])
            slot[1] += 1
            slot[0] += int(r.reached)
        return {k: (v[0], v[1]) for k, v in out.items()}

    def to_dict(self) -> dict:
        return {
            "measured": "a field reaches a block iff changing it changes the block's text",
            "blocks": [{"name": b.name, "rides": b.rides, "consumer": b.consumer,
                        "fixture_chars": self.rendered.get(b.name, 0)} for b in BLOCKS],
            "inline_sites": [{"where": w, "what": d} for w, d in INLINE_SITES],
            "fields": [{"path": r.path, "model": r.model, "blocks": list(r.blocks)} for r in self.rows],
            "summary": {"fields": len(self.rows), "reached": len(self.reached),
                        "unreached": len(self.unreached),
                        "by_model": {k: {"reached": a, "total": b} for k, (a, b) in self.by_model().items()}},
        }

    def to_markdown(self) -> str:
        lines = ["| Field | Model | Reaches |", "|---|---|---|"]
        for r in self.rows:
            lines.append(f"| `{r.path}` | {r.model} | {', '.join(r.blocks) if r.blocks else '—'} |")
        s = self.to_dict()["summary"]
        lines.append("")
        lines.append(f"**{s['reached']} of {s['fields']} fields reach at least one prompt block; "
                     f"{s['unreached']} reach none.**")
        for model, (a, b) in self.by_model().items():
            lines.append(f"- {model}: {a}/{b}")
        return "\n".join(lines)


def _render_all(g: OntologyGraph) -> dict[str, str]:
    return {b.name: b.render(g) for b in BLOCKS}


def audit(graph: Optional[OntologyGraph] = None) -> Audit:
    base = graph or fixture_graph()
    base_text = _render_all(base)
    rows: list[Reach] = []
    for path, model, ann in _leaf_paths(base):
        g = copy.deepcopy(base)
        _apply(g, _split(path), ann)
        moved = tuple(name for name, text in _render_all(g).items() if text != base_text[name])
        rows.append(Reach(path=path, model=model, blocks=moved))
    return Audit(rows=tuple(rows), rendered={k: len(v) for k, v in base_text.items()})


# ── The declared-action census: actions on disk, per connection and schema ──────────

def action_census(root: Optional[Path] = None) -> dict[str, list[str]]:
    """``"{conn}/{schema}" → [action ids]`` from the overrides tree — the number Arc ON's
    verb-layer claim rests on. Counts FILES, which is what a declaration is here."""
    from aughor.ontology.overrides import overrides_root
    base = root or overrides_root()
    out: dict[str, list[str]] = {}
    if not base.exists():
        return out
    for f in sorted(base.glob("*/*/action/*.yaml")):
        scope = f"{f.parents[2].name}/{f.parents[1].name}"
        out.setdefault(scope, []).append(f.stem)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--census" in args:
        census = action_census()
        total = sum(len(v) for v in census.values())
        print(json.dumps({"declared_actions": census, "total": total}, indent=2))
        return 0
    a = audit()
    if "--json" in args:
        print(json.dumps(a.to_dict(), indent=2))
        return 0
    print("ON-0 · prompt reach — a field reaches a block iff changing it changes the block's text\n")
    for b in BLOCKS:
        print(f"  {b.name:24} {a.rendered[b.name]:5d} chars   rides: {b.rides}\n{'':32}consumer: {b.consumer}")
    print()
    print(a.to_markdown())
    print("\nInline prompt sites not rendered by this harness:")
    for where, what in INLINE_SITES:
        print(f"  - {where}: {what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
