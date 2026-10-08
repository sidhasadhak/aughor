"use client";

/**
 * DatasetProgram — what each dataset is for, whether it is on, and how mature it is (the exploration
 * principles, docs/EXPLORATION_PRINCIPLES_2026-10-07.md, built 2026-10-08).
 *
 * - **Maturity** is three short vertical bars and a number — Structure, Questions, Time — in the Catalog's
 *   tree, on each schema and table, and beside the scope picker (the user, 2026-10-07: "percentage
 *   highlighted by vertical bars and a number"). A reading that does not apply is drawn faint and says
 *   why ("not explored — raw"), never as 0%.
 * - **Layer** — business, integration, raw, reference, uploads, system — is proposed from the dataset's
 *   signs with the evidence shown, and set by a person (decision 2: a name never sets it by itself).
 * - **Off** takes a schema or a table out of the Explorer, Investigation and Quick analysis at once; a
 *   person can still read it in the SQL editor.
 * - **Budget** — the connection's monthly exploration budget beside the organisation's, the tighter
 *   holding, said when spent.
 */
import { useEffect, useState } from "react";
import {
  acceptDatasetLayers, clearDatasetLayer, getConnectionSettings, getDatasets, setDatasetLayer, setDatasetOff,
  updateConnectionSettings,
  type DatasetSchema, type DatasetTable, type DatasetsView, type Maturity, type MaturityBar,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

const BARS: { key: "structure" | "questions" | "time"; label: string }[] = [
  { key: "structure", label: "Structure" },
  { key: "questions", label: "Questions" },
  { key: "time", label: "Time" },
];

const REASON_LABEL: Record<string, string> = {
  out_of_domain: "not this connection's subject",
  deprecated: "deprecated",
  sensitive: "sensitive",
  system_table: "system or plumbing",
  other: "another reason",
};

const muted: React.CSSProperties = { color: "var(--t3)" };

function pct(b: MaturityBar): string {
  return b.share == null ? "—" : `${Math.round(b.share * 100)}%`;
}

/** Each reading in words, for the bars' title and for a reader without the picture. */
export function maturityWords(m: Maturity): string {
  return BARS.map(b => `${b.label} ${pct(m[b.key])} — ${m[b.key].note}`).join("\n");
}

/** Three short vertical bars and the number beside them. */
export function MaturityBars({ m, size = "sm", showNumber = true }: { m: Maturity | null | undefined; size?: "sm" | "md"; showNumber?: boolean }) {
  if (!m) return null;
  const h = size === "md" ? 16 : 11;
  const w = size === "md" ? 4 : 3;
  const fill = m.stage === "watching" ? "var(--grn4)" : "var(--blue3)";
  return (
    <span role="img" aria-label={`Maturity ${m.percent ?? "—"}%: ${maturityWords(m).replace(/\n/g, "; ")}`}
      title={maturityWords(m)} data-testid="maturity-bars"
      style={{ display: "inline-flex", alignItems: "flex-end", gap: 2, flexShrink: 0 }}>
      {BARS.map(b => {
        const share = m[b.key].share;
        return (
          <span key={b.key} data-bar={b.key}
            style={{ position: "relative", width: w, height: h, background: "var(--b1)", overflow: "hidden",
              opacity: share == null ? 0.4 : 1 }}>
            <span style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: `${Math.round((share ?? 0) * 100)}%`, background: fill }} />
          </span>
        );
      })}
      {showNumber && (
        <span className="aug-fs-xs" style={{ ...muted, marginLeft: 3, fontVariantNumeric: "tabular-nums" }}>
          {m.percent == null ? "—" : `${m.percent}%`}
        </span>
      )}
    </span>
  );
}

