"use client";

/**
 * OntologyPieces — the cockpit's pieces bound to the ontology (Arc OC-4, ROADMAP §3.56; the screen the user approved
 * on 2026-10-09: a late dispatch cockpit, board → table → detail → action).
 *
 * Each piece names what it reads by id and reads it through the doors every other surface uses: a process board reads
 * `GET /ontology/processes`, an objects table `POST /objects/list` (the object door's own compiler), an object detail
 * `GET /objects/{type}/{key}`, and an action button runs a declared action through the governed execute door — or,
 * when running it needs approval, has the door stage it in the Actions inbox for a person. Nothing here computes a figure.
 *
 * The pieces talk to each other through the cockpit, never through the spec: the spec says which table a detail
 * follows (by element key); which object is chosen is the reader's, held here while they look. After an action runs,
 * every piece reads again, so its edit shows in the table and in the detail at once — and on the object's own page,
 * which reads the same edits.
 *
 * An id that stops resolving is said where the piece stands, never drawn as an empty piece.
 *
 * Since 2026-10-10 a cockpit started from an object adds three more (design-mockups/cockpit-from-object.html): a filter
 * column over an entity's categories, a figure and a chart of objects per day. A reader's click in the filter column
 * narrows every piece over that entity — the table too — for that reader only (the user, 2026-10-10): the choice is
 * held here and in their browser, never in the spec. A piece the filters cannot narrow says "Not filtered" while one
 * is on, so a whole-business number is never read as the filtered one.
 */
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Foot, Frame, Title } from "@/components/cockpit/CockpitTile";
import { Masked } from "@/components/objects/Masked";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import {
  anyFilter, chosenWords, conditionsFor, dayLabel, daysBefore, entityKey, figureText, onDays, plural, ticks, toggled,
  windowEnd, type Filters,
} from "@/lib/cockpit/objectView";
import { formatCount, formatDateTime, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { objectHref } from "@/lib/objectLinks";
import {
  cachedObjectCatalog, getDeclaredActions, getObjectPage, listObjects, queryObjects, runOrPropose,
  type ActionCheck, type DeclaredAction, type ObjectListingPage, type ObjectPage, type ObjectQueryRequest,
} from "@/lib/objects";
import { getProcesses, type ProcessDetail, type ProcessesAndRules } from "@/lib/objectTypes";

/** The object a reader chose in a table. */
export interface Picked { objectType: string; typeId: string; pk: string }

interface PiecesValue {
  connectionId?: string;
  schema?: string;
  /** Each table's chosen object, by the table's element key. */
  picked: Record<string, Picked>;
  pick: (table: string, p: Picked | null) => void;
  /** Raised after an action runs, so every piece reads again. */
  tick: number;
  bump: () => void;
  /** The tables the cockpit holds: element key → what it lists. */
  tables: { key: string; entity: string; segment: string }[];
  /** Place a table of a segment beside a board — absent on a cockpit the reader may not change. */
  onPlaceTable?: (entity: string, segment: string) => void;
  /** One read per drawn cockpit and tick, shared by its pieces — never kept past the cockpit that made it. */
  processes: () => Promise<ProcessesAndRules>;
  actions: () => Promise<Record<string, DeclaredAction>>;
  /** The reader's own filters, by entity — never in the spec. */
  filters: Filters;
  toggle: (entity: string, path: string, value: string) => void;
  clear: (entity?: string) => void;
}

const PiecesContext = createContext<PiecesValue | null>(null);

function usePieces(): PiecesValue {
  const ctx = useContext(PiecesContext);
  if (!ctx) throw new Error("an ontology piece was drawn outside its cockpit");
  return ctx;
}

/** Where a reader's filters for one cockpit are remembered: their browser, and only theirs. */
const filtersKey = (cockpit: string) => `aughor:cockpit-filters:${cockpit}`;

function remembered(cockpit?: string): Filters {
  if (!cockpit) return {};
  try {
    const raw = JSON.parse(localStorage.getItem(filtersKey(cockpit)) ?? "{}") as unknown;
    return raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Filters : {};
  } catch { return {}; }
}

export function PiecesProvider({ connectionId, schema, elements, onPlaceTable, cockpitId, children }: {
  connectionId?: string;
  schema?: string;
  elements: Record<string, { type?: string; props?: Record<string, unknown> } | undefined>;
  onPlaceTable?: (entity: string, segment: string) => void;
  /** The cockpit drawn — the key a reader's filters are remembered under; none, and they last while it is open. */
  cockpitId?: string;
  children: ReactNode;
}) {
  const [picked, setPicked] = useState<Record<string, Picked>>({});
  const [filters, setFilters] = useState<Filters>(() => remembered(cockpitId));
  useEffect(() => { setFilters(remembered(cockpitId)); }, [cockpitId]);
  const keep = useCallback((next: Filters) => {
    setFilters(next);
    // a reader's choice changes a row they chose from: the detail is chosen again from what the table now lists
    setPicked({});
    if (!cockpitId) return;
    try { localStorage.setItem(filtersKey(cockpitId), JSON.stringify(next)); } catch { /* it lasts while the cockpit is open */ }
  }, [cockpitId]);
  const toggle = useCallback((entity: string, path: string, value: string) => keep(toggled(filters, entity, path, value)),
    [filters, keep]);
  const clear = useCallback((entity?: string) => {
    if (!entity) { keep({}); return; }
    const next = { ...filters };
    delete next[entityKey(entity)];
    keep(next);
  }, [filters, keep]);
  const [tick, setTick] = useState(0);
  const pick = useCallback((table: string, p: Picked | null) => setPicked(prev => {
    const next = { ...prev };
    if (p) next[table] = p; else delete next[table];
    return next;
  }), []);
  const bump = useCallback(() => setTick(t => t + 1), []);
  const tables = useMemo(() => Object.entries(elements)
    .filter(([, el]) => el?.type === "ObjectTable")
    .map(([key, el]) => ({ key, entity: String(el?.props?.entity ?? ""), segment: String(el?.props?.segment ?? "") })),
  [elements]);
  const reads = useRef(new Map<string, Promise<unknown>>());
  const once = useCallback(<T,>(key: string, read: () => Promise<T>): Promise<T> => {
    let hit = reads.current.get(key) as Promise<T> | undefined;
    if (!hit) {
      hit = read();
      hit.catch(() => reads.current.delete(key));
      reads.current.set(key, hit);
    }
    return hit;
  }, []);
  const processes = useCallback(() => (connectionId
    ? once(`processes|${schema ?? ""}|${tick}`, () => getProcesses(connectionId, schema))
    : Promise.reject(new Error("This cockpit names no connection."))), [connectionId, schema, tick, once]);
  const actions = useCallback(() => (connectionId
    ? once(`actions|${schema ?? ""}`, () => getDeclaredActions(connectionId, schema))
    : Promise.reject(new Error("This cockpit names no connection."))), [connectionId, schema, once]);
  const value = useMemo<PiecesValue>(() => ({
    connectionId, schema, picked, pick, tick, bump, tables, onPlaceTable, processes, actions, filters, toggle, clear,
  }), [connectionId, schema, picked, pick, tick, bump, tables, onPlaceTable, processes, actions, filters, toggle, clear]);
  return <PiecesContext.Provider value={value}>{children}</PiecesContext.Provider>;
}

/** Whether a reader's filter is on anywhere in the cockpit — and so whether `entity`'s pieces are narrowed by one.
 *  Outside a cockpit's pieces (a strip of cards with none), nothing is filtered. */
export function useFiltering(entity?: string): { on: boolean; narrows: boolean } {
  const ctx = useContext(PiecesContext);
  if (!ctx) return { on: false, narrows: false };
  return { on: anyFilter(ctx.filters), narrows: !!entity && conditionsFor(ctx.filters, entity).length > 0 };
}

/** The chip a piece the filters cannot narrow wears while one is on. */
export function NotFiltered() {
  return (
    <span className="aug-fs-xs" data-testid="not-filtered" title="The filters narrow the objects' own pieces; this one reads everything"
      style={{ position: "absolute", top: 10, right: 12, zIndex: 1, color: "var(--t3)", background: "var(--bg-3)",
        border: "1px solid var(--b1)", borderRadius: "var(--r-chip)", padding: "1px 7px", pointerEvents: "auto" }}>
      Not filtered
    </span>
  );
}

/** A piece that cannot be read says so, in its place. */
function Unread({ what, children }: { what: string; children: ReactNode }) {
  return (
    <Frame testid="ontology-piece-unread" dashed>
      <div className="aug-fs-ui" style={{ color: "var(--t1)", fontWeight: 500 }}>{what}</div>
      <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>{children}</div>
    </Frame>
  );
}

function Reading({ what }: { what: string }) {
  return (
    <Frame testid="ontology-piece-reading">
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading {what}…</div>
    </Frame>
  );
}

const words = (id: string) => id.replace(/_/g, " ");

// ── the process board ───────────────────────────────────────────────────────────────────────

export function ProcessBoardPiece({ process }: { process: string }) {
  const { processes, tables, onPlaceTable } = usePieces();
  const [found, setFound] = useState<ProcessDetail | null | undefined>(undefined);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    let alive = true;
    processes()
      .then(all => { if (alive) { setFound(all.processes.find(p => p.id === process) ?? null); setProblem(""); } })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [processes, process]);

  if (problem) return <Unread what="This process could not be read">{problem}</Unread>;
  if (found === undefined) return <Reading what="the process" />;
  if (found === null) {
    return <Unread what="Not a process here">The board names the process “{process}”, which this connection does not declare.</Unread>;
  }
  return (
    <Frame testid="process-board">
      <Title title={found.display_name || words(found.id)}
        right={<span className="aug-fs-xs" style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>Process board</span>} />
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.max(1, found.stages.length)}, minmax(0, 1fr))`, gap: 8 }}>
        {withUniqueKeys(found.stages, st => st.name).map(([k, stage]) => (
          <div key={k} data-testid="process-stage" style={{ background: "var(--bg-1)", borderRadius: "var(--r2)", padding: "8px 10px", minWidth: 0 }}>
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{stage.display_name}</div>
            <div className="aug-fs-h2" style={{ color: "var(--t1)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{formatCount(stage.reached)}</div>
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              {stage.share != null ? pct(stage.share) : "—"}
              {stage.transition?.p50_days != null ? ` · p50 ${stage.transition.p50_days.toFixed(1)} d` : ""}
            </div>
          </div>
        ))}
      </div>
      {withUniqueKeys(found.stages.filter(s => s.promise), st => st.name).map(([k, stage]) => {
        const promise = stage.promise!;
        const segment = promise.overdue_segment ?? "";
        const table = tables.find(t => t.segment === segment);
        const terms = promise.kind === "deadline" ? `by ${words(promise.deadline)}`
          : promise.kind === "within_hours" ? `within ${promise.within_hours} hours` : `within ${promise.within_days} days`;
        return (
          <div key={k} data-testid="process-promise" className="aug-fs-sm"
            style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", borderTop: "1px solid var(--b1)", paddingTop: 8 }}>
            <span style={{ color: "var(--t2)", display: "inline-flex", alignItems: "center", gap: 6 }}>
              <Icon name="clock" size={13} /> {words(promise.name)}: {stage.display_name} {terms}
            </span>
            <span style={{ color: promise.breach_rate ? "var(--red3)" : "var(--t3)" }}>
              {promise.breach_rate != null ? `broken on ${pct(promise.breach_rate, 1)}` : "not measured"}
            </span>
            <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6 }}>
              {promise.open_overdue == null ? null : table ? (
                <Button size="xs" variant="outline" data-testid="process-overdue"
                  title={`Show the table of these, as of ${promise.as_of}`}
                  onClick={() => document.querySelector(`[data-element="${table.key}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>
                  {formatCount(promise.open_overdue)} open and overdue <Icon name="chevd" />
                </Button>
              ) : onPlaceTable && segment ? (
                <Button size="xs" variant="outline" data-testid="process-overdue-place"
                  title="Place a table of the objects still waiting and already past the promise"
                  onClick={() => onPlaceTable(promise.grain_id, segment)}>
                  {formatCount(promise.open_overdue)} open and overdue · add a table
                </Button>
              ) : (
                <span data-testid="process-overdue-count" style={{ color: "var(--t2)" }}>{formatCount(promise.open_overdue)} open and overdue</span>
              )}
            </span>
          </div>
        );
      })}
      {found.leaves && (
        <div className="aug-fs-xs" data-testid="process-leaves" style={{ color: "var(--t3)" }}>
          {found.leaves.left != null ? `${formatCount(found.leaves.left)} left the process` : "Objects leave the process"} when{" "}
          {found.leaves.property} is {found.leaves.values.join(" or ")} — they are not open, and never overdue
          {found.leaves.unknown ? `; ${formatCount(found.leaves.unknown)} hold no ${found.leaves.property} and are left out` : ""}
        </div>
      )}
      {found.counted_over && (
        <div className="aug-fs-xs" data-testid="process-counted-over" style={{ color: "var(--t3)", display: "flex", gap: 4 }}>
          <Icon name="lock" size={11} /> {found.counted_over}
        </div>
      )}
      <Foot icon="process">{found.measured_at ? `Measured ${formatDateTime(found.measured_at)}` : "Not measured yet"} · {found.entity_id}</Foot>
    </Frame>
  );
}

