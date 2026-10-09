"use client";

/**
 * OntologyPieceComposer — placing a piece bound to the ontology on a cockpit, by hand (Arc OC-4, ROADMAP §3.56).
 *
 * Four kinds, each named by the ids the ontology declares: a process board (a process), an objects table (an entity,
 * and perhaps one of its segments — a rule's, a promise's late or overdue objects, a verified one — with the columns
 * a person picks), an object detail (the table it follows, and the declared actions it offers), and an action button
 * (a declared action, in a detail that is already there). What is offered is what this connection declares; nothing
 * here writes a definition. The server checks every id again before the cockpit is kept.
 */
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { SelectField } from "@/components/ui/select";
import { getOntologyKeys } from "@/lib/api";
import { MAX_TABLE_COLUMNS } from "@/lib/cockpit/catalog";
import { withUniqueKeys } from "@/lib/listKeys";
import { addAction, placePiece, sectionsOf, type CockpitSpec } from "@/lib/cockpit/edit";
import { getDeclaredActions, type DeclaredAction } from "@/lib/objects";
import { getObjectType, getProcesses, type ObjectTypeDetail, type ProcessesAndRules } from "@/lib/objectTypes";

type Kind = "board" | "table" | "detail" | "action";
const KINDS: { kind: Kind; label: string; says: string }[] = [
  { kind: "board", label: "Process board", says: "a declared process: its stages, its promises, and the objects open and overdue" },
  { kind: "table", label: "Objects table", says: "an entity, or one of its segments, a page at a time" },
  { kind: "detail", label: "Object detail", says: "the object chosen in a table, with the declared actions it offers" },
  { kind: "action", label: "Action button", says: "a declared action, added to a detail already here" },
];

const words = (id: string) => id.replace(/_/g, " ");
const word = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** The declared actions that take one object of ``entity``. */
function actionsOn(actions: Record<string, DeclaredAction>, entity: string): DeclaredAction[] {
  return Object.values(actions).filter(a => a.params.some(p => p.kind === "object" && word(p.object_type) === word(entity)));
}