/** The three readings with what each says — a schema's or a table's own strip. */
function MaturityLines({ m }: { m: Maturity }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {BARS.map(b => (
        <div key={b.key} className="aug-fs-xs" style={{ color: "var(--t2)" }}>
          <span style={{ fontWeight: 500 }}>{b.label}</span> {pct(m[b.key])} <span style={muted}>· {m[b.key].note}</span>
        </div>
      ))}
    </div>
  );
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** The layer select: the set one, else "not set" with the proposal beside it and one click to accept it. */
function LayerControl({ connId, schema, table, layer, proposed, setBy, layers, onChanged }: {
  connId: string; schema: string; table?: string;
  layer: string; proposed: { layer: string; label: string; evidence: string[] } | null;
  setBy: { set_by: string; set_at: string } | null;
  layers: DatasetsView["layers"]; onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const set = async (v: string) => {
    setBusy(true); setSaid("");
    try {
      if (v) {
        const r = await setDatasetLayer(connId, schema, v, table ?? "");
        if (r.started) setSaid(r.started);
      } else {
        await clearDatasetLayer(connId, schema, table ?? "");
      }
      onChanged();
    } catch (e) { setSaid(errorText(e)); }
    finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span className="aug-fs-xs" style={muted}>Layer</span>
        <SelectField value={layer} disabled={busy} onChange={e => set(e.target.value)}
          aria-label={table ? `Layer of ${table}` : `Layer of ${schema}`} style={{ minWidth: 150 }}>
          <option value="">{table ? "As its schema" : "Not set"}</option>
          {layers.map(l => <option key={l.id} value={l.id}>{l.label}</option>)}
        </SelectField>
        {!layer && proposed?.layer && (
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => set(proposed.layer)}
            data-testid="accept-layer">
            Set as {proposed.label}
          </Button>
        )}
      </div>
      {!layer && proposed?.layer && (
        <span className="aug-fs-xs" style={muted} data-testid="layer-evidence">
          Proposed {proposed.label.toLowerCase()}: {proposed.evidence.join("; ")}
        </span>
      )}
      {layer && setBy && (
        <span className="aug-fs-xs" style={muted}>
          Set by {setBy.set_by}{setBy.set_at ? ` · ${formatTimestamp(setBy.set_at, "short")}` : ""}
        </span>
      )}
      {said && <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>{said}</span>}
    </div>
  );
}

/** On for analysis, or off with a reason. Turning off asks why first. */
function OffSwitch({ connId, schema, table, off, reasons, onChanged }: {
  connId: string; schema: string; table?: string;
  off: DatasetSchema["off"]; reasons: string[]; onChanged: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("out_of_domain");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const act = async (turnOff: boolean) => {
    setBusy(true); setErr("");
    try { await setDatasetOff(connId, schema, turnOff, { table, reason }); setAsking(false); onChanged(); }
    catch (e) { setErr(errorText(e)); }
    finally { setBusy(false); }
  };
  const what = table ? "table" : "schema";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t2)" }}>
        <Switch checked={!off} disabled={busy}
          aria-label={off ? `Turn this ${what} back on` : `Turn this ${what} off for analysis`}
          onChange={e => (e.target.checked ? act(false) : setAsking(true))} />
        {off ? "Off for analysis" : "On for analysis"}
      </label>
      {off && (
        <span className="aug-fs-xs" style={muted}>
          {REASON_LABEL[off.reason] ?? off.reason}{off.declared_by ? ` · by ${off.declared_by}` : ""} — never explored, never queried
          by Investigation or Quick analysis; the SQL editor still reads it
        </span>
      )}
      {asking && !off && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <SelectField value={reason} onChange={e => setReason(e.target.value)} aria-label="Why it is off" style={{ minWidth: 170 }}>
            {reasons.map(r => <option key={r} value={r}>{REASON_LABEL[r] ?? r}</option>)}
          </SelectField>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => act(true)} data-testid="confirm-off">Turn off</Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => setAsking(false)}>Cancel</Button>
        </div>
      )}
      {err && <span className="aug-fs-xs" style={{ color: "var(--red4)" }}>{err}</span>}
    </div>
  );
}