// ── the objects table ──────────────────────────────────────────────────────────────────────

function cell(v: unknown): string {
  if (v === null || v === undefined || v === "" || v === "NULL") return "—";
  if (v === true || v === "true" || v === "True") return "yes";
  if (v === false || v === "false" || v === "False") return "no";
  return String(v);
}

export function ObjectTablePiece({ elementKey, entity, segment, columns, sort, descending, tall }: {
  elementKey: string | null;
  entity: string;
  segment?: string | null;
  columns?: string[] | null;
  sort?: string | null;
  descending?: boolean | null;
  tall: boolean;
}) {
  const { connectionId, schema, tick, picked, pick, filters } = usePieces();
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ObjectListingPage | null>(null);
  const [refused, setRefused] = useState("");
  const limit = tall ? 12 : 6;
  const narrowed = conditionsFor(filters, entity);
  const asked = JSON.stringify([entity, segment, columns, sort, descending, narrowed]);
  useEffect(() => { setOffset(0); }, [asked]);
  useEffect(() => {
    let alive = true;
    listObjects({ entity, segment: segment ?? "", columns: columns ?? [], order_by: sort ?? "",
                  descending: !!descending, offset, limit, filters: narrowed }, connectionId, schema)
      .then(out => {
        if (!alive) return;
        if (out.path === "refused") { setRefused(out.refused); setPage(null); return; }
        setRefused(out.error ?? ""); setPage(out);
      })
      .catch(e => { if (alive) setRefused((e as Error).message); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the table asks
  }, [asked, offset, limit, connectionId, schema, tick]);

  if (refused && !page) return <Unread what="This table cannot be read">{refused}</Unread>;
  if (!page) return <Reading what="the objects" />;
  const chosen = elementKey ? picked[elementKey] : undefined;
  const heading = `${words(page.type_id)}${segment ? ` · ${words(segment)}` : ""}`;
  const shown = page.rows.length;
  return (
    <Frame testid="object-table">
      <Title title={heading} right={
        <span className="aug-fs-xs" title={page.segment_said || undefined} data-testid="object-table-total"
          style={{ color: "var(--t3)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
          {page.total == null ? "not counted" : formatCount(page.total)}
        </span>} />
      <div style={{ overflowX: "auto", minHeight: 0 }}>
        <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse", tableLayout: "auto" }}>
          <thead>
            <tr>
              {withUniqueKeys([{ name: page.key, label: page.key, edited: false }, ...page.columns], c => c.name).map(([k, c]) => (
                <th key={k} style={{ textAlign: "left", fontWeight: 500, color: "var(--t3)", padding: "4px 8px 6px 0", borderBottom: "1px solid var(--b1)", whiteSpace: "nowrap" }}>
                  {c.edited && <Icon name="edit" size={11} label="Set by a declared action" />}
                  {"masked" in c && c.masked && <Icon name="lock" size={11} label="Masked for you — the note under the table says why" />}
                  {" "}{words(c.label)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {/* keyed by each row's object key, made unique: an entity whose key is not unique lists one key twice */}
            {withUniqueKeys(page.rows, r => String(r[0])).map(([rowKey, row]) => {
              const pk = String(row[0]);
              const on = chosen?.pk === pk;
              return (
                <tr key={rowKey} data-testid="object-table-row" aria-selected={on}
                  onClick={() => elementKey && pick(elementKey, on ? null : { objectType: page.object_type, typeId: page.type_id, pk })}
                  style={{ cursor: elementKey ? "pointer" : undefined, background: on ? "var(--bg-sel)" : undefined }}>
                  {row.map((v, i) => (
                    <td key={page.names[i] ?? i} style={{ padding: "5px 8px 5px 0", borderBottom: "1px solid var(--b1)", whiteSpace: "nowrap",
                      color: cell(v) === "—" ? "var(--t3)" : "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
                      {i > 0 && page.columns[i - 1]?.edited && cell(v) !== "—" && <Icon name="edit" size={11} label="Edited" />} {cell(v)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
        {shown === 0 && <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: "8px 0" }}>No objects in this set.</div>}
        {/* what this reader does not see, and why — a row policy, a masked column — said, never implied (Arc OC-7) */}
        {page.caveats.length > 0 && (
          <div className="aug-fs-xs" data-testid="object-table-caveats" style={{ color: "var(--t3)", padding: "6px 0 0" }}>
            {page.caveats.map(c => <div key={c}>{c}</div>)}
          </div>
        )}
      </div>
      <Foot icon="table" aside={
        <span style={{ display: "inline-flex", gap: 4 }}>
          <Button size="icon-xs" variant="ghost" aria-label="Previous page" disabled={offset === 0}
            onClick={() => setOffset(o => Math.max(0, o - limit))}><Icon name="chevl" /></Button>
          <Button size="icon-xs" variant="ghost" aria-label="Next page"
            disabled={page.total != null ? offset + shown >= page.total : shown < limit}
            onClick={() => setOffset(o => o + limit)}><Icon name="chevr" /></Button>
        </span>}>
        {shown ? `${formatCount(offset + 1)}–${formatCount(offset + shown)}` : "0"}{page.total != null ? ` of ${formatCount(page.total)}` : ""}
        {sort ? ` · by ${words(sort)}${descending ? ", highest first" : ""}` : ""}
      </Foot>
    </Frame>
  );
}

// ── the object detail and its actions ───────────────────────────────────────────────────────

/** The object a detail shows, to the action buttons it holds. */
const DetailObject = createContext<{ page: ObjectPage | null; table: string }>({ page: null, table: "" });

export function ObjectDetailPiece({ follows, children }: { follows: string; children?: ReactNode }) {
  const { connectionId, schema, picked, tick, tables } = usePieces();
  const chosen = picked[follows];
  const [page, setPage] = useState<ObjectPage | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    if (!chosen) { setPage(null); setProblem(""); return; }
    let alive = true;
    getObjectPage(chosen.objectType, chosen.pk, connectionId, schema)
      .then(out => {
        if (!alive) return;
        if (out.path === "object") { setPage(out); setProblem(""); }
        else setProblem(out.path === "refused" ? out.refused : out.detail);
      })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [chosen?.objectType, chosen?.pk, connectionId, schema, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tables.some(t => t.key === follows)) {
    return <Unread what="Follows no table">This detail follows “{follows}”, which is not a table on this cockpit.</Unread>;
  }
  if (!chosen) {
    return (
      <Frame testid="object-detail">
        <Title title="Object detail" />
        <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Choose a row in the table to see it here.</div>
      </Frame>
    );
  }
  if (problem) return <Unread what="This object could not be read">{problem}</Unread>;
  if (!page || page.pk !== chosen.pk) return <Reading what={`${words(chosen.typeId)} ${chosen.pk}`} />;
  const key = page.key.toLowerCase();
  const props = [...page.properties.filter(p => p.name.toLowerCase() === key),
    ...page.properties.filter(p => p.name.toLowerCase() !== key && !p.overlay).slice(0, 7),
    ...page.properties.filter(p => p.overlay)];
  return (
    <Frame testid="object-detail">
      <Title title={page.title || `${page.type_name} ${page.pk}`} right={
        <Link className="aug-fs-xs" href={objectHref(page.object_type, page.pk, connectionId, schema)}
          style={{ color: "var(--blue3)", display: "inline-flex", alignItems: "center", gap: 4 }}>
          Open page <Icon name="external" size={11} />
        </Link>} />
      <dl style={{ display: "grid", gridTemplateColumns: "minmax(90px, max-content) minmax(0, 1fr)", columnGap: 12, rowGap: 4, margin: 0 }}>
        {withUniqueKeys(props, x => x.name).map(([k, p]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt className="aug-fs-xs" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 4 }}>
              {p.overlay && <Icon name="edit" size={11} label="Set by an accepted action" />}{p.display_name}
            </dt>
            <dd className="aug-fs-sm" data-testid={p.overlay ? "object-detail-edit" : undefined}
              style={{ margin: 0, overflowWrap: "anywhere", color: p.value == null ? "var(--t3)" : "var(--t1)" }}>
              {p.withheld ? <Masked why={p.withheld} /> : cell(p.value)}
              {p.overlay && (
                <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)" }}>
                  {p.overlay.provenance}{p.overlay.note ? ` — ${p.overlay.note}` : ""}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {children && (
        <DetailObject.Provider value={{ page, table: follows }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>{children}</div>
        </DetailObject.Provider>
      )}
      <Foot icon="eye">Follows the table · read live</Foot>
    </Frame>
  );
}

const word = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** What a press that ran says: "Done." alone when the action declares no check, else what its check found — a run
 *  whose check failed is never read as done. */
export function ranSaid(check?: ActionCheck): string {
  if (!check || check.status === "not_declared") return "Done.";
  if (check.status === "passed") return `Done — its check passed: ${check.why}.`;
  if (check.status === "failed") return `It ran, but its check failed: ${check.why}.`;
  // Arc OC-6 — its calls still in the outbox: the check waits for them to land
  if (check.status === "pending") return `Done — ${check.why}.`;
  // a call the outbox gave up on is not on its way — it is never "done"
  if (check.status === "waits_for_a_person") return `It ran, but ${check.why}.`;
  return `Done — its check could not be read: ${check.why}.`;
}

export function ActionButtonPiece({ action }: { action: string }) {
  const { connectionId, schema, bump, actions } = usePieces();
  const { page } = useContext(DetailObject);
  const [declared, setDeclared] = useState<DeclaredAction | null | undefined>(undefined);
  const [asking, setAsking] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  useEffect(() => {
    let alive = true;
    actions().then(all => { if (alive) setDeclared(all[action] ?? null); })
      .catch(() => { if (alive) setDeclared(null); });
    return () => { alive = false; };
  }, [actions, action]);
  useEffect(() => { setSaid(""); setAsking(false); }, [page?.pk]);

  if (declared === undefined || !page || !connectionId) return null;
  if (declared === null) {
    return <span className="aug-fs-xs" data-testid="action-button-missing" style={{ color: "var(--t3)" }}>The action “{action}” is not declared here.</span>;
  }
  const target = declared.params.find(p => p.kind === "object");
  const fits = !!target && [word(page.type_id), word(page.object_type)].includes(word(target.object_type));
  const asked = declared.params.filter(p => p.kind === "value" && p.required && p.default_value == null);
  const optional = declared.params.filter(p => p.kind === "value" && !(p.required && p.default_value == null));
  const label = declared.display_name || words(declared.id);

  const run = async () => {
    if (!target) return;
    setBusy(true);
    try {
      const params: Record<string, unknown> = { [target.name]: page.pk };
      for (const p of [...asked, ...optional]) if (values[p.name]?.trim()) params[p.name] = values[p.name].trim();
      // Arc OC-6 — the version of each property the action sets, as this detail read it (0: none set yet)
      const expected = Object.fromEntries((declared.edits ?? []).map(e => [e.property,
        page.properties.find(p => p.name.toLowerCase() === e.property.toLowerCase() && p.overlay)?.overlay?.version ?? 0]));
      const out = await runOrPropose(declared.id, params, connectionId, schema, `from a cockpit, on ${page.type_name} ${page.pk}`,
        Object.keys(expected).length ? expected : undefined);
      if (out.status === "ran") { setSaid(ranSaid(out.verification)); setAsking(false); setValues({}); bump(); }
      else if (out.status === "proposed") { setSaid("It needs approval — proposed in Actions."); setAsking(false); }
      else setSaid(out.message);
    } catch (e) {
      setSaid((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span data-testid="action-button" style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      {asking ? (
        <>
          {withUniqueKeys([...asked, ...optional], x => x.name).map(([k, p]) => (
            <Input key={k} aria-label={p.display_name || p.name} placeholder={p.display_name || words(p.name)}
              value={values[p.name] ?? ""} onChange={e => setValues(v => ({ ...v, [p.name]: e.target.value }))}
              style={{ width: 160 }} />
          ))}
          <Button size="xs" disabled={busy || asked.some(p => !values[p.name]?.trim())} onClick={() => void run()}>
            <Icon name="bolt" /> {busy ? "Running…" : label}
          </Button>
          <Button size="xs" variant="ghost" disabled={busy} onClick={() => setAsking(false)}>Cancel</Button>
        </>
      ) : (
        <Button size="xs" variant="secondary" disabled={busy || !fits} aria-label={label}
          title={fits ? declared.description || `Run ${label} on this ${page.type_name}` : `${label} takes a ${target?.object_type || "different"} object`}
          onClick={() => ([...asked, ...optional].length ? setAsking(true) : void run())}>
          <Icon name="bolt" /> {busy ? "Running…" : label}
        </Button>
      )}
      {said && <span className="aug-fs-xs" data-testid="action-button-said" style={{ color: "var(--t2)" }}>{said}</span>}
    </span>
  );
}


// ── a cockpit started from an object: the filter column, a figure, a chart (2026-10-10) ─────────────────────

const num = (v: unknown): number | null => {
  const n = Number(v);
  return v === null || v === undefined || v === "" || Number.isNaN(n) ? null : n;
};

/** What its objects are called, lower case and plural ("orders"): the entity's name in the object catalog. */
function useNoun(entity: string): string {
  const { connectionId } = usePieces();
  const [name, setName] = useState("");
  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    cachedObjectCatalog(connectionId)
      .then(c => {
        const t = c?.object_types.find(o => [o.object_type, o.id].some(n => n.toLowerCase() === entity.toLowerCase()));
        if (alive) setName(t?.display_name ?? "");
      })
      .catch(() => { /* the entity's own spelling stands */ });
    return () => { alive = false; };
  }, [connectionId, entity]);
  return plural(name || words(entity)).toLowerCase();
}

type Read = { rows: unknown[][]; caveats: string[] } | { refused: string } | null;

/** One object query, asked again when what it asks, the connection or the tick changes. Null asks nothing. */
function useObjectQuery(body: ObjectQueryRequest | null): Read {
  const { connectionId, schema, tick } = usePieces();
  const [read, setRead] = useState<Read>(null);
  const asked = JSON.stringify(body);
  useEffect(() => {
    if (!body) { setRead(null); return; }
    let alive = true;
    queryObjects(body, connectionId, schema)
      .then(out => {
        if (!alive) return;
        if (out.path === "refused") setRead({ refused: out.refused });
        else if (out.error) setRead({ refused: out.error });
        else setRead({ rows: out.rows, caveats: out.caveats ?? [] });
      })
      .catch(e => { if (alive) setRead({ refused: (e as Error).message }); });
    return () => { alive = false; };
  }, [asked, connectionId, schema, tick]); // eslint-disable-line react-hooks/exhaustive-deps -- keyed on what it asks
  return read;
}

const COUNT = { name: "n", agg: "count" };

/** The small uppercase label a column or a card is headed by. */
function Label({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "baseline", gap: 6, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
      {children}{right}
    </div>
  );
}

const Via = ({ what }: { what: string }) => (
  <span style={{ color: "var(--vio4)", textTransform: "none", letterSpacing: 0 }}>via {what}</span>
);

export interface FilterProperty { path: string; label: string; via?: string | null }

/** The filter column: each property's values, how many objects hold each, and a bar for it. A reader's click narrows
 *  every piece over the entity; each list is counted under the OTHER filters, never its own. */
export function ObjectFiltersPiece({ entity, properties }: { entity: string; properties: FilterProperty[] }) {
  return (
    <aside data-testid="object-filters" aria-label="Filters" style={{
      background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 14, alignSelf: "start", position: "sticky", top: 12,
    }}>
      {withUniqueKeys(properties, p => p.path).map(([k, p]) => <Facet key={k} entity={entity} prop={p} />)}
    </aside>
  );
}

/** The values a list shows before "Show all", and the most it reads. */
const SHOWN = 6;
const MOST = 50;

function Facet({ entity, prop }: { entity: string; prop: FilterProperty }) {
  const { filters, toggle } = usePieces();
  const [all, setAll] = useState(false);
  const read = useObjectQuery({ object_type: entity, measures: [COUNT], by: [prop.path],
    filters: conditionsFor(filters, entity, prop.path), order_by: "n", descending: true, limit: MOST + 1 });
  const chosen = filters[entityKey(entity)]?.[prop.path] ?? [];
  const head = <Label right={prop.via ? <Via what={prop.via} /> : null}>{prop.label}</Label>;
  if (!read || "refused" in read) {
    return (
      <div data-testid="object-facet">
        {head}
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 5 }}>{read ? read.refused : "Reading…"}</div>
      </div>
    );
  }
  const rows = read.rows.slice(0, MOST).map(r => ({ value: r[0], n: num(r[1]) ?? 0 }));
  // a value chosen and now held by none under the other filters stays, so it can be unchosen
  for (const v of chosen) if (!rows.some(r => String(r.value) === v)) rows.push({ value: v, n: 0 });
  const shown = all ? rows : rows.filter((r, i) => i < SHOWN || chosen.includes(String(r.value)));
  const top = Math.max(1, ...rows.map(r => r.n));
  return (
    <div data-testid="object-facet" role="group" aria-label={prop.label}>
      {head}
      <div style={{ marginTop: 5 }}>
        {shown.map((r, i) => {
          const empty = r.value === null || r.value === undefined || r.value === "" || r.value === "NULL";
          const v = String(r.value);
          const on = chosen.includes(v);
          return (
            <label key={empty ? `empty-${i}` : `v-${v}`} data-testid="object-facet-row" data-on={on || undefined}
              title={empty ? "Objects with no value cannot be chosen" : undefined} className="aug-fs-sm"
              style={{ display: "grid", gridTemplateColumns: "16px minmax(0, 1fr) 52px 48px", alignItems: "center", gap: 7,
                padding: "3px 4px", borderRadius: "var(--r2)", cursor: empty ? "default" : "pointer",
                background: on ? "var(--bg-sel)" : undefined }}>
              <Checkbox checked={on} disabled={empty} aria-label={`${prop.label}: ${empty ? "no value" : v}`}
                onChange={() => toggle(entity, prop.path, v)} />
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: empty ? "var(--t3)" : "var(--t1)" }}>
                {empty ? "No value" : v}
              </span>
              <span style={{ textAlign: "right", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{formatCount(r.n)}</span>
              <span aria-hidden="true" style={{ height: 6, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                <span style={{ display: "block", height: "100%", width: `${(r.n / top) * 100}%`, background: "var(--chart-1)" }} />
              </span>
            </label>
          );
        })}
      </div>
      {rows.length > SHOWN && (
        <Button size="xs" variant="ghost" style={{ marginTop: 2 }} onClick={() => setAll(a => !a)}>
          {all ? "Show fewer" : `Show all ${formatCount(rows.length)}`}
        </Button>
      )}
      {read.rows.length > MOST && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>The first {MOST} values, by how many objects hold each.</div>
      )}
    </div>
  );
}

/** Above the pieces a filter column narrows: what is chosen, a way out, and how many objects that leaves. */
export function FilterBar({ entity, properties }: { entity: string; properties: FilterProperty[] }) {
  const { filters, toggle, clear } = usePieces();
  const noun = useNoun(entity);
  const narrowed = conditionsFor(filters, entity);
  const some = useObjectQuery(narrowed.length ? { object_type: entity, measures: [COUNT], filters: narrowed } : null);
  const every = useObjectQuery({ object_type: entity, measures: [COUNT] });
  const total = every && "rows" in every ? num(every.rows[0]?.[0]) : null;
  const left = some && "rows" in some ? num(some.rows[0]?.[0]) : null;
  const chosen = Object.entries(filters[entityKey(entity)] ?? {}).filter(([, v]) => v.length);
  const label = (path: string) => properties.find(p => p.path === path)?.label ?? words(path);
  return (
    <div data-testid="object-filter-bar" className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", minHeight: 26 }}>
      {chosen.map(([path, values]) => (
        <span key={path} data-testid="object-filter-chip" style={{ display: "inline-flex", alignItems: "center", gap: 4,
          background: "var(--bg-sel)", color: "var(--accent-text)", padding: "2px 4px 2px 9px", borderRadius: "var(--r-pill)" }}>
          {label(path)}: {values.join(", ")}
          <Button size="icon-xs" variant="ghost" aria-label={`Clear ${label(path)}`}
            onClick={() => values.forEach(v => toggle(entity, path, v))}><Icon name="close" size={11} /></Button>
        </span>
      ))}
      {chosen.length > 0 && <Button size="xs" variant="ghost" onClick={() => clear(entity)}>Clear</Button>}
      <span data-testid="object-filter-count" style={{ marginLeft: "auto", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>
        {narrowed.length
          ? `${left == null ? "…" : formatCount(left)} of ${total == null ? "…" : formatCount(total)} ${noun}`
          : `${total == null ? "…" : formatCount(total)} ${noun}`}
      </span>
    </div>
  );
}

/** One figure over an entity's objects, narrowed by the reader's filters, and said beside the whole. */
export function ObjectFigurePiece({ entity, label, agg, path, format, sym }: {
  entity: string; label: string; agg: string; path?: string | null; format?: string | null; sym: string;
}) {
  const { filters } = usePieces();
  const noun = useNoun(entity);
  const measure = { name: "v", agg, path: path ?? "" };
  const narrowed = conditionsFor(filters, entity);
  const every = useObjectQuery({ object_type: entity, measures: [measure] });
  const some = useObjectQuery(narrowed.length ? { object_type: entity, measures: [measure], filters: narrowed } : null);
  const shown = narrowed.length ? some : every;
  if (shown && "refused" in shown) return <Unread what={`${label} cannot be read`}>{shown.refused}</Unread>;
  const value = shown && "rows" in shown ? num(shown.rows[0]?.[0]) : null;
  const whole = every && "rows" in every ? num(every.rows[0]?.[0]) : null;
  const text = (v: number | null) => figureText(v, agg, format, sym);
  const beside = !narrowed.length ? "" : agg === "count" || agg === "count_distinct" || agg === "sum"
    ? `of ${text(whole)}` : `all ${noun} ${text(whole)}`;
  return (
    <Frame testid="object-figure">
      <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{label}</div>
      <div className="aug-fs-display" data-testid="object-figure-value"
        style={{ color: "var(--t1)", fontWeight: 600, fontVariantNumeric: "tabular-nums", lineHeight: 1.2 }}>
        {shown ? text(value) : "…"}
      </div>
      <div className="aug-fs-xs" data-testid="object-figure-whole" style={{ color: "var(--t3)", minHeight: 16 }}>{beside}</div>
    </Frame>
  );
}

// the chart's frame, in its own units (the mockup's): drawn to the card's width
const W = 640, H = 210, LEFT = 40, RIGHT = 632, BASE = 184, TOP = 26;

/** An entity's objects per day over its last whole days: the reader's filtered objects as bars, all of them as a
 *  line behind — or, with no filter on, all of them as bars. Each bar says its day and its count when pointed at. */
export function ObjectChartPiece({ entity, label, time, days }: { entity: string; label: string; time: string; days: number }) {
  const { filters } = usePieces();
  const noun = useNoun(entity);
  const narrowed = conditionsFor(filters, entity);
  const last = useObjectQuery({ object_type: entity, measures: [{ name: "t", agg: "max", path: time }] });
  const end = last && "rows" in last ? windowEnd(String(last.rows[0]?.[0] ?? "")) : "";
  const window = end ? daysBefore(end, days) : [];
  const per = (f: Record<string, unknown>[]): ObjectQueryRequest | null => end ? {
    object_type: entity, measures: [COUNT], time, grain: "day", start: window[0], end, filters: f } : null;
  const every = useObjectQuery(per([]));
  const some = useObjectQuery(narrowed.length ? per(narrowed) : null);
  const [hover, setHover] = useState<number | null>(null);
  const failed = [last, every, some].find(r => r && "refused" in r) as { refused: string } | undefined;
  if (failed) return <Unread what={`${label} cannot be read`}>{failed.refused}</Unread>;
  const all = every && "rows" in every ? onDays(window, every.rows) : null;
  const bars = narrowed.length ? (some && "rows" in some ? onDays(window, some.rows) : null) : all;
  const head = (
    <div style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 500 }} className="aug-fs-chrome">
      <span style={{ color: "var(--t1)" }}>{label} · last {days} days</span>
      {narrowed.length > 0 && (
        <span className="aug-fs-xs" data-testid="object-chart-legend" style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6, color: "var(--t2)", fontWeight: 400 }}>
          <i style={{ width: 10, height: 10, borderRadius: 2, background: "var(--chart-1)", display: "inline-block" }} />{chosenWords(filters, entity)}
          <i style={{ width: 14, height: 2, background: "var(--chart-deemph)", display: "inline-block", marginLeft: 8 }} />All {noun}
        </span>
      )}
    </div>
  );
  if (!bars || !all) return <Frame testid="object-chart">{head}<div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading…</div></Frame>;
  const axis = ticks(Math.max(1, ...all, ...bars));
  const top = axis[axis.length - 1] || 1;
  const y = (v: number) => BASE - (v / top) * (BASE - TOP);
  const slot = (RIGHT - LEFT) / window.length;
  const bw = Math.max(2, slot - 2);
  const x = (i: number) => LEFT + i * slot + 1;
  const mid = (i: number) => x(i) + bw / 2;
  const r = Math.min(2.5, bw / 2);
  const bar = (i: number, v: number) => {
    const t = y(v), b = BASE, l = x(i), w = bw;
    if (b - t < r) return `M${l},${b} V${t} H${l + w} V${b} Z`;
    return `M${l},${b} V${t + r} Q${l},${t} ${l + r},${t} H${l + w - r} Q${l + w},${t} ${l + w},${t + r} V${b} Z`;
  };
  const lastI = window.length - 1;
  const lineEnd = narrowed.length ? all[lastI] : bars[lastI];
  const said = (i: number) => narrowed.length
    ? `${dayLabel(window[i])}: ${formatCount(bars[i])} ${chosenWords(filters, entity)} of ${formatCount(all[i])} ${noun}`
    : `${dayLabel(window[i])}: ${formatCount(all[i])} ${noun}`;
  return (
    <Frame testid="object-chart">
      {head}
      <div style={{ position: "relative" }} onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" data-testid="object-chart-svg"
          aria-label={`${label}, last ${days} days${narrowed.length ? `: ${chosenWords(filters, entity)} as bars, all ${noun} as a line` : ""}`}>
          {axis.map(t => (
            <g key={t}>
              <line x1={LEFT} x2={RIGHT} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
              <text x={LEFT - 6} y={y(t) + 3} textAnchor="end" fill="var(--chart-tick)" style={{ font: "10px Inter, system-ui, sans-serif" }}>{formatCount(t)}</text>
            </g>
          ))}
          {bars.map((v, i) => (
            <g key={window[i]}>
              <path d={bar(i, v)} fill="var(--chart-1)" opacity={hover === null || hover === i ? 1 : 0.55} />
              {i % 7 === 0 && <text x={mid(i)} y={H - 8} textAnchor="middle" fill="var(--chart-tick)" style={{ font: "10px Inter, system-ui, sans-serif" }}>{dayLabel(window[i])}</text>}
              <rect data-testid="object-chart-hit" x={LEFT + i * slot} y={TOP - 10} width={slot} height={BASE - TOP + 10} fill="transparent"
                onMouseEnter={() => setHover(i)}><title>{said(i)}</title></rect>
            </g>
          ))}
          {narrowed.length > 0 && (
            <polyline points={all.map((v, i) => `${mid(i)},${y(v)}`).join(" ")} fill="none" stroke="var(--chart-deemph)"
              strokeWidth={2} strokeLinejoin="round" pointerEvents="none" />
          )}
          <circle cx={mid(lastI)} cy={y(lineEnd)} r={4} fill={narrowed.length ? "var(--chart-deemph)" : "var(--chart-1)"} stroke="var(--bg-2)" strokeWidth={2} pointerEvents="none" />
          <text x={mid(lastI) - 6} y={y(lineEnd) - 8} textAnchor="end" fill="var(--t2)" style={{ font: "10.5px Inter, system-ui, sans-serif" }}>
            {formatCount(lineEnd)} {noun}
          </text>
        </svg>
        {hover !== null && (
          <div data-testid="object-chart-tip" className="aug-fs-xs" role="status" style={{
            position: "absolute", top: 0, left: `${(mid(hover) / W) * 100}%`, transform: `translateX(${hover > lastI / 2 ? "-100%" : "0"})`,
            background: "var(--bg-3)", border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: "4px 8px", color: "var(--t1)",
            whiteSpace: "nowrap", pointerEvents: "none", boxShadow: "var(--shadow-sm)" }}>
            {said(hover)}
          </div>
        )}
      </div>
    </Frame>
  );
}
