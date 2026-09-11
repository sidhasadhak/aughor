"""ON-3 — `get_object`: one business object, opened by its type and key, on every transport.

Declared into the SP-5 roster (`spotlight_roster`), so the conversation, `/spotlight/tools` and the
MCP server carry the same tool with the same description, and the parity ratchet holds the diff
empty. The body is `aughor.semantic.object_instances` — the reader `GET /objects/{type}/{pk}` serves —
over the served ontology graph, so an agent and the object page cannot disagree about what an
object is. `describe_entity` says what a TYPE is; this opens one instance of it.
"""
from __future__ import annotations

from aughor.agent.tool_loop import ToolSpec

#: Properties an object hands the model; the page shows them all.
_MAX_PROPERTIES = 40
#: Linked objects listed when a link is named.
_MAX_LINKED = 20

_OBJECT_PARAMS = {
    "type": "object",
    "properties": {
        "object_type": {"type": "string",
                        "description": "The object's type, by name — e.g. order, customer, product."},
        "key": {"type": "string", "description": "The object's key value — e.g. an order id or a customer id."},
        "link": {"type": "string",
                 "description": "Optional: one of the object's links, to list the first page of the objects it reaches."},
    },
    "required": ["object_type", "key"],
}


def get_object_tool(connection_id: str, args: dict) -> dict:
    """One object with its properties and links, or a found=False answer that says why."""
    from aughor.actions.overlay import accepted_object_edits
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.routers.ontology import resolve_effective_schema, served_ontology_graph
    from aughor.semantic.object_instances import ObjectNotFound, get_object, list_linked
    from aughor.semantic.object_query import ObjectQueryRefused

    object_type = str(args.get("object_type") or "").strip()
    key = str(args.get("key") or "").strip()
    if not object_type or not key:
        return {"error": "name the object's type and its key",
                "summary": "No object was opened: both a type and a key are needed."}
    graph = served_ontology_graph(connection_id, None)
    if graph is None:
        return {"found": False,
                "summary": "This connection has no ontology built, so it has no object types to open."}
    db = open_connection_for_with_schema(
        connection_id, graph.schema_name or resolve_effective_schema(connection_id, None))
    linked = None
    try:
        try:
            instance = get_object(graph, db, object_type, key, overlay=accepted_object_edits(connection_id))
        except ObjectNotFound as exc:
            return {"found": False, "summary": f"Not found: {exc}."}
        except ObjectQueryRefused as exc:
            return {"found": False, "summary": f"Not opened: {exc.reason}", "available": exc.available[:40]}
        link = str(args.get("link") or "").strip()
        if link:
            try:
                linked = list_linked(graph, db, object_type, key, link, limit=_MAX_LINKED)
            except (ObjectNotFound, ObjectQueryRefused) as exc:
                linked = {"link": link, "refused": getattr(exc, "reason", str(exc))}
    finally:
        db.close()

    out = instance.to_dict()
    properties = out.pop("properties")
    out["properties"] = [{"name": p["name"], "value": p["value"], **({"unit": p["unit"]} if p.get("unit") else {}),
                          **({"set_by": p["overlay"]["provenance"]} if p.get("overlay") else {})}
                         for p in properties[:_MAX_PROPERTIES]]
    out["properties_truncated"] = len(properties) > _MAX_PROPERTIES
    many = [f"{link['count']} via {link['name']}" for link in instance.links
            if link.get("usable") and link.get("kind") == "to-many"]
    named = f" ({instance.title})" if instance.title else ""
    out["found"] = True
    out["summary"] = (f"{instance.type_name} {instance.pk}{named}: {len(properties)} properties"
                      + (f"; linked objects: {', '.join(many)}" if many else "") + ".")
    if linked is not None:
        out["linked"] = linked
    return out


def object_tools(connection_id: str, *, session_id: str = "") -> list[ToolSpec]:
    """The object plane's reads for the roster — connection bound by closure, like every tool."""
    return [
        ToolSpec(
            name="get_object",
            description=(
                "Open ONE business object by its type and key — an order, a customer, a product — "
                "read live from the warehouse through the ontology: its properties, and each of its "
                "links resolved to the linked object's key (when it reaches one object) or a count "
                "(when it reaches many); name a link to list a page of the objects it reaches. Use "
                "it when a question or an answer names a specific object ('order O000123', 'this "
                "customer'); use describe_entity for what a type is. It never guesses: an unknown "
                "type or key comes back not found, and a link the ontology cannot vouch for is shown "
                "with its reason and not followed. Quote the summary field verbatim for the counts."
            ),
            parameters=_OBJECT_PARAMS,
            run=lambda a: get_object_tool(connection_id, a),
        ),
    ]
