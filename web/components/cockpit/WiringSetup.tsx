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
import { Segmented } from "@/components/ui/segmented";
import { SelectField } from "@/components/ui/select";
import {
  MAX_LABEL, MAX_SETS, MAX_VALUE_OPTIONS, MAX_VALUES, MAX_WHERE, SET_COMBINES, SET_OPS, VALUE_KINDS, VALUE_OPS, type CockpitSetDef, type CockpitValueDef,
  type SetCombine, type SetOp,
} from "@/lib/cockpit/catalog";
import { dropWire, freshWireName, putSet, putValue, renameValue, type CockpitSpec } from "@/lib/cockpit/edit";
import { lineOf, setTitles, wireWords } from "@/lib/cockpit/names";
import { choicesOf, doorConditions, isRefused, readSet, readersOf } from "@/lib/cockpit/sets";
import { typedValue, valueFits, valueWords } from "@/lib/cockpit/values";
import { formatCount, formatSeconds } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { cachedObjectCatalog, queryObjects } from "@/lib/objects";

type Change = (next: CockpitSpec, note: string) => void;
const words = (s: string) => wireWords(s);

/** Arc AP-8b — how a set is combined with another, as a person reads it (the mockup's words, screen 12): in the setup,
 *  and on the set's line beside the set it is combined with. */
const COMBINE_WORDS: Record<SetCombine, string> = { either: "Either", both: "Both", but_not: "But not" };
const COMBINE_LINE: Record<SetCombine, (other: string) => string> = {
  either: o => `either this or ${o}`, both: o => `both this and ${o}`, but_not: o => `but not ${o}` };

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

/** A read and how long it took, in milliseconds. */
async function timed<T>(read: () => Promise<T>): Promise<{ out: T; ms: number }> {
  const started = performance.now();
  const out = await read();
  return { out, ms: performance.now() - started };
}

/** How many objects a set holds now, read through the object door — or the choice it waits on — and how long the door
 *  took to count them (Arc AP-6: each set says its read time). */