export function OntologyPieceComposer({ connectionId, schema, spec, busy, onPlace, onClose }: {
  connectionId: string;
  schema?: string;
  spec: CockpitSpec;
  busy: boolean;
  /** Hands back the change, the version's note and what to tell the person. */
  onPlace: (change: (s: CockpitSpec) => CockpitSpec, note: string, said: string) => void;
  onClose: () => void;
}) {
  const [kind, setKind] = useState<Kind>("board");
  const [processes, setProcesses] = useState<ProcessesAndRules | null>(null);
  const [entities, setEntities] = useState<{ id: string; label: string }[]>([]);
  const [actions, setActions] = useState<Record<string, DeclaredAction>>({});
  const [problem, setProblem] = useState("");
  const sections = sectionsOf(spec);
  const [section, setSection] = useState(sections[0]?.key ?? "");

  useEffect(() => {
    let alive = true;
    Promise.all([getProcesses(connectionId, schema), getOntologyKeys(connectionId, schema), getDeclaredActions(connectionId, schema)])
      .then(([p, k, a]) => { if (alive) { setProcesses(p); setEntities(k.entities); setActions(a); } })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [connectionId, schema]);

  // A board.
  const [process, setProcess] = useState("");
  // A table — and, with it, a detail that follows it.
  const [entity, setEntity] = useState("");
  const [type, setType] = useState<ObjectTypeDetail | null>(null);
  const [segment, setSegment] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [withDetail, setWithDetail] = useState(true);
  const [chosenActions, setChosenActions] = useState<string[]>([]);
  // A detail or a button, on what the cockpit already holds.
  const [table, setTable] = useState("");
  const [detail, setDetail] = useState("");
  const [action, setAction] = useState("");

  useEffect(() => {
    setType(null); setSegment(""); setColumns([]); setChosenActions([]);
    if (!entity) return;
    let alive = true;
    getObjectType(entity, connectionId, schema)
      .then(t => { if (alive && t.path === "object_type") setType(t); })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [entity, connectionId, schema]);

  const tables = Object.entries(spec.elements).filter(([, el]) => el.type === "ObjectTable");
  const details = Object.entries(spec.elements).filter(([, el]) => el.type === "ObjectDetail");
  const entityOf = (tableKey: string) => String(spec.elements[tableKey]?.props.entity ?? "");

  /** Every segment of the chosen entity a table may read: a verified one, a derived one that is usable, and each
   *  measured promise's overdue objects. */
  const segments = useMemo(() => {
    if (!type) return [] as { name: string; says: string }[];
    const out = new Map<string, string>();
    for (const s of type.segments) out.set(s, "a verified segment");
    for (const d of type.derived?.segments ?? []) if (d.usable) out.set(d.name, d.description);
    for (const p of processes?.processes ?? []) {
      for (const st of p.stages) {
        const pr = st.promise;
        if (pr?.overdue_segment && word(pr.grain_id) === word(type.id) && pr.verified) {
          out.set(pr.overdue_segment, `still waiting for ${st.display_name} and already past the ${words(pr.name)} promise`);
        }
      }
    }
    return [...out].map(([name, says]) => ({ name, says }));
  }, [type, processes]);

  /** The properties a table may list: the entity's own, and each one a declared action's edit writes. */
  const offered = useMemo(() => {
    if (!type) return [] as { name: string; label: string; edited: boolean }[];
    const own = type.properties.filter(p => !p.is_key).map(p => ({ name: p.name, label: p.display_name || p.name, edited: false }));
    const edits = actionsOn(actions, type.id).flatMap(a =>
      (a.edits ?? []).map(e => ({ name: e.property, label: words(e.property), edited: true })));
    const seen = new Set<string>();
    return [...own, ...edits].filter(c => (seen.has(c.name) ? false : (seen.add(c.name), true)));
  }, [type, actions]);

  const toggle = (list: string[], set: (v: string[]) => void, name: string, max = Infinity) =>
    set(list.includes(name) ? list.filter(n => n !== name) : list.length < max ? [...list, name] : list);

  const place = () => {
    if (kind === "board" && process) {
      onPlace(s => placePiece(s, "ProcessBoard", { process, size: "full" }, section).spec,
        "a process board placed by hand", "Placed. It reads the process as the ontology declares it.");
    } else if (kind === "table" && entity) {
      const picked = [...chosenActions];
      onPlace(s => {
        const t = placePiece(s, "ObjectTable", { entity, segment, columns, size: "wide" }, section);
        if (!withDetail || !t.key) return t.spec;
        const d = placePiece(t.spec, "ObjectDetail", { follows: t.key, size: "small" }, section);
        return picked.reduce((acc, a) => addAction(acc, d.key as string, a), d.spec);
      }, "an objects table placed by hand", withDetail ? "Placed, with a detail beside it. Choose a row to open it." : "Placed.");
    } else if (kind === "detail" && table) {
      const picked = [...chosenActions];
      onPlace(s => {
        const d = placePiece(s, "ObjectDetail", { follows: table, size: "small" }, section);
        return picked.reduce((acc, a) => addAction(acc, d.key as string, a), d.spec);
      }, "an object detail placed by hand", "Placed. It shows the row chosen in its table.");
    } else if (kind === "action" && detail && action) {
      onPlace(s => addAction(s, detail, action), "an action button placed by hand", "Placed in the detail.");
    }
  };

  const ready = kind === "board" ? !!process : kind === "table" ? !!entity : kind === "detail" ? !!table : !!(detail && action);
  const actionChoices = kind === "table" ? actionsOn(actions, type?.id ?? entity)
    : kind === "detail" ? actionsOn(actions, entityOf(table))
      : actionsOn(actions, entityOf(String(spec.elements[detail]?.props.follows ?? "")));

  return (
    <div data-testid="cockpit-piece-composer" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }} role="radiogroup" aria-label="What to place">
        {withUniqueKeys(KINDS, x => x.kind).map(([key, k]) => (
          <Button key={key} size="xs" variant={kind === k.kind ? "secondary" : "ghost"} role="radio" aria-checked={kind === k.kind}
            aria-label={k.label} title={k.says} onClick={() => setKind(k.kind)}>{k.label}</Button>
        ))}
      </div>
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>{KINDS.find(k => k.kind === kind)?.says}. It reads what the ontology declares, by id; nothing here defines anything.</div>
      {problem && <div className="aug-fs-sm" data-testid="cockpit-piece-problem" style={{ color: "var(--red4)" }}>{problem}</div>}

      {kind === "board" && (
        <SelectField aria-label="Process" value={process} onChange={e => setProcess(e.target.value)}>
          <option value="">Choose a process…</option>
          {(processes?.processes ?? []).map(p => <option key={p.id} value={p.id}>{p.display_name || words(p.id)}</option>)}
        </SelectField>
      )}

      {kind === "table" && (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <SelectField aria-label="Entity" value={entity} onChange={e => setEntity(e.target.value)}>
              <option value="">Choose an entity…</option>
              {entities.map(e => <option key={e.id} value={e.id}>{e.label}</option>)}
            </SelectField>
            {type && (
              <SelectField aria-label="Segment" value={segment} onChange={e => setSegment(e.target.value)}>
                <option value="">Every {type.display_name || type.id}</option>
                {withUniqueKeys(segments, x => x.name).map(([key, s]) => <option key={key} value={s.name} title={s.says}>{words(s.name)}</option>)}
              </SelectField>
            )}
          </div>
          {type && (
            <div>
              <div className="aug-label" style={{ marginBottom: 4 }}>Columns beside the key · up to {MAX_TABLE_COLUMNS}; none picked lists its first ones</div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {withUniqueKeys(offered.slice(0, 24), x => x.name).map(([key, c]) => (
                  <label key={key} className="aug-fs-sm" style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--t2)" }}>
                    <Checkbox aria-label={c.label} checked={columns.includes(c.name)} onChange={() => toggle(columns, setColumns, c.name, MAX_TABLE_COLUMNS)} />
                    {c.label}{c.edited ? " (set by an action)" : ""}
                  </label>
                ))}
              </div>
            </div>
          )}
          <label className="aug-fs-sm" style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--t2)" }}>
            <Checkbox aria-label="And a detail beside it" checked={withDetail} onChange={e => setWithDetail(e.target.checked)} /> And a detail beside it, which follows the row chosen
          </label>
        </>
      )}

      {kind === "detail" && (
        <SelectField aria-label="Table it follows" value={table} onChange={e => setTable(e.target.value)}>
          <option value="">{tables.length ? "Choose the table it follows…" : "Place an objects table first"}</option>
          {tables.map(([k, el]) => <option key={k} value={k}>{words(String(el.props.entity))}{el.props.segment ? ` · ${words(String(el.props.segment))}` : ""}</option>)}
        </SelectField>
      )}

      {kind === "action" && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <SelectField aria-label="Detail" value={detail} onChange={e => { setDetail(e.target.value); setAction(""); }}>
            <option value="">{details.length ? "Choose a detail…" : "Place an object detail first"}</option>
            {details.map(([k, el]) => <option key={k} value={k}>Detail of {words(entityOf(String(el.props.follows)))}</option>)}
          </SelectField>
          {detail && (
            <SelectField aria-label="Action" value={action} onChange={e => setAction(e.target.value)}>
              <option value="">{actionChoices.length ? "Choose a declared action…" : "No declared action takes this entity"}</option>
              {actionChoices.map(a => <option key={a.id} value={a.id}>{a.display_name || words(a.id)}</option>)}
            </SelectField>
          )}
        </div>
      )}

      {(kind === "table" && withDetail) || kind === "detail" ? (
        actionChoices.length > 0 && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <span className="aug-label">Actions in the detail</span>
            {actionChoices.map(a => (
              <label key={a.id} className="aug-fs-sm" style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--t2)" }}>
                <Checkbox aria-label={a.display_name || words(a.id)} checked={chosenActions.includes(a.id)} onChange={() => toggle(chosenActions, setChosenActions, a.id)} />
                {a.display_name || words(a.id)}
              </label>
            ))}
          </div>
        )
      ) : null}

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {sections.length > 1 && kind !== "action" && (
          <SelectField aria-label="Section" value={section} onChange={e => setSection(e.target.value)}>
            {sections.map(s => <option key={s.key} value={s.key}>{s.tabLabel ? `${s.tabLabel} · ` : ""}{s.title}</option>)}
          </SelectField>
        )}
        <Button size="sm" disabled={busy || !ready} onClick={place}>Place</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>Cancel</Button>
      </div>
    </div>
  );
}
