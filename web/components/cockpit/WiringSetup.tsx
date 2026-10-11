"use client";

/**
 * WiringSetup — a cockpit's sets, values and choices in the builder (Arc AP-2; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md
 * §4.4; design-mockups/cockpit-builder.html screen 3).
 *
 * The Data tab lists what the cockpit's pieces read and what its readers make: each set with what it holds now and how
 * many pieces read it, each choice with the piece that makes it, each value. A set is built here — the entity or set it
 * starts from, the segment it keeps, its conditions, the chosen object it links to — and taken away only when nothing
 * reads it. Every field offers what the ontology declares; nothing is typed as a spec, and a model never wires a cockpit.
 */
import { useEffect, useState, type ReactNode } from "react";

import { entityFields, isNumber, isTime, type EntityField, type EntityFields } from "@/components/cockpit/PieceSetup";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { MAX_LABEL, MAX_SETS, MAX_VALUES, MAX_WHERE, SET_OPS, VALUE_KINDS, type CockpitSetDef, type CockpitValueDef, type SetOp } from "@/lib/cockpit/catalog";
import { dropWire, freshWireName, putSet, putValue, type CockpitSpec } from "@/lib/cockpit/edit";
import { lineOf, setTitles, wireWords } from "@/lib/cockpit/names";
import { choicesOf, doorConditions, isRefused, readSet, readersOf } from "@/lib/cockpit/sets";
import { formatCount } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { cachedObjectCatalog, queryObjects } from "@/lib/objects";

type Change = (next: CockpitSpec, note: string) => void;
const words = (s: string) => wireWords(s);

/** What an operator says, as a person reads it. */
const OP_WORDS: Record<SetOp, string> = {
  "=": "is", "!=": "is not", ">": "is over", ">=": "is at least", "<": "is under", "<=": "is at most", in: "is one of",
  not_in: "is none of", is_null: "is empty", not_null: "is not empty", in_last: "is in the last",
};

function Label({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "baseline", gap: 6, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em", padding: "12px 12px 6px" }}>
      {children}{right && <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>{right}</span>}
    </div>
  );
}

function Row({ label, hint, children, testid }: { label: string; hint?: ReactNode; children: ReactNode; testid?: string }) {
  return (
    <div data-testid={testid} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 14px" }}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>{label}</div>
      {children}
      {hint && <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.45 }}>{hint}</div>}
    </div>
  );
}

/** How many objects a set holds now, read through the object door — or the choice it waits on. */
function useSetCount(spec: CockpitSpec, name: string, connectionId: string, schema?: string): string {
  const r = readSet(spec, name);
  const read = isRefused(r) ? null : doorConditions(r, () => null);
  const body = !isRefused(r) && read && "filters" in read
    ? { object_type: r.entity, measures: [{ name: "n", agg: "count" }], ...(r.segment ? { segment: r.segment } : {}), ...(read.filters.length ? { filters: read.filters } : {}) }
    : null;
  const asked = JSON.stringify(body);
  const [said, setSaid] = useState<{ asked: string; text: string } | null>(null);
  useEffect(() => {
    if (!body) return;
    let alive = true;
    queryObjects(body, connectionId, schema)
      .then(out => { if (alive) setSaid({ asked, text: out.path === "refused" ? "cannot be read" : out.error ? "cannot be read" : formatCount(Number(out.rows?.[0]?.[0] ?? 0)) }); })
      .catch(() => { if (alive) setSaid({ asked, text: "cannot be read" }); });
    return () => { alive = false; };
  }, [asked, connectionId, schema]); // eslint-disable-line react-hooks/exhaustive-deps -- keyed on what it asks
  if (isRefused(r)) return "cannot be read";
  if (read && "waiting" in read) return `waits on the ${words(read.waiting)}`;
  return said && said.asked === asked ? said.text : "…";
}

