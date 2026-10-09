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
 */
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Foot, Frame, Title } from "@/components/cockpit/CockpitTile";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { formatCount, formatDateTime, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { objectHref } from "@/lib/objectLinks";
import {
  getDeclaredActions, getObjectPage, listObjects, runOrPropose,
  type ActionCheck, type DeclaredAction, type ObjectListingPage, type ObjectPage,
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
}

const PiecesContext = createContext<PiecesValue | null>(null);

function usePieces(): PiecesValue {
  const ctx = useContext(PiecesContext);
  if (!ctx) throw new Error("an ontology piece was drawn outside its cockpit");
  return ctx;
}

export function PiecesProvider({ connectionId, schema, elements, onPlaceTable, children }: {
  connectionId?: string;
  schema?: string;
  elements: Record<string, { type?: string; props?: Record<string, unknown> } | undefined>;
  onPlaceTable?: (entity: string, segment: string) => void;
  children: ReactNode;
}) {
  const [picked, setPicked] = useState<Record<string, Picked>>({});
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
  const value = useMemo<PiecesValue>(() => ({ connectionId, schema, picked, pick, tick, bump, tables, onPlaceTable, processes, actions }),
    [connectionId, schema, picked, pick, tick, bump, tables, onPlaceTable, processes, actions]);
  return <PiecesContext.Provider value={value}>{children}</PiecesContext.Provider>;
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
  const { connectionId, schema, tick, picked, pick } = usePieces();
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ObjectListingPage | null>(null);
  const [refused, setRefused] = useState("");
  const limit = tall ? 12 : 6;
  const asked = JSON.stringify([entity, segment, columns, sort, descending]);
  useEffect(() => { setOffset(0); }, [asked]);
  useEffect(() => {
    let alive = true;
    listObjects({ entity, segment: segment ?? "", columns: columns ?? [], order_by: sort ?? "",
                  descending: !!descending, offset, limit }, connectionId, schema)
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
                  {c.edited && <Icon name="edit" size={11} label="Set by a declared action" />} {words(c.label)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.rows.map(row => {
              const pk = String(row[0]);
              const on = chosen?.pk === pk;
              return (
                <tr key={pk} data-testid="object-table-row" aria-selected={on}
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
              {cell(p.value)}
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
      const out = await runOrPropose(declared.id, params, connectionId, schema, `from a cockpit, on ${page.type_name} ${page.pk}`);
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