function useSetCount(spec: CockpitSpec, name: string, connectionId: string, schema?: string, sum?: string): { text: string; ms: number | null } {
  // Arc AP-8 — in the builder a value is what it starts from; one counted, or read off a chosen object, waits on the page
  const r = readSet(spec, name, v => {
    const def = spec.values?.[v];
    const by = def?.from?.by ?? "author";
    return by === "author" || by === "reader" ? { value: def?.value ?? null } : by === "chosen" && def?.from?.by === "chosen"
      ? { waiting: def.from.choice } : { reading: true };
  });
  const read = isRefused(r) ? null : doorConditions(r, () => null);
  const body = !isRefused(r) && read && "filters" in read
    ? { object_type: r.entity, measures: [sum ? { name: "n", agg: "sum", path: sum } : { name: "n", agg: "count" }],
      ...(r.segment ? { segment: r.segment } : {}), ...(read.filters.length ? { filters: read.filters } : {}) }
    : null;
  const asked = JSON.stringify(body);
  const [said, setSaid] = useState<{ asked: string; text: string; ms: number | null } | null>(null);
  useEffect(() => {
    if (!body) return;
    let alive = true;
    timed(() => queryObjects(body, connectionId, schema))
      .then(({ out, ms }) => {
        if (!alive) return;
        const read = out.path !== "refused" && !out.error;
        const raw = out.path === "refused" ? null : out.rows?.[0]?.[0];
        // a sum over no objects is none, said — never a zero it did not add up
        const text = !read ? "cannot be read" : sum && (raw === null || raw === undefined) ? "nothing to add up"
          : formatCount(Number(raw ?? 0));
        setSaid({ asked, text, ms: read ? ms : null });
      })
      .catch(() => { if (alive) setSaid({ asked, text: "cannot be read", ms: null }); });
    return () => { alive = false; };
  }, [asked, connectionId, schema]); // eslint-disable-line react-hooks/exhaustive-deps -- keyed on what it asks
  if (isRefused(r)) return { text: "cannot be read", ms: null };
  if (read && "reading" in read) return { text: "counted on the page", ms: null };
  if (read && "waiting" in read) return { text: `waits on the ${words(read.waiting)}`, ms: null };
  return said && said.asked === asked ? { text: said.text, ms: said.ms } : { text: "…", ms: null };
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
          {set?.traverse ? ` → ${words(set.traverse.entity)}` : ""}
          {set?.combine ? ` · ${COMBINE_LINE[set.combine.op](spec.sets?.[set.combine.set]?.label ?? words(set.combine.set))}` : ""}
        </span>
      </span>
      <span className="aug-fs-xs" style={{ textAlign: "right", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>
        {count.text}
        {count.ms !== null && <span data-testid="data-set-read-time" style={{ color: "var(--t3)" }}> · {formatSeconds(count.ms)}</span>}
        <span style={{ display: "block", color: "var(--t3)" }}>read by {readers.elements.length + readers.sets.length}</span>
      </span>
    </Button>
  );
}

/** A line of the Data tab: the app's own button, laid out as a row of three — its mark, its words, its count. */
const ROW = { display: "grid", gridTemplateColumns: "14px minmax(0, 1fr) auto", gap: 8, alignItems: "baseline", width: "100%", height: "auto",
  textAlign: "left", padding: "6px 10px", borderRadius: "var(--r2)", color: "var(--t1)", fontWeight: 400 } as const;

/** Arc AP-8 — the cards of a person's own query a spec places, by element key, that read `name` (`{{name}}`). */
function cardsReading(spec: CockpitSpec, name: string, cardReads?: (cardId: string) => string[]): string[] {
  if (!cardReads) return [];
  return Object.entries(spec.elements).filter(([, el]) => el?.type === "Card" && cardReads(String(el.props?.card ?? "")).includes(name)).map(([k]) => k);
}

/** The element keys that read `name`, a query of the person's own among them (Arc AP-8) — dashed on the canvas. */
export function readingElements(spec: CockpitSpec, name: string, cardReads?: (cardId: string) => string[]): string[] {
  return [...readersOf(spec, name).elements, ...cardsReading(spec, name, cardReads)];
}

/** Everything that reads `name`: the pieces, the sets, the values and (Arc AP-8) the queries of the person's own. */
function readersAll(spec: CockpitSpec, name: string, cardReads?: (cardId: string) => string[]) {
  const r = readersOf(spec, name);
  const cards = cardsReading(spec, name, cardReads);
  return { ...r, cards, count: r.elements.length + r.sets.length + r.values.length + cards.length };
}

/** Where a value comes from, and what it is, in a line: "days · set by you". */
export function valueLine(spec: CockpitSpec, v: CockpitValueDef): string {
  const kind = KIND_SAID[v.kind] ?? v.kind;
  const from = v.from;
  if (!from || from.by === "author") return `${kind} · set by you`;
  if (from.by === "reader") return `${kind} · set by the reader`;
  if (from.by === "count") return `${kind} · counted from ${spec.sets?.[from.set]?.label ?? words(from.set)}`;
  if (from.by === "sum") return `${kind} · ${words(from.path).toLowerCase()} summed over ${spec.sets?.[from.set]?.label ?? words(from.set)}`;
  if (from.by === "query") return `${kind} · read from a query`;
  return `${kind} · read from the ${words(from.choice)}`;
}
const KIND_SAID: Record<string, string> = { days: "days", number: "a number", text: "words", date: "a day", yesno: "yes or no", list: "a list" };
const KIND_MARK: Record<string, string> = { days: "#", number: "#", text: "Aa", date: "◷", yesno: "✓", list: "≡" };

/** What a value holds now, in the builder: what it starts from; a count, read; a chosen object's, once one is chosen. */
function ValueNowText({ spec, v, connectionId, schema }: { spec: CockpitSpec; v: CockpitValueDef; connectionId: string; schema?: string }) {
  const from = v.from;
  if (from?.by === "count") return <CountOf spec={spec} set={from.set} connectionId={connectionId} schema={schema} />;
  if (from?.by === "sum") return <CountOf spec={spec} set={from.set} sum={from.path} connectionId={connectionId} schema={schema} />;
  if (from?.by === "chosen") return <>once one is chosen</>;
  if (from?.by === "query") return <>read on the page</>;
  return <>{valueWords(v.kind, v.value)}{v.kind === "days" ? " days" : ""}</>;
}
function CountOf({ spec, set, sum, connectionId, schema }: { spec: CockpitSpec; set: string; sum?: string; connectionId: string; schema?: string }) {
  return <>{useSetCount(spec, set, connectionId, schema, sum).text}</>;
}

/** The Data tab: the sets, the choices and the values, and the doors to new ones. Arc AP-8 — while variables are on,
 *  the Variables pane: the values first, each with where it comes from, what it holds now and how many read it; then
 *  the sets; then what the pieces output — a row chosen, rows ticked, a figure clicked. */
export function DataPane({ spec, selected, onSelect, onChange, connectionId, schema, variablesOn = false, cardReads }: {
  spec: CockpitSpec;
  /** `set:<name>`, `value:<name>` or `choice:<name>` while one is chosen. */
  selected: string | null;
  onSelect: (key: string) => void;
  onChange: Change;
  connectionId: string;
  schema?: string;
  variablesOn?: boolean;
  /** The values a card of the person's own query reads, by the card's id. */
  cardReads?: (cardId: string) => string[];
}) {
  const sets = Object.keys(spec.sets ?? {});
  const values = Object.keys(spec.values ?? {});
  const choices = [...choicesOf(spec).values()];
  const entities = useEntities(connectionId);
  // a new set starts from the entity the cockpit already reads — a piece's own, else a set's, else the filter column's;
  // on a cockpit that reads none yet — its cards all queries — from the connection's first entity (Arc AP-8)
  const firstEntity = [...Object.values(spec.elements).map(el => el.props?.entity), ...Object.values(spec.sets ?? {}).map(x => x.entity)]
    .find((e): e is string => typeof e === "string" && !!e) ?? entities[0]?.value ?? "";
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
  const choiceRows = withUniqueKeys(choices, c => c.name).map(([key, c]) => (
    <Button key={key} variant="ghost" data-testid="data-choice" aria-pressed={selected === `choice:${c.name}`} onClick={() => onSelect(`choice:${c.name}`)}
      className="aug-fs-sm" style={{ ...ROW, background: selected === `choice:${c.name}` ? "var(--accent-a3, var(--bg-3))" : "transparent" }}>
      <span aria-hidden="true" style={{ color: "var(--vio4)" }}>◆</span>
      <span style={{ minWidth: 0 }}>
        {words(c.name)}
        <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)" }}>
          {c.kind === "chosen" ? "a row clicked" : c.kind === "ticked" ? "rows ticked" : "a figure clicked"} in {c.madeBy.map(k => lineOf(spec.elements, k, undefined, undefined, setTitles(spec)).split(" · ").pop()).join(", ")}
        </span>
      </span>
      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        {variablesOn ? `used in ${readersAll(spec, c.name, cardReads).count}` : `read by ${readersOf(spec, c.name).elements.length + readersOf(spec, c.name).sets.length}`}
      </span>
    </Button>
  ));
  if (variablesOn) {
    return (
      <div data-testid="builder-data" data-variables="on" style={{ padding: "0 6px 8px" }}>
        <Label right={`${values.length} of ${MAX_VALUES}`}>Values</Label>
        {values.map(n => {
          const v = spec.values?.[n];
          if (!v) return null;
          const used = readersAll(spec, n, cardReads).count;
          return (
            <Button key={n} variant="ghost" data-testid="data-value" data-name={n} aria-pressed={selected === `value:${n}`} onClick={() => onSelect(`value:${n}`)}
              className="aug-fs-sm" style={{ ...ROW, background: selected === `value:${n}` ? "var(--accent-a3, var(--bg-3))" : "transparent" }}>
              <span aria-hidden="true" className="aug-fs-xs" style={{ color: "var(--amb3)" }}>{KIND_MARK[v.kind] ?? "#"}</span>
              <span style={{ minWidth: 0 }}>
                <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v.label}</span>
                <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{valueLine(spec, v)}</span>
              </span>
              <span className="aug-fs-xs" style={{ textAlign: "right", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>
                <ValueNowText spec={spec} v={v} connectionId={connectionId} schema={schema} />
                <span style={{ display: "block", color: "var(--t3)" }}>{used ? `used in ${used}` : "not used yet"}</span>
              </span>
            </Button>
          );
        })}
        {values.length < MAX_VALUES && <Button size="xs" variant="ghost" data-testid="data-new-value" onClick={newValue}><Icon name="plus" /> New value</Button>}
        <Label right={`${sets.length} of ${MAX_SETS}`}>Sets</Label>
        {sets.map(n => (
          <SetLine key={n} spec={spec} name={n} selected={selected === `set:${n}`} onSelect={() => onSelect(`set:${n}`)} connectionId={connectionId} schema={schema} />
        ))}
        {!sets.length && <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "0 10px 6px" }}>None yet: every piece reads its own entity.</div>}
        {sets.length < MAX_SETS && (
          <Button size="xs" variant="ghost" data-testid="data-new-set" disabled={!firstEntity} onClick={newSet}><Icon name="plus" /> New set</Button>
        )}
        <Label>From the pieces</Label>
        {choiceRows}
        {!choices.length && <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "0 10px 6px" }}>None: a table&rsquo;s setup names what a click chooses.</div>}
      </div>
    );
  }
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
      {choiceRows}
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
function ReadBy({ spec, name, onChange, onGone, cardReads, cardTitle }: {
  spec: CockpitSpec; name: string; onChange?: Change; onGone?: () => void;
  /** Arc AP-8 — the values a card of the person's own query reads, and its title: a query reads a value as a piece does. */
  cardReads?: (cardId: string) => string[]; cardTitle?: (cardId: string) => string | undefined;
}) {
  const r = readersAll(spec, name, cardReads);
  const none = r.count === 0;
  return (
    <>
      <Row label="Read by" testid="setup-read-by">
        {none ? <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Nothing yet.</span> : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {r.elements.map(k => <li key={k} className="aug-fs-sm" style={{ color: "var(--t2)" }}>{lineOf(spec.elements, k, undefined, undefined, setTitles(spec))}</li>)}
            {r.sets.map(k => <li key={k} className="aug-fs-sm" style={{ color: "var(--t2)" }}>Set · {spec.sets?.[k]?.label ?? k}</li>)}
            {r.values.map(k => <li key={k} className="aug-fs-sm" style={{ color: "var(--t2)" }}>Value · {spec.values?.[k]?.label ?? k}</li>)}
            {r.cards.map(k => {
              const id = String(spec.elements[k]?.props?.card ?? "");
              return <li key={k} className="aug-fs-sm" style={{ color: "var(--t2)" }}>Your query · {cardTitle?.(id) ?? id}</li>;
            })}
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

/** Arc AP-8c — the column a value reads off a query's first row: none, its first. */
function QueryColumn({ column, onSet }: { column: string; onSet: (column: string) => void }) {
  const [text, setText] = useState(column);
  const [shown, setShown] = useState(column);
  if (shown !== column) { setShown(column); setText(column); }
  return (
    <Input aria-label="The column it reads" value={text} placeholder="Its first column" maxLength={128}
      onChange={e => setText(e.target.value)} onBlur={() => { if (text.trim() !== column) onSet(text.trim()); }}
      onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
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
export function SetSetup({ spec, name, onChange, onGone, connectionId, schema, variablesOn = false }: {
  spec: CockpitSpec; name: string; onChange: Change; onGone: () => void; connectionId: string; schema?: string;
  /** Arc AP-8 — a condition may compare with any value of the cockpit's, as its kind allows. */
  variablesOn?: boolean;
}) {
  const set = spec.sets?.[name];
  const entities = useEntities(connectionId);
  const r = readSet(spec, name);
  // Arc AP-8b — its conditions read its objects before they reach others: the entity it starts from, its own
  const own = set && (set.traverse || set.combine) ? readSet({ ...spec, sets: { ...spec.sets, [name]: { ...set, traverse: null, combine: null } } }, name) : r;
  const entity = isRefused(own) ? set?.entity ?? "" : own.entity;
  const fields = useFields(entity, connectionId, schema);
  const reached = isRefused(r) ? "" : r.entity;
  const count = useSetCount(spec, name, connectionId, schema);
  const [label, setLabel] = useState(set?.label ?? "");
  const [shownLabel, setShownLabel] = useState(set?.label ?? "");
  if (shownLabel !== (set?.label ?? "")) { setShownLabel(set?.label ?? ""); setLabel(set?.label ?? ""); }
  const others = Object.keys(spec.sets ?? {}).filter(n => n !== name);
  // Arc AP-8b — the other sets it may be combined with: the ones it reads well with — of the objects it holds, and none
  // that reads it back
  const combinable = others.filter(n => !isRefused(readSet(spec, n))
    && !isRefused(readSet({ ...spec, sets: { ...spec.sets, [name]: { ...set!, combine: { op: "both", set: n } } } }, name)));
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
          <Condition key={`${c.path}-${i}`} spec={spec} c={c} fields={props} variablesOn={variablesOn}
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
      {variablesOn && (
        <Row label="Gets its linked objects" testid="set-traverse"
          hint="The objects its objects link to — the customers of the waiting orders. The set then holds those, each once.">
          <Pick label="Gets its linked objects" value={set.traverse?.link ?? ""} none={`No — its own ${words(entity).toLowerCase()} objects`}
            options={[...(fields?.reaches ?? []).map(l => ({ value: l.name, label: `${l.toName} · through ${words(l.name)}` })),
              ...(set.traverse && !(fields?.reaches ?? []).some(l => l.name === set.traverse!.link) ? [{ value: set.traverse.link, label: words(set.traverse.link) }] : [])]}
            onPick={v => {
              const l = (fields?.reaches ?? []).find(x => x.name === v);
              put({ ...set, traverse: v && l ? { link: v, entity: l.to } : null, combine: null }, v ? "a set's linked objects chosen by hand" : "a set's linked objects let go by hand");
            }} />
        </Row>
      )}
      {variablesOn && (
        <Row label="Combined with" testid="set-combine"
          hint="Another set of the same objects: either one, both, or this one but not that one.">
          <Pick label="How it is combined" value={set.combine?.op ?? ""} none="Not combined"
            options={SET_COMBINES.map(o => ({ value: o, label: COMBINE_WORDS[o] }))}
            onPick={v => {
              if (!v) { put({ ...set, combine: null }, "a set's combination let go by hand"); return; }
              const with_ = set.combine?.set ?? combinable[0];
              if (with_) put({ ...set, combine: { op: v as SetCombine, set: with_ } }, "a set combined by hand");
            }} />
          {set.combine && (
            <Pick label="The set it is combined with" value={set.combine.set}
              options={[...combinable, ...(combinable.includes(set.combine.set) ? [] : [set.combine.set])].map(n => ({ value: n, label: `The set ${spec.sets?.[n]?.label ?? n}` }))}
              onPick={v => put({ ...set, combine: { op: set.combine!.op, set: v } }, "a set combined by hand")} />
          )}
          {!set.combine && !combinable.length && (
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>No other set holds {words(reached || entity).toLowerCase()} objects yet.</span>
          )}
        </Row>
      )}
      <Row label="Holds now" hint="Read through the object door; each reader's row policies and masks hold on it.">
        <span className="aug-fs-sm" data-testid="set-holds" style={{ color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
          {isRefused(r) ? r.refused : count.text}
          {!isRefused(r) && count.ms !== null && (
            <span className="aug-fs-xs" data-testid="set-read-time" style={{ color: "var(--t3)" }}> · counted in {formatSeconds(count.ms)}</span>
          )}
        </span>
      </Row>
      <ReadBy spec={spec} name={name} onChange={onChange} onGone={onGone} />
    </div>
  );
}

function Condition({ spec, c, fields, onChange, onDrop, variablesOn = false }: {
  spec: CockpitSpec; c: NonNullable<CockpitSetDef["where"]>[number]; fields: EntityField[];
  onChange: (next: NonNullable<CockpitSetDef["where"]>[number]) => void; onDrop: () => void; variablesOn?: boolean;
}) {
  const f = fields.find(x => x.path === c.path);
  const time = !!f && isTime(f);
  const number = !!f && isNumber(f);
  const ops = SET_OPS.filter(o => (o === "in_last" ? time : true));
  const days = Object.entries(spec.values ?? {}).filter(([, v]) => v.kind === "days");
  const yesno = !!f && /BOOL/i.test(f.type);
  // Arc AP-8 — the values this condition may compare with, as their kinds allow: days counted back by "in the last";
  // a day for a moment, a number for a number, words for anything else — words only by "is" and "is not". Arc AP-8c — a
  // list by "is one of" and "is none of", and yes or no for a property that is yes or no, by "is" and "is not"
  const comparable = (o: SetOp) => Object.entries(spec.values ?? {}).filter(([, v]) => {
    if (o === "in_last") return v.kind === "days";
    if (!(VALUE_OPS as readonly string[]).includes(o)) return false;
    if (o === "in" || o === "not_in") return v.kind === "list";
    if (v.kind === "list") return false;
    if (v.kind === "yesno") return yesno && (o === "=" || o === "!=");
    return time ? v.kind === "date" : number ? v.kind === "number" : v.kind === "text" && (o === "=" || o === "!=");
  });
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
    // a variable it compares with that the new comparison also takes is kept (Arc AP-8)
    if (variablesOn && c.value_from && comparable(next).some(([n]) => n === c.value_from)) { keep({ path: c.path, op: next, value_from: c.value_from }); return; }
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
      {!variablesOn && op === "in_last" && days.length > 0 && (
        <Pick label="Days from" value={c.value_from ?? ""} none="A number of days" options={days.map(([n, v]) => ({ value: n, label: `${v.label} · ${String(v.value)} days` }))}
          onPick={v => keep({ ...c, value_from: v || null, value: v ? null : 14 })} />
      )}
      {variablesOn && comparable(op).length > 0 && (
        <Pick label="Compared with" value={op === c.op ? c.value_from ?? "" : ""} none={op === "in_last" ? "A number of days typed here" : "A value typed here"}
          options={comparable(op).map(([n, v]) => ({ value: n, label: `The variable ${v.label}${v.from?.by === "reader" ? " · the reader's" : ""}` }))}
          onPick={v => {
            if (v) { keep({ path: c.path, op: op as typeof c.op, value_from: v }); return; }
            // back to a value typed here: the one the condition starts from, or one to give it
            if (op === "in_last") { setText("14"); keep({ path: c.path, op, value: 14 }); } else { setDraft(op); setText(""); }
          }} />
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

/** A value's setup: its name, its kind and the value sets read. Arc AP-8 — while variables are on: its name, what it
 *  holds (days, a number, words, a day), where it comes from (you; the reader on the page, from choices you offer or as
 *  they type; a set's count; the chosen object's property), what it holds now, and everything that reads it. */
export function ValueSetup({ spec, name, onChange, onGone, variablesOn = false, connectionId = "", schema, cardReads, cardTitle, onRenamed, queryCards = [] }: {
  spec: CockpitSpec; name: string; onChange: Change; onGone: () => void;
  variablesOn?: boolean; connectionId?: string; schema?: string;
  cardReads?: (cardId: string) => string[]; cardTitle?: (cardId: string) => string | undefined;
  /** Arc AP-8c — the cards of the person's own query the cockpit places, a value may read the first value of. */
  queryCards?: { id: string; title: string }[];
  /** The name a value has after a rename moved it — the setup follows it. */
  onRenamed?: (name: string) => void;
}) {
  const v = spec.values?.[name];
  const boxed = Array.isArray(v?.value) ? v.value.join(", ") : typeof v?.value === "boolean" ? (v.value ? "yes" : "no") : String(v?.value ?? "");
  const [text, setText] = useState(boxed);
  const [shown, setShown] = useState(boxed);
  if (shown !== boxed) { setShown(boxed); setText(boxed); }
  const [label, setLabel] = useState(v?.label ?? "");
  const [shownLabel, setShownLabel] = useState(v?.label ?? "");
  if (shownLabel !== (v?.label ?? "")) { setShownLabel(v?.label ?? ""); setLabel(v?.label ?? ""); }
  const options = v?.from?.by === "reader" ? v.from.options ?? [] : [];
  const [choicesText, setChoicesText] = useState(options.join(", "));
  const [shownChoices, setShownChoices] = useState(options.join(", "));
  if (shownChoices !== options.join(", ")) { setShownChoices(options.join(", ")); setChoicesText(options.join(", ")); }
  const [said, setSaid] = useState("");
  const chosen = [...choicesOf(spec).values()].filter(c => c.kind === "chosen");
  const chosenEntity = v?.from?.by === "chosen" ? chosen.find(c => c.name === (v.from as { choice: string }).choice)?.entity ?? "" : "";
  // Arc AP-8c — a sum's property is one of its set's entity
  const summed = v?.from?.by === "sum" ? readSet(spec, v.from.set) : null;
  const sumEntity = summed && !isRefused(summed) ? summed.entity : "";
  const fields = useFields(variablesOn ? chosenEntity || sumEntity : "", connectionId, schema);
  if (!v) return null;
  const put = (def: CockpitValueDef, note: string) => onChange(putValue(spec, name, def), note);
  const by = v.from?.by ?? "author";
  // off, a value is what it was before AP-8: days, a number or a word, set by its author
  const kinds = VALUE_KINDS.filter(k => variablesOn || !["date", "yesno", "list"].includes(k));
  const kindLabel = (k: string) => (k === "days" ? "A number of days" : k === "number" ? "A number" : k === "date" ? "A day"
    : k === "yesno" ? "Yes or no" : k === "list" ? "A list" : "A word");
  const startFor = (k: string): CockpitValueDef["value"] => (k === "text" ? (typeof v.value === "string" && v.value) || "words"
    : k === "date" ? new Date().toISOString().slice(0, 10) : k === "yesno" ? true
      : k === "list" ? (Array.isArray(v.value) && v.value.length ? v.value : [typeof v.value === "string" && v.value ? v.value : "words"])
        : k === "days" ? Math.max(1, Math.round(Number(v.value) || 1)) : Number(v.value) || 1);
  const inOptions = (x: unknown) => !options.length || (Array.isArray(x) ? x.every(i => options.some(o => o === i)) : options.some(o => o === x));
  const commitValue = () => {
    const next = typedValue(v.kind, text);
    if (next === null || !inOptions(next)) {
      setSaid(next === null ? `${kindLabel(v.kind)} — ${v.kind === "days" ? "a whole number, one or more" : v.kind === "date" ? "written 2026-10-11"
        : v.kind === "list" ? "items with a comma between, at most 30, each once" : "as it reads"}.`
        : v.kind === "list" ? "It starts from some of the choices offered." : "It starts from one of the choices offered.");
      setText(boxed);
      return;
    }
    setSaid("");
    if (JSON.stringify(next) !== JSON.stringify(v.value)) put({ ...v, value: next as CockpitValueDef["value"] }, "a value changed by hand");
  };
  const commitChoices = () => {
    // a list's choices are its items: each a number or words
    const itemKind = v.kind === "list" ? "list" : v.kind;
    const list = choicesText.split(",").map(x => x.trim()).filter(Boolean).map(x => {
      const t = typedValue(itemKind, x);
      return itemKind === "list" ? (Array.isArray(t) ? t[0] : null) : t;
    });
    if (list.some(x => x === null)) { setSaid(`Each choice is ${v.kind === "list" ? "a number or words" : kindLabel(v.kind).toLowerCase()}.`); setChoicesText(options.join(", ")); return; }
    const unique = [...new Set(list as (string | number)[])].slice(0, MAX_VALUE_OPTIONS);
    setSaid("");
    if (JSON.stringify(unique) === JSON.stringify(options)) return;
    // the value it starts from is among the choices: a list, the ones it held that are offered (else the first); any
    // other value, one of them (else the first)
    const kept = Array.isArray(v.value) ? v.value.filter(x => unique.some(o => o === x)) : [];
    const start: CockpitValueDef["value"] = !unique.length ? v.value
      : v.kind === "list" ? (kept.length ? kept : [unique[0]])
        : !unique.some(o => o === v.value) ? unique[0] : v.value;
    put({ ...v, value: start, from: { by: "reader", ...(unique.length ? { options: unique } : {}) } }, "a value's choices changed by hand");
  };
  const comesFrom = (next: string) => {
    if (next === by) return;
    const { from: _f, value: _v, ...rest } = v;
    void _f; void _v;
    if (next === "author") put({ ...rest, value: startFor(v.kind) }, "a value set by you");
    else if (next === "reader") put({ ...rest, value: v.value ?? startFor(v.kind), from: { by: "reader" } }, "a value the reader sets");
    else if (next === "count") {
      const set = Object.keys(spec.sets ?? {})[0];
      if (set) put({ ...rest, kind: "number", from: { by: "count", set } }, "a value counted from a set");
    } else if (next === "sum") {
      // Arc AP-8c — the first number of the first set's objects, until another is picked
      const set = Object.keys(spec.sets ?? {})[0];
      const r = set ? readSet(spec, set) : null;
      if (!set || !r || isRefused(r)) return;
      void entityFields(r.entity, connectionId, schema).then(f => {
        const first = f.fields.find(x => isNumber(x) && /^[A-Za-z_][A-Za-z0-9_.]*$/.test(x.path));
        if (!first) { setSaid(`A ${words(r.entity).toLowerCase()} has no number to add up.`); return; }
        put({ ...rest, kind: "number", from: { by: "sum", set, path: first.path } }, "a value summed from a set");
      }).catch(e => setSaid(`The set's properties could not be read: ${(e as Error).message}`));
    } else if (next === "query" && queryCards[0]) {
      put({ ...rest, kind: v.kind === "days" ? "number" : v.kind, from: { by: "query", card: queryCards[0].id } }, "a value read from a query");
    } else if (next === "chosen" && chosen[0]) {
      // the first property of the chosen object's own, as words, until another is picked
      const c = chosen[0];
      void entityFields(c.entity, connectionId, schema).then(f => {
        const first = f.fields.find(x => !x.via && /^[A-Za-z_][A-Za-z0-9_]*$/.test(x.path) && !isTime(x) && !isNumber(x))
          ?? f.fields.find(x => !x.via && /^[A-Za-z_][A-Za-z0-9_]*$/.test(x.path));
        if (!first) { setSaid(`A ${words(c.entity).toLowerCase()} has no property of its own to read.`); return; }
        const kind = isTime(first) ? "date" : isNumber(first) ? "number" : "text";
        put({ ...rest, kind, from: { by: "chosen", choice: c.name, path: first.path } }, "a value read from a chosen object");
      }).catch(e => setSaid(`The chosen object's properties could not be read: ${(e as Error).message}`));
    }
  };
  const setNames = Object.keys(spec.sets ?? {});
  const direct = (fields?.fields ?? []).filter(f => !f.via && /^[A-Za-z_][A-Za-z0-9_]*$/.test(f.path));
  return (
    <div data-testid="value-setup" data-name={name}>
      <div style={{ padding: "12px 14px 8px", borderBottom: "1px solid var(--b1)" }}>
        <div className="aug-fs-xs" style={{ color: "var(--accent-11)", textTransform: "uppercase", letterSpacing: ".06em" }}>
          {variablesOn ? `Variable · ${KIND_SAID[v.kind] ?? v.kind}` : "Value"}
        </div>
        <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600, marginTop: 2 }}>{v.label}</div>
      </div>
      {variablesOn && (
        <Row label="Name" hint={<>In a query of your own, <span style={{ fontFamily: "var(--font-mono)" }}>{`{{${name}}}`}</span>.</>}>
          <Input aria-label="The value's name" value={label} maxLength={MAX_LABEL} onChange={e => setLabel(e.target.value)}
            onBlur={() => {
              const t = label.trim();
              if (!t || t === v.label) { setLabel(v.label); return; }
              // its name in SQL follows while nothing reads it yet
              const moved = renameValue(spec, name, t, readersAll(spec, name, cardReads).count > 0);
              onChange(moved.spec, "a value renamed by hand");
              if (moved.name !== name) onRenamed?.(moved.name);
            }}
            onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        </Row>
      )}
      {variablesOn && (
        <Row label="Comes from" testid="value-comes-from"
          hint={by === "reader" ? "A control on the page. Each reader's own, kept in their browser — never in the cockpit."
            : by === "count" ? "How many objects the set holds as the page reads it — each reader's row policies hold."
              : by === "sum" ? "A number added up over the set's objects as the page reads them — each reader's row policies hold."
                : by === "query" ? "The query's first value — every row's, for a list — run as written, never cut to the page's range."
                  : by === "chosen" ? "A property of the object a reader chose — nothing until one is chosen."
                    : "Set once, here, for every reader."}>
          <Pick label="Comes from" value={by} onPick={comesFrom} options={[
            { value: "author", label: "Set by you" }, { value: "reader", label: "Set by the reader on the page" },
            ...(setNames.length ? [{ value: "count", label: "Counted from a set" }, { value: "sum", label: "Summed over a set" }] : []),
            ...(queryCards.length ? [{ value: "query", label: "Read from a query of yours" }] : []),
            ...(chosen.length ? [{ value: "chosen", label: "Read from the chosen object" }] : []),
          ]} />
          {v.from?.by === "sum" && (
            <>
              <Pick label="The set it sums over" value={v.from.set} options={setNames.map(n => ({ value: n, label: `The set ${spec.sets?.[n]?.label ?? n}` }))}
                onPick={set => put({ ...v, from: { by: "sum", set, path: (v.from as { path: string }).path } }, "a value's set chosen by hand")} />
              <Pick label="The number it adds up" value={v.from.path}
                options={[...(fields?.fields ?? []).filter(f => isNumber(f)).map(f => ({ value: f.path, label: f.label })),
                  ...((fields?.fields ?? []).some(f => f.path === (v.from as { path: string }).path) ? [] : [{ value: v.from.path, label: words(v.from.path) }])]}
                onPick={path => put({ ...v, from: { by: "sum", set: (v.from as { set: string }).set, path } }, "a value's number chosen by hand")} />
            </>
          )}
          {v.from?.by === "query" && (
            <>
              <Pick label="The query it reads" value={v.from.card}
                options={[...queryCards.map(c => ({ value: c.id, label: c.title })),
                  ...(queryCards.some(c => c.id === (v.from as { card: string }).card) ? [] : [{ value: v.from.card, label: "A query no longer placed" }])]}
                onPick={card => put({ ...v, from: { by: "query", card, ...((v.from as { column?: string | null }).column ? { column: (v.from as { column: string }).column } : {}) } }, "a value's query chosen by hand")} />
              <QueryColumn column={v.from.column ?? ""} onSet={column => put({ ...v, from: { by: "query", card: (v.from as { card: string }).card, ...(column ? { column } : {}) } }, "a value's column chosen by hand")} />
            </>
          )}
          {v.from?.by === "count" && (
            <Pick label="The set it counts" value={v.from.set} options={setNames.map(n => ({ value: n, label: `The set ${spec.sets?.[n]?.label ?? n}` }))}
              onPick={set => put({ ...v, from: { by: "count", set } }, "a value's set chosen by hand")} />
          )}
          {v.from?.by === "chosen" && (
            <>
              <Pick label="The choice it reads" value={v.from.choice} options={chosen.map(c => ({ value: c.name, label: words(c.name) }))}
                onPick={choice => put({ ...v, from: { by: "chosen", choice, path: (v.from as { path: string }).path } }, "a value's choice chosen by hand")} />
              <Pick label="The property it reads" value={v.from.path} options={[...direct.map(f => ({ value: f.path, label: f.label })),
                ...(direct.some(f => f.path === (v.from as { path: string }).path) ? [] : [{ value: v.from.path, label: words(v.from.path) }])]}
                onPick={path => {
                  const f = direct.find(x => x.path === path);
                  const kind = f && isTime(f) ? "date" : f && isNumber(f) ? "number" : "text";
                  put({ ...v, kind, from: { by: "chosen", choice: (v.from as { choice: string }).choice, path } }, "a value's property chosen by hand");
                }} />
            </>
          )}
        </Row>
      )}
      {variablesOn && by === "query" && (
        <Row label="Is" hint="What its first value is read as; a list reads every row's.">
          <Pick label="Kind" value={v.kind} options={kinds.filter(k => k !== "days").map(k => ({ value: k, label: kindLabel(k) }))}
            onPick={k => put({ ...v, kind: k as CockpitValueDef["kind"] }, "a value's kind chosen by hand")} />
        </Row>
      )}
      {(by === "author" || by === "reader" || !variablesOn) && (
        <Row label={variablesOn && by === "reader" ? "Starts from" : "Is"}>
          {(!variablesOn || (by !== "count" && by !== "sum")) && (
            <Pick label="Kind" value={v.kind} options={kinds.map(k => ({ value: k, label: kindLabel(k) }))}
              onPick={k => {
                const start = startFor(k);
                put({ ...v, kind: k as CockpitValueDef["kind"], value: start, ...(v.from?.by === "reader" ? { from: { by: "reader" as const } } : {}) }, "a value's kind chosen by hand");
              }} />
          )}
          {v.kind === "yesno" ? (
            <Segmented label="The value" value={v.value === false ? "no" : "yes"} options={[{ value: "yes", label: "Yes" }, { value: "no", label: "No" }]}
              onChange={x => { if ((x === "yes") !== v.value) put({ ...v, value: x === "yes" }, "a value changed by hand"); }} />
          ) : (
            <Input aria-label="The value" value={text} type={v.kind === "text" || v.kind === "list" ? "text" : v.kind === "date" ? "date" : "number"}
              placeholder={v.kind === "list" ? "China, Brasil, Japan" : undefined} onChange={e => setText(e.target.value)}
              onBlur={commitValue} onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
          )}
        </Row>
      )}
      {variablesOn && by === "reader" && v.kind !== "yesno" && (
        <Row label="The reader chooses from" hint={`Choices with a comma between — ${v.kind === "days" ? "7, 14, 30, 90" : v.kind === "text" ? "China, Brasil, Japan" : "the values offered"}; none, the reader types their own. At most ${MAX_VALUE_OPTIONS}.`}>
          <Input aria-label="The choices offered" value={choicesText} placeholder="Any the reader types" onChange={e => setChoicesText(e.target.value)}
            onBlur={commitChoices} onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        </Row>
      )}
      {said && <div className="aug-fs-xs" data-testid="value-setup-said" style={{ color: "var(--t2)", padding: "0 14px" }}>{said}</div>}
      {variablesOn && (
        <Row label="Holds now" testid="value-holds">
          <span className="aug-fs-sm" style={{ color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
            <ValueNowText spec={spec} v={v} connectionId={connectionId} schema={schema} />
          </span>
        </Row>
      )}
      <ReadBy spec={spec} name={name} onChange={onChange} onGone={onGone} cardReads={cardReads} cardTitle={cardTitle} />
      {variablesOn && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "4px 14px 12px", lineHeight: 1.45 }}>
          Taken away only when nothing reads it. In SQL it is a bound parameter: the statement never changes.
        </div>
      )}
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