function SetLine({ spec, name, selected, onSelect, connectionId, schema }: {
  spec: CockpitSpec; name: string; selected: boolean; onSelect: () => void; connectionId: string; schema?: string;
}) {
  const set = spec.sets?.[name];
  const count = useSetCount(spec, name, connectionId, schema);
  const readers = readersOf(spec, name);
  const from = set?.from ? spec.sets?.[set.from]?.label ?? words(set.from) : words(set?.entity ?? "");
  return (
    <Button variant="ghost" data-testid="data-set" data-name={name} aria-pressed={selected} onClick={onSelect} className="aug-fs-sm"
      style={{ ...ROW, background: selected ? "var(--accent-a3, var(--bg-3))" : "transparent" }}>
      <span aria-hidden="true" style={{ color: "var(--blue3)" }}>●</span>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{set?.label ?? name}</span>
        <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {from}{set?.segment ? ` · ${words(set.segment)}` : ""}{set?.where?.length ? ` · ${set.where.length} condition${set.where.length === 1 ? "" : "s"}` : ""}
        </span>
      </span>
      <span className="aug-fs-xs" style={{ textAlign: "right", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>
        {count}
        <span style={{ display: "block", color: "var(--t3)" }}>read by {readers.elements.length + readers.sets.length}</span>
      </span>
    </Button>
  );
}

/** A line of the Data tab: the app's own button, laid out as a row of three — its mark, its words, its count. */
const ROW = { display: "grid", gridTemplateColumns: "14px minmax(0, 1fr) auto", gap: 8, alignItems: "baseline", width: "100%", height: "auto",
  textAlign: "left", padding: "6px 10px", borderRadius: "var(--r2)", color: "var(--t1)", fontWeight: 400 } as const;

/** The Data tab: the sets, the choices and the values, and the doors to new ones. */
export function DataPane({ spec, selected, onSelect, onChange, connectionId, schema }: {
  spec: CockpitSpec;
  /** `set:<name>`, `value:<name>` or `choice:<name>` while one is chosen. */
  selected: string | null;
  onSelect: (key: string) => void;
  onChange: Change;
  connectionId: string;
  schema?: string;
}) {
  const sets = Object.keys(spec.sets ?? {});
  const values = Object.keys(spec.values ?? {});
  const choices = [...choicesOf(spec).values()];
  // a new set starts from the entity the cockpit already reads — a piece's own, else a set's, else the filter column's
  const firstEntity = [...Object.values(spec.elements).map(el => el.props?.entity), ...Object.values(spec.sets ?? {}).map(x => x.entity)]
    .find((e): e is string => typeof e === "string" && !!e) ?? "";
  const newSet = () => {
    const name = freshWireName(spec, "New set");
    onChange(putSet(spec, name, { label: "New set", entity: firstEntity || "entity" }), "a set added by hand");
    onSelect(`set:${name}`);
  };
  const newValue = () => {
    const name = freshWireName(spec, "Window");
    onChange(putValue(spec, name, { label: "Window", kind: "days", value: 14 }), "a value added by hand");
    onSelect(`value:${name}`);
  };
  return (
    <div data-testid="builder-data" style={{ padding: "0 6px 8px" }}>
      <Label right={`${sets.length} of ${MAX_SETS}`}>Sets</Label>
      {sets.map(n => (
        <SetLine key={n} spec={spec} name={n} selected={selected === `set:${n}`} onSelect={() => onSelect(`set:${n}`)} connectionId={connectionId} schema={schema} />
      ))}
      {!sets.length && <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "0 10px 6px" }}>None yet: every piece reads its own entity.</div>}
      {sets.length < MAX_SETS && (
        <Button size="xs" variant="ghost" data-testid="data-new-set" disabled={!firstEntity} onClick={newSet}><Icon name="plus" /> New set</Button>
      )}
      <Label>Chosen by the reader</Label>
      {withUniqueKeys(choices, c => c.name).map(([key, c]) => (
        <Button key={key} variant="ghost" data-testid="data-choice" aria-pressed={selected === `choice:${c.name}`} onClick={() => onSelect(`choice:${c.name}`)}
          className="aug-fs-sm" style={{ ...ROW, background: selected === `choice:${c.name}` ? "var(--accent-a3, var(--bg-3))" : "transparent" }}>
          <span aria-hidden="true" style={{ color: "var(--vio4)" }}>◆</span>
          <span style={{ minWidth: 0 }}>
            {words(c.name)}
            <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)" }}>
              {c.kind === "chosen" ? "a row clicked" : c.kind === "ticked" ? "rows ticked" : "a figure clicked"} in {c.madeBy.map(k => lineOf(spec.elements, k, undefined, undefined, setTitles(spec)).split(" · ").pop()).join(", ")}
            </span>
          </span>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>read by {readersOf(spec, c.name).elements.length + readersOf(spec, c.name).sets.length}</span>
        </Button>
      ))}
      {!choices.length && <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "0 10px 6px" }}>None: a table&rsquo;s setup names what a click chooses.</div>}
      <Label right={`${values.length} of ${MAX_VALUES}`}>Values</Label>
      {values.map(n => {
        const v = spec.values?.[n];
        return (
          <Button key={n} variant="ghost" data-testid="data-value" aria-pressed={selected === `value:${n}`} onClick={() => onSelect(`value:${n}`)}
            className="aug-fs-sm" style={{ ...ROW, background: selected === `value:${n}` ? "var(--accent-a3, var(--bg-3))" : "transparent" }}>
            <span aria-hidden="true" style={{ color: "var(--amb3)" }}>#</span>
            <span>{v?.label ?? n}</span>
            <span className="aug-fs-xs" style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{String(v?.value ?? "")}{v?.kind === "days" ? " days" : ""}</span>
          </Button>
        );
      })}
      {values.length < MAX_VALUES && <Button size="xs" variant="ghost" data-testid="data-new-value" onClick={newValue}><Icon name="plus" /> New value</Button>}
    </div>
  );
}