function programLine(ds: DatasetSchema): string[] {
  const out: string[] = [];
  const p = ds.program;
  if (p.held) out.push(`Held: ${p.held.why}`);
  if (p.reopened) out.push(`Reopened: ${p.reopened.reason} — its questions run on the next check`);
  if (p.last_run) {
    const job = p.last_run.job === "full" ? "structure and questions" : p.last_run.job;
    out.push(`Last run: ${job}, ${p.last_run.outcome}${p.last_run.new_findings ? ` · ${p.last_run.new_findings} new finding${p.last_run.new_findings === 1 ? "" : "s"}` : ""}${p.last_run.ended_at ? ` · ${formatTimestamp(p.last_run.ended_at, "short")}` : ""}`);
  }
  for (const [grain, w] of Object.entries(p.watch || {})) {
    const moved = (w.moved || []).map(m => {
      const why = (w.explained || []).find(e => e.name === m.name);
      const part = why ? ` (most of it ${why.dimension} = ${why.group})` : "";
      return `${m.name} ${m.rel > 0 ? "+" : ""}${Math.round(m.rel * 100)}%${part}`;
    }).join(", ");
    out.push(`Watched ${grain}: read to ${w.through}${moved ? ` · moved: ${moved}` : ""}`);
    if (w.story?.text) out.push(`The move, in words: ${w.story.text}`);
    else if (w.story?.withheld) out.push(`Its explanation: ${w.story.withheld}`);
  }
  if (p.unanswered) out.push(`${p.unanswered} question${p.unanswered === 1 ? "" : "s"} it could not answer this week`);
  if (p.health?.read_at) {
    out.push(p.health.notes.length ? `Health: ${p.health.notes.join("; ")}` : "Health: nothing changed since the last reading");
  }
  for (const n of p.news || []) out.push(`New: ${n}`);
  return out;
}

/** A schema's strip: its maturity, its layer and what that layer means, and its on/off switch. */
export function SchemaProgram({ connId, ds, view, onChanged }: {
  connId: string; ds: DatasetSchema | undefined; view: DatasetsView | null; onChanged: () => void;
}) {
  if (!ds || !view) return null;
  return (
    <div data-testid="schema-program"
      style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "10px 16px", borderBottom: "0.5px solid var(--b1)", background: "var(--bg-0)" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <MaturityBars m={ds.maturity} size="md" />
        <MaturityLines m={ds.maturity} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 220, flex: 1 }}>
        <LayerControl connId={connId} schema={ds.name} layer={ds.layer.effective} proposed={ds.layer.proposed}
          setBy={ds.layer.set} layers={view.layers} onChanged={onChanged} />
        <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>{ds.layer.policy}</span>
        {programLine(ds).map(l => <span key={l} className="aug-fs-xs" style={muted}>{l}</span>)}
      </div>
      <OffSwitch connId={connId} schema={ds.name} off={ds.off} reasons={view.exclusion_reasons} onChanged={onChanged} />
    </div>
  );
}

/** A table's strip: its maturity, its own layer (or its schema's), and its on/off switch. */
export function TableProgram({ connId, schema, t, view, schemaOff, onChanged }: {
  connId: string; schema: string; t: DatasetTable | undefined; view: DatasetsView | null;
  schemaOff: boolean; onChanged: () => void;
}) {
  if (!t || !view) return null;
  return (
    <div data-testid="table-program"
      style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "10px 16px", borderBottom: "0.5px solid var(--b1)", background: "var(--bg-0)" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <MaturityBars m={t.maturity} size="md" />
        <MaturityLines m={t.maturity} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <LayerControl connId={connId} schema={schema} table={t.name} layer={t.layer.set?.layer ?? ""}
          proposed={t.layer.proposed} setBy={t.layer.set} layers={view.layers} onChanged={onChanged} />
        {(t.copies?.length ?? 0) > 0 && (
          <span className="aug-fs-xs" style={muted} data-testid="table-copies">
            The same entity as {t.copies!.join(", ")}
          </span>
        )}
      </div>
      {schemaOff
        ? <span className="aug-fs-xs" style={muted}>Off with its schema</span>
        : <OffSwitch connId={connId} schema={schema} table={t.name} off={t.off} reasons={view.exclusion_reasons} onChanged={onChanged} />}
    </div>
  );
}

