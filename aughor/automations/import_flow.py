"""DS-16 · the migration funnel — Langflow (and archived-Flowise) flow JSON, imported.

Their format is the category's lingua franca and their users' exit path. It is also,
structurally, a code package: **every Langflow node carries its component's Python source
in a `code` template field, and their engine exec()s it in-process** (measured in the
2026-08-31 re-study; sandboxing is an open upstream proposal). So this importer never
reads a line of that code. It maps an ALLOWLIST of component classes onto our declared
kinds using only the template's VALUES — the declarations — and refuses everything else
with a sentence naming the law and, where one exists, the declarative alternative.
A node here is a REFERENCE to a governed capability, never an implementation.

What comes out:
- a DRAFT chain (conditions + effects) in exactly the shape the canvas-first create view
  seeds from — nothing saved, nothing armed, the DS-15 posture verbatim;
- a per-node REPORT (mapped / folded / dropped / refused, each with its reason) — the
  receipt §3.7 asks for is the report as much as the chain;
- optionally a SUGGESTED agent record (an Agent node's instructions), proposed as data
  for the human to create, never created here.

The mapping table is deliberately explicit and boring: their flow format migrates
in-engine upstream, and a table is what a quarterly release-tracking pass can diff.
Written against the flow-JSON shape at Langflow v1.12 / archived Flowise v3.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ── the dispositions a node can land in ──────────────────────────────────────────
MAPPED = "mapped"        # became a step in the draft
FOLDED = "folded"        # contributed text/config to another node's step (Prompt → question)
DROPPED = "dropped"      # structural in their model, meaningless in ours (ChatInput/Output)
REFUSED = "refused"      # carries or IS code, or names a capability we refuse to fake

_NO_CODE_LAW = (
    "Aughor refuses code injection by design: a node is a reference to a governed "
    "capability, never an implementation. "
)

#: Component classes that ARE code execution — refused with the law by name.
_CODE_CLASSES = {
    "pythonfunction", "pythonrepl", "pythonrepltool", "customcomponent", "code",
    "codeblock", "pythoncode", "runnablecode", "customjsfunction", "customfunction",
    "ifelse", "conditionalrouter",  # their router takes a Python predicate string
}

#: Model/agent classes → our one governed answer path. The MODEL CHOICE is dropped on
#: purpose: model routing belongs to the deployment (Settings → Models), never to a
#: flow file — the no-hardcoded-models law, applied at the border.
_LLM_CLASSES = {
    "openaimodel", "anthropicmodel", "azureopenaimodel", "ollamamodel", "googlemodel",
    "geminimodel", "groqmodel", "mistralmodel", "llmmodel", "languagemodel",
    "chatopenai", "chatanthropic", "chatollama", "azurechatopenai",  # flowise spellings
}
_AGENT_CLASSES = {
    "agent", "toolcallingagent", "reactagent", "crewaiagent", "openaitoolsagent",
    "conversationalagent", "agentexecutor",
}

#: Structural chat plumbing — their flows are conversations, our chains are triggered.
_STRUCTURAL = {"chatinput", "chatoutput", "textinput", "textoutput", "messagehistory",
               "memory", "conversationbuffermemory"}

_PROMPT_CLASSES = {"prompt", "prompttemplate", "chatprompttemplate"}

_SLACK_CLASSES = {"slacksend", "slackpost", "slacksendmessage", "slack"}

#: Classes whose honest alternative is DS-13's declarative http action.
_HTTP_CLASSES = {"apirequest", "httprequest", "webhook", "curlcomponent", "urlrequest",
                 "restcall"}


class NodeReport(BaseModel):
    node_id: str
    component: str
    disposition: str            # mapped | folded | dropped | refused
    detail: str
    #: The alias of the draft step this node became (or fed), "" otherwise.
    step: str = ""


class SuggestedAgent(BaseModel):
    name: str
    instructions: str


class ImportResult(BaseModel):
    verdict: str                # "imported" | "nothing_mapped" | "unreadable"
    source: str = ""            # "langflow" | "flowise" | ""
    name: str = ""
    draft: Optional[dict] = None            # {conditions, effects} — the canvas seed
    report: list[NodeReport] = Field(default_factory=list)
    suggested_agent: Optional[SuggestedAgent] = None
    reason: str = ""            # verdict != imported: the sentence


# ── format detection + neutral node view ─────────────────────────────────────────

class _Node(BaseModel):
    id: str
    cls: str                     # lowercased component class
    display: str
    values: dict[str, Any]       # template field → literal value (declarations only)


def _read_langflow(doc: dict) -> tuple[list[_Node], list[tuple[str, str]]]:
    nodes, edges = [], []
    data = doc.get("data") or {}
    for n in data.get("nodes") or []:
        nd = (n.get("data") or {})
        cls = str(nd.get("type") or "")
        template = ((nd.get("node") or {}).get("template") or {})
        values = {}
        for field, spec in template.items():
            if not isinstance(spec, dict):
                continue
            if str(spec.get("type") or "") == "code" or field == "code":
                continue                      # the one field this importer never reads
            if "value" in spec and spec["value"] not in (None, ""):
                values[field] = spec["value"]
        nodes.append(_Node(id=str(n.get("id") or cls), cls=cls.lower(), display=cls,
                           values=values))
    for e in data.get("edges") or []:
        s, t = str(e.get("source") or ""), str(e.get("target") or "")
        if s and t:
            edges.append((s, t))
    return nodes, edges


def _read_flowise(doc: dict) -> tuple[list[_Node], list[tuple[str, str]]]:
    nodes, edges = [], []
    for n in doc.get("nodes") or []:
        nd = (n.get("data") or {})
        cls = str(nd.get("name") or nd.get("type") or "")
        values = {k: v for k, v in (nd.get("inputs") or {}).items()
                  if isinstance(k, str) and v not in (None, "") and k != "code"}
        nodes.append(_Node(id=str(n.get("id") or cls), cls=cls.lower(), display=cls,
                           values=values))
    for e in doc.get("edges") or []:
        s, t = str(e.get("source") or ""), str(e.get("target") or "")
        if s and t:
            edges.append((s, t))
    return nodes, edges


def _detect(doc: dict) -> str:
    if isinstance(doc.get("data"), dict) and isinstance(doc["data"].get("nodes"), list):
        return "langflow"
    if isinstance(doc.get("nodes"), list):
        return "flowise"
    return ""


# ── the mapping ──────────────────────────────────────────────────────────────────

def _first_text(values: dict, *keys: str) -> str:
    for k in keys:
        v = values.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _downstream_of(node_id: str, edges: list[tuple[str, str]]) -> set[str]:
    return {t for s, t in edges if s == node_id}


def import_flow(doc: Any) -> ImportResult:
    """One flow document in, one honest result out. Pure — no store, no network."""
    if not isinstance(doc, dict):
        return ImportResult(verdict="unreadable",
                            reason="the file is not a JSON object — expected a Langflow "
                                   "or Flowise flow export")
    source = _detect(doc)
    if not source:
        return ImportResult(verdict="unreadable", reason=(
            "neither a Langflow export (data.nodes) nor a Flowise export (nodes) — "
            "export the flow as JSON from the editor and try that file"))
    nodes, edges = (_read_langflow(doc) if source == "langflow" else _read_flowise(doc))
    flow_name = str(doc.get("name") or doc.get("description") or "Imported flow").strip()

    report: list[NodeReport] = []
    effects: list[dict] = []
    suggested: Optional[SuggestedAgent] = None
    by_id = {n.id: n for n in nodes}
    step_of: dict[str, str] = {}      # source node id → the draft alias it became

    # Prompt text folds into the question of the LLM/Agent step it FEEDS. Collected
    # first so mapping order does not depend on node order in the file.
    prompt_for: dict[str, str] = {}
    for n in nodes:
        if n.cls in _PROMPT_CLASSES:
            text = _first_text(n.values, "template", "prompt", "system_message", "text")
            for target in _downstream_of(n.id, edges):
                tcls = by_id.get(target)
                if tcls and (tcls.cls in _LLM_CLASSES or tcls.cls in _AGENT_CLASSES):
                    prompt_for[target] = text

    def alias() -> str:
        return f"step{len(effects) + 1}"

    for n in nodes:
        if n.cls in _CODE_CLASSES:
            report.append(NodeReport(
                node_id=n.id, component=n.display, disposition=REFUSED,
                detail=_NO_CODE_LAW + "Its declarative alternative: declare the logic as "
                       "a governed action in the ontology (DS-13's described `http` call, "
                       "or a guard on the step that needs the condition)."))
            continue
        if n.cls in _HTTP_CLASSES:
            report.append(NodeReport(
                node_id=n.id, component=n.display, disposition=REFUSED,
                detail="an open HTTP call is refused at the border: declare it as an "
                       "ontology `http` action instead — a DESCRIBED call, filled and "
                       "never evaluated, its credential encrypted at rest — then add a "
                       "declared-action step and grant it."))
            continue
        if n.cls in _STRUCTURAL:
            report.append(NodeReport(
                node_id=n.id, component=n.display, disposition=DROPPED,
                detail="conversation plumbing — an Aughor chain is TRIGGERED (the "
                       "schedule stands where ChatInput stood), and every step's output "
                       "lands in the run history rather than a chat window."))
            continue
        if n.cls in _PROMPT_CLASSES:
            fed = [t for t in _downstream_of(n.id, edges) if t in prompt_for]
            report.append(NodeReport(
                node_id=n.id, component=n.display,
                disposition=FOLDED if fed else DROPPED,
                detail=("its template text became the downstream step's question"
                        if fed else
                        "a prompt feeding nothing mapped — its text had no step to join"),
            ))
            continue
        if n.cls in _LLM_CLASSES or n.cls in _AGENT_CLASSES:
            question = (prompt_for.get(n.id)
                        or _first_text(n.values, "input_value", "prompt", "question",
                                       "task", "objective")
                        or f"{flow_name}: answer the question this flow was built for")
            a = alias()
            step_of[n.id] = a
            effects.append({"kind": "investigate", "alias": a,
                            "config": {"question": question}})
            extra = ""
            if n.cls in _AGENT_CLASSES:
                instructions = _first_text(n.values, "system_prompt", "system_message",
                                           "instructions", "agent_description")
                if instructions and suggested is None:
                    suggested = SuggestedAgent(
                        name=f"{flow_name} agent"[:120], instructions=instructions[:8000])
                    extra = (" Its system prompt is proposed as a NEW agent record "
                             "(nothing created — review and create it, then bind the "
                             "step to it).")
            model_named = _first_text(n.values, "model_name", "model", "model_id")
            if model_named:
                extra += (f" The flow pinned model {model_named!r}; dropped — model "
                          "routing is the deployment's (Settings → Models), never a "
                          "flow file's.")
            report.append(NodeReport(
                node_id=n.id, component=n.display, disposition=MAPPED, step=a,
                detail="became an `investigate` step on the governed answer path."
                       + extra))
            continue
        if n.cls in _SLACK_CLASSES:
            a = alias()
            cfg: dict[str, Any] = {
                "channel": _first_text(n.values, "channel", "channel_id", "channel_name"),
                "message": _first_text(n.values, "message", "text", "input_value"),
            }
            # The flagship translation: an LLM/Agent feeding a Slack sender becomes
            # `{"$from": "<that step>.summary"}` — the report worth reading, bound the
            # way the daily briefing binds (2026-09-02). The FEEDER'S OWN step, looked
            # up by node id — the first-investigate shortcut would wire the wrong chain
            # the moment a flow holds two.
            for s, t in edges:
                if t == n.id and s in step_of:
                    cfg["message"] = {"$from": f"{step_of[s]}.summary"}
                    break
            effects.append({"kind": "slack_post", "alias": a, "config": cfg})
            report.append(NodeReport(
                node_id=n.id, component=n.display, disposition=MAPPED, step=a,
                detail="became a `slack_post` step" + (
                    " bound to the upstream step's summary."
                    if isinstance(cfg.get("message"), dict) else
                    "; fill channel/message before saving.")))
            continue
        report.append(NodeReport(
            node_id=n.id, component=n.display, disposition=REFUSED,
            detail=f"no governed mapping for {n.display!r}. " + _NO_CODE_LAW
                   + "If the capability exists here, add the step from the palette; "
                     "if it should exist, declare it (an ontology action, an "
                     "integration operation) and it becomes a step everywhere."))

    if not effects:
        return ImportResult(
            verdict="nothing_mapped", source=source, name=flow_name, report=report,
            reason="no node mapped onto a governed step — the report names each "
                   "refusal and its alternative")

    draft = {
        # Their flows run when invoked; ours run when due. The default schedule is the
        # honest stand-in, shown disarmed on the create canvas like any new chain.
        "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
        "effects": effects,
    }
    return ImportResult(verdict="imported", source=source, name=flow_name,
                        draft=draft, report=report, suggested_agent=suggested)