/** Who reads a set, a value or a choice — its pieces by name, the sets that start from it — and the door that takes it
 *  away, open only when nothing reads it. */
function ReadBy({ spec, name, onChange, onGone }: { spec: CockpitSpec; name: string; onChange?: Change; onGone?: () => void }) {
  const r = readersOf(spec, name);
  const none = !r.elements.length && !r.sets.length;
  return (
    <>
      <Row label="Read by" testid="setup-read-by">
        {none ? <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Nothing yet.</span> : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {r.elements.map(k => <li key={k} className="aug-fs-sm" style={{ color: "var(--t2)" }}>{lineOf(spec.elements, k, undefined, undefined, setTitles(spec))}</li>)}
            {r.sets.map(k => <li key={k} className="aug-fs-sm" style={{ color: "var(--t2)" }}>Set · {spec.sets?.[k]?.label ?? k}</li>)}
          </ul>
        )}
      </Row>
      {onChange && (
        <div style={{ padding: "6px 14px" }}>
          <Button size="xs" variant="ghost" disabled={!none} data-testid="setup-wire-delete" title={none ? "Take it away" : "Only what nothing reads can be taken away"}
            onClick={() => { onChange(dropWire(spec, name), "taken away by hand"); onGone?.(); }}><Icon name="trash" /> Take away</Button>
        </div>
      )}
    </>
  );
}

function useEntities(connectionId: string): { value: string; label: string }[] {
  const [list, setList] = useState<{ value: string; label: string }[]>([]);
  useEffect(() => {
    let alive = true;
    cachedObjectCatalog(connectionId).then(c => {
      if (alive && c) setList(c.object_types.map(t => ({ value: t.object_type, label: t.display_name || words(t.object_type) })));
    }).catch(() => { /* the entity a set names stays offered */ });
    return () => { alive = false; };
  }, [connectionId]);
  return list;
}

function useFields(entity: string, connectionId: string, schema?: string): EntityFields | null {
  const [got, setGot] = useState<{ entity: string; fields: EntityFields } | null>(null);
  useEffect(() => {
    if (!entity) return;
    let alive = true;
    entityFields(entity, connectionId, schema).then(f => { if (alive) setGot({ entity, fields: f }); }).catch(() => { /* none offered */ });
    return () => { alive = false; };
  }, [entity, connectionId, schema]);
  return got && got.entity === entity ? got.fields : null;
}

function Pick({ label, value, options, onPick, none }: { label: string; value: string; options: { value: string; label: string }[]; onPick: (v: string) => void; none?: string }) {
  return (
    <SelectField aria-label={label} value={value} onChange={e => onPick(e.target.value)}>
      {none !== undefined && <option value="">{none}</option>}
      {withUniqueKeys(options, o => o.value).map(([k, o]) => <option key={k} value={o.value}>{o.label}</option>)}
    </SelectField>
  );
}

/** A set's setup: what it is called, what it starts from, the segment and conditions it keeps, the chosen object it links
 *  to, what it holds now and what reads it. */