/** The connection's section: the proposals waiting for a person, and the month's budget. */
export function ConnectionProgram({ connId, view, onChanged }: { connId: string; view: DatasetsView | null; onChanged: () => void }) {
  const [budget, setBudget] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    getConnectionSettings(connId)
      .then(s => { if (live) setBudget(s.exploration_monthly_tokens ? String(s.exploration_monthly_tokens) : ""); })
      .catch(() => { /* the field starts empty; saving still works */ });
    return () => { live = false; };
  }, [connId]);
  if (!view) return null;
  const waiting = view.schemas.filter(s => !s.layer.set && !s.off && s.layer.proposed.layer);
  // tables inside them whose own signs read differently — a `stg_` copy inside a business schema
  const tableProposals = waiting.flatMap(s => s.tables
    .filter(t => t.layer.proposed?.layer && !t.layer.set && !t.off)
    .map(t => ({ key: `${s.key}:${t.name}`, text: `${s.name}.${t.name} → ${t.layer.proposed!.label}` })));
  const accept = async () => {
    setBusy(true); setErr("");
    try { await acceptDatasetLayers(connId); onChanged(); }
    catch (e) { setErr(errorText(e)); }
    finally { setBusy(false); }
  };
  const saveBudget = async () => {
    setBusy(true); setErr(""); setSaved("");
    const n = budget.trim() ? Math.max(0, Math.round(Number(budget.replace(/[, ]/g, "")))) : 0;
    if (!Number.isFinite(n)) { setErr("A budget is a number of tokens"); setBusy(false); return; }
    try { await updateConnectionSettings(connId, { exploration_monthly_tokens: n }); setSaved("Saved"); onChanged(); }
    catch (e) { setErr(errorText(e)); }
    finally { setBusy(false); }
  };
  return (
    <div data-testid="connection-program" style={{ padding: "12px 16px", borderTop: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="aug-label">Exploration</div>
      {waiting.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
            {waiting.length} dataset{waiting.length === 1 ? " has" : "s have"} no layer set — its structure is learned, its questions wait for you:
          </span>
          {waiting.map(s => (
            <span key={s.key} className="aug-fs-xs" style={muted}>
              {s.name} → {s.layer.proposed.label} ({s.layer.proposed.evidence.join("; ")})
            </span>
          ))}
          {tableProposals.length > 0 && (
            <span className="aug-fs-xs" style={muted} data-testid="table-proposals">
              and {tableProposals.length} table{tableProposals.length === 1 ? "" : "s"} inside them read differently:{" "}
              {tableProposals.slice(0, 4).map(t => t.text).join(", ")}{tableProposals.length > 4 ? ", …" : ""}
            </span>
          )}
          <div><Button variant="secondary" size="sm" disabled={busy} onClick={accept} data-testid="accept-all-layers">Accept the proposed layers</Button></div>
        </div>
      ) : (
        <span className="aug-fs-xs" style={muted}>Every dataset's layer is set.</span>
      )}
      <span className="aug-fs-xs" style={{ color: view.budget.spent_out ? "var(--amb4)" : "var(--t2)" }} data-testid="budget-sentence">
        Budget: {view.budget.sentence}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <label className="aug-fs-xs" style={muted} htmlFor={`budget-${connId}`}>This connection's monthly budget (tokens)</label>
        <Input id={`budget-${connId}`} value={budget} onChange={e => { setBudget(e.target.value); setSaved(""); }}
          placeholder="none" inputMode="numeric" style={{ width: 130 }} disabled={busy} />
        <Button variant="ghost" size="sm" onClick={saveBudget} disabled={busy}>Save</Button>
        {saved && <span className="aug-fs-xs" style={{ color: "var(--grn4)" }}>{saved}</span>}
      </div>
      {err && <span className="aug-fs-xs" style={{ color: "var(--red4)" }}>{err}</span>}
    </div>
  );
}

/** The scope bar's mark: the chosen dataset's maturity beside the schema picker (or alone, for a
 *  connection with one schema). Reads nothing it cannot — on a read failure it draws nothing. */
export function ScopeMaturity({ connId, schema }: { connId: string; schema?: string | null }) {
  const [view, setView] = useState<DatasetsView | null>(null);
  useEffect(() => {
    let live = true;
    setView(null);
    getDatasets(connId).then(v => { if (live) setView(v); }).catch(() => { /* no mark is drawn */ });
    return () => { live = false; };
  }, [connId]);
  const ds = view?.schemas.find(s => s.name === schema) ?? (view?.schemas.length === 1 ? view.schemas[0] : undefined);
  if (!ds) return null;
  const stage = ds.off ? "off for analysis" : ds.maturity.stage;
  return (
    <span data-testid="scope-maturity" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span className="aug-label">Maturity</span>
      {ds.off ? null : <MaturityBars m={ds.maturity} />}
      <span className="aug-fs-xs" style={muted}>{stage}{ds.layer.effective ? "" : " · layer not set"}</span>
    </span>
  );
}