export function SetSetup({ spec, name, onChange, onGone, connectionId, schema }: {
  spec: CockpitSpec; name: string; onChange: Change; onGone: () => void; connectionId: string; schema?: string;
}) {
  const set = spec.sets?.[name];
  const entities = useEntities(connectionId);
  const r = readSet(spec, name);
  const entity = isRefused(r) ? set?.entity ?? "" : r.entity;
  const fields = useFields(entity, connectionId, schema);
  const count = useSetCount(spec, name, connectionId, schema);
  const [label, setLabel] = useState(set?.label ?? "");
  const [shownLabel, setShownLabel] = useState(set?.label ?? "");
  if (shownLabel !== (set?.label ?? "")) { setShownLabel(set?.label ?? ""); setLabel(set?.label ?? ""); }
  const others = Object.keys(spec.sets ?? {}).filter(n => n !== name);
  const chosen = [...choicesOf(spec).values()].filter(c => c.kind === "chosen");
  const props = fields?.fields ?? [];
  if (!set) return null;
  const put = (def: CockpitSetDef, note: string) => onChange(putSet(spec, name, def), note);
  const where = set.where ?? [];
  const startsFrom = set.from ? `set:${set.from}` : `entity:${set.entity ?? ""}`;
  return (
    <div data-testid="set-setup" data-name={name}>
      <div style={{ padding: "12px 14px 8px", borderBottom: "1px solid var(--b1)" }}>
        <div className="aug-fs-xs" style={{ color: "var(--accent-11)", textTransform: "uppercase", letterSpacing: ".06em" }}>Set</div>
        <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600, marginTop: 2 }}>{set.label}</div>
      </div>
      <Row label="Name">
        <Input aria-label="The set's name" value={label} maxLength={MAX_LABEL} onChange={e => setLabel(e.target.value)}
          onBlur={() => { const t = label.trim(); if (t && t !== set.label) put({ ...set, label: t }, "a set renamed by hand"); else setLabel(set.label); }}
          onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      </Row>
      <Row label="Starts from" hint="An entity's every object, or another set — what this one narrows further.">
        <Pick label="Starts from" value={startsFrom}
          options={[...entities.map(e => ({ value: `entity:${e.value}`, label: e.label })), ...others.map(n => ({ value: `set:${n}`, label: `The set ${spec.sets?.[n]?.label ?? n}` })),
            ...(set.entity && !entities.some(e => e.value === set.entity) ? [{ value: `entity:${set.entity}`, label: words(set.entity) }] : [])]}
          onPick={v => {
            const [kind, id] = [v.slice(0, v.indexOf(":")), v.slice(v.indexOf(":") + 1)];
            const { entity: _e, from: _f, ...rest } = set;
            void _e; void _f;
            put(kind === "set" ? { ...rest, from: id } : { ...rest, entity: id }, "a set's start chosen by hand");
          }} />
      </Row>
      <Row label="Keeps only" hint="A segment the ontology derives — overdue on dispatch, returned — or every object.">
        <Pick label="Segment" value={set.segment ?? ""} none="Every object"
          options={[...new Set([...(fields?.segments ?? []), ...(set.segment ? [set.segment] : [])])].map(s => ({ value: s, label: words(s) }))}
          onPick={v => put({ ...set, segment: v || null }, "a set's segment chosen by hand")} />
      </Row>
      <Row label="And where" testid="set-where" hint={where.length >= MAX_WHERE ? `At most ${MAX_WHERE} conditions of its own.` : "A property, and what it must be. A number of days counts back from today."}>
        {where.map((c, i) => (
          <Condition key={`${c.path}-${i}`} spec={spec} c={c} fields={props}
            onChange={next => put({ ...set, where: where.map((x, j) => (j === i ? next : x)) }, "a set's condition changed by hand")}
            onDrop={() => put({ ...set, where: where.filter((_, j) => j !== i) }, "a set's condition taken off by hand")} />
        ))}
        {where.length < MAX_WHERE && props.length > 0 && (
          <Pick label="Add a condition" value="" none="+ A condition on a property" options={props.map(f => ({ value: f.path, label: f.via ? `${f.label} via ${f.via}` : f.label }))}
            onPick={v => { const f = props.find(x => x.path === v); if (f) put({ ...set, where: [...where, isTime(f) ? { path: v, op: "in_last", value: 14 } : { path: v, op: "not_null" }] }, "a set's condition added by hand"); }} />
        )}
      </Row>
      <Row label="Linked to" hint="Only the objects whose property is the key of the object a reader chose — an order's lines, say.">
        <Pick label="Linked to" value={set.linked_to?.choice ?? ""} none="No chosen object" options={chosen.map(c => ({ value: c.name, label: words(c.name) }))}
          onPick={v => put({ ...set, linked_to: v ? { choice: v, path: set.linked_to?.path ?? props.find(f => /_id$/.test(f.path))?.path ?? props[0]?.path ?? "id" } : null }, "a set's link chosen by hand")} />
        {set.linked_to && (
          <Pick label="Through" value={set.linked_to.path} options={props.map(f => ({ value: f.path, label: `whose ${f.via ? `${f.label} via ${f.via}` : f.label}` }))}
            onPick={v => put({ ...set, linked_to: { choice: set.linked_to!.choice, path: v } }, "a set's link chosen by hand")} />
        )}
      </Row>
      <Row label="Holds now" hint="Read through the object door; each reader's row policies and masks hold on it.">
        <span className="aug-fs-sm" data-testid="set-holds" style={{ color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
          {isRefused(r) ? r.refused : count}
        </span>
      </Row>
      <ReadBy spec={spec} name={name} onChange={onChange} onGone={onGone} />
    </div>
  );
}

function Condition({ spec, c, fields, onChange, onDrop }: {
  spec: CockpitSpec; c: NonNullable<CockpitSetDef["where"]>[number]; fields: EntityField[];
  onChange: (next: NonNullable<CockpitSetDef["where"]>[number]) => void; onDrop: () => void;
}) {
  const f = fields.find(x => x.path === c.path);
  const time = !!f && isTime(f);
  const number = !!f && isNumber(f);
  const ops = SET_OPS.filter(o => (o === "in_last" ? time : true));
  const days = Object.entries(spec.values ?? {}).filter(([, v]) => v.kind === "days");
  // an operator chosen that needs something to compare with waits here until it is given one: a comparison with nothing
  // is refused by the rules, so changing "is not empty" to "is over" kept nothing (scenario on theLook, 2026-10-11)
  const [draft, setDraft] = useState<SetOp | null>(null);
  const op = draft ?? c.op;
  const [text, setText] = useState(String(c.value ?? (c.values ?? []).join(", ")));
  // a number typed for a numeric property is kept as a number: "1" compared with a count is a word, not a count
  const typed = (x: string): string | number => (number && x.trim() !== "" && !Number.isNaN(Number(x)) ? Number(x) : x.trim());
  const keep = (next: NonNullable<CockpitSetDef["where"]>[number]) => { setDraft(null); onChange(next); };
  const commit = () => {
    if (op === "in" || op === "not_in") {
      const values = text.split(",").map(x => x.trim()).filter(Boolean).map(typed);
      if (values.length) keep({ path: c.path, op, values });
    } else if (op === "in_last") {
      const n = Number(text);
      if (Number.isInteger(n) && n >= 1) keep({ path: c.path, op, value: n });
    } else if (text.trim() !== "") {
      keep({ path: c.path, op, value: typed(text) });
    }
  };
  const pickOp = (v: string) => {
    const next = v as SetOp;
    if (next === "is_null" || next === "not_null") { keep({ path: c.path, op: next }); return; }
    if (next === "in_last") { setText("14"); keep({ path: c.path, op: next, value: 14 }); return; }
    // a comparison keeps the value it had, when it had one that is not a number of days; else it waits for one
    const had = c.op !== "in_last" && c.value != null && c.value !== "" ? c.value : null;
    if (next === "in" || next === "not_in") {
      const list = c.values?.length ? c.values : had != null && typeof had !== "boolean" ? [had] : [];
      if (list.length) keep({ path: c.path, op: next, values: list }); else { setDraft(next); setText(""); }
    } else if (had != null) {
      keep({ path: c.path, op: next, value: had });
    } else {
      setDraft(next); setText("");
    }
  };
  return (
    <div data-testid="set-condition" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 4, padding: "4px 0", borderBottom: "1px solid var(--b1)" }}>
      <span className="aug-fs-sm" style={{ color: "var(--t1)", alignSelf: "center" }}>{f ? (f.via ? `${f.label} via ${f.via}` : f.label) : words(c.path)}</span>
      <Button size="xs" variant="ghost" aria-label={`Take the condition on ${words(c.path)} off`} onClick={onDrop}><Icon name="close" size={12} /></Button>
      <Pick label="Is" value={op} options={ops.map(o => ({ value: o, label: OP_WORDS[o] }))} onPick={pickOp} />
      <span />
      {op === "in_last" && days.length > 0 && (
        <Pick label="Days from" value={c.value_from ?? ""} none="A number of days" options={days.map(([n, v]) => ({ value: n, label: `${v.label} · ${String(v.value)} days` }))}
          onPick={v => keep({ ...c, value_from: v || null, value: v ? null : 14 })} />
      )}
      {!["is_null", "not_null"].includes(op) && !(op === c.op && c.value_from) && (
        <Input aria-label={`What ${words(c.path)} ${OP_WORDS[op]}`} value={text} onChange={e => setText(e.target.value)} onBlur={commit}
          autoFocus={draft !== null} inputMode={number || op === "in_last" ? "decimal" : undefined}
          onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setDraft(null); setText(String(c.value ?? (c.values ?? []).join(", "))); } }}
          placeholder={op === "in_last" ? "days" : op === "in" || op === "not_in" ? "values, comma between" : "value"} />
      )}
      {draft !== null && (
        <span className="aug-fs-xs" data-testid="set-condition-waits" style={{ gridColumn: "1 / -1", color: "var(--t3)" }}>
          Give it what it {OP_WORDS[draft]} to keep it — Escape leaves it as it was.
        </span>
      )}
    </div>
  );
}

/** A value's setup: its name, its kind and the value sets read. */
export function ValueSetup({ spec, name, onChange, onGone }: { spec: CockpitSpec; name: string; onChange: Change; onGone: () => void }) {
  const v = spec.values?.[name];
  const [text, setText] = useState(String(v?.value ?? ""));
  const [shown, setShown] = useState(String(v?.value ?? ""));
  if (shown !== String(v?.value ?? "")) { setShown(String(v?.value ?? "")); setText(String(v?.value ?? "")); }
  if (!v) return null;
  const put = (def: CockpitValueDef, note: string) => onChange(putValue(spec, name, def), note);
  return (
    <div data-testid="value-setup" data-name={name}>
      <div style={{ padding: "12px 14px 8px", borderBottom: "1px solid var(--b1)" }}>
        <div className="aug-fs-xs" style={{ color: "var(--accent-11)", textTransform: "uppercase", letterSpacing: ".06em" }}>Value</div>
        <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600, marginTop: 2 }}>{v.label}</div>
      </div>
      <Row label="Is">
        <Pick label="Kind" value={v.kind} options={VALUE_KINDS.map(k => ({ value: k, label: k === "days" ? "A number of days" : k === "number" ? "A number" : "A word" }))}
          onPick={k => put({ ...v, kind: k as CockpitValueDef["kind"], value: k === "text" ? String(v.value) : Number(v.value) || 1 }, "a value's kind chosen by hand")} />
        <Input aria-label="The value" value={text} type={v.kind === "text" ? "text" : "number"} onChange={e => setText(e.target.value)}
          onBlur={() => {
            const next = v.kind === "text" ? text.trim() : Number(text);
            if ((v.kind === "text" ? !!next : Number.isFinite(next) && (v.kind !== "days" || (Number.isInteger(next) && (next as number) >= 1))) && next !== v.value) put({ ...v, value: next }, "a value changed by hand");
            else setText(String(v.value));
          }} />
      </Row>
      <ReadBy spec={spec} name={name} onChange={onChange} onGone={onGone} />
    </div>
  );
}

/** A choice's setup: what makes it and what reads it. A choice is a piece's to make — named in that piece's setup. */
export function ChoiceSetup({ spec, name }: { spec: CockpitSpec; name: string }) {
  const c = choicesOf(spec).get(name);
  if (!c) return null;
  return (
    <div data-testid="choice-setup" data-name={name}>
      <div style={{ padding: "12px 14px 8px", borderBottom: "1px solid var(--b1)" }}>
        <div className="aug-fs-xs" style={{ color: "var(--accent-11)", textTransform: "uppercase", letterSpacing: ".06em" }}>Chosen by the reader</div>
        <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600, marginTop: 2 }}>{words(name)}</div>
      </div>
      <Row label="Made by" hint="Each reader's own, in their browser, for as long as the cockpit is open — never the kept cockpit.">
        <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
          {c.kind === "chosen" ? "A row clicked" : c.kind === "ticked" ? "Rows ticked" : "A figure clicked"} in {c.madeBy.map(k => lineOf(spec.elements, k, undefined, undefined, setTitles(spec))).join(", ")}
        </span>
      </Row>
      <ReadBy spec={spec} name={name} />
    </div>
  );
}
