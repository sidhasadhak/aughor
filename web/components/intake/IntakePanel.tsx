"use client";

/**
 * IntakePanel — PX-3 (§3.14): the intake lane's door.
 *
 * The backend lane (KI-1…4, `aughor/routers/intake.py`) shipped complete and
 * consumer-less: upload declared knowledge → a per-object PLAN against the live
 * stores → human verdicts → each accept applies through its target store's own
 * governance. This panel is that flow as a screen. Laws it inherits:
 *
 *  - Nothing auto-applies. Verdicts are marked locally and sent in ONE resolve
 *    call; a failed apply STAYS PENDING with its error shown on the row.
 *  - `identical` objects arrive as `noop` — the platform already holds them, so
 *    they render as a collapsed receipt, never as a decision.
 *  - The prose door is the lane's ONE model-spending call, and only an explicit
 *    button press makes it (its running edit-rate — the arc's falsifier — is
 *    shown beside it).
 *  - Every candidate gets a HUMAN label derived from its payload (PX-1's law:
 *    no machine text as a title); the raw payload stays one disclosure away.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  exportIntakeBundle, getConnections, getIntakeMapperStats, getIntakePlan,
  listIntakeBundles, mineIntakeUsage, resolveIntakeBundle, uploadIntakeBundleYaml,
  uploadIntakeFile, uploadIntakeProse, uploadIntakeSheet,
  type Connection, type IntakeBundle, type IntakeCandidate, type IntakeMapperStats,
  type IntakePlan, type IntakeStageResult, type IntakeVerdict,
} from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { claimsOf, getIdToken } from "@/lib/auth";
import { formatTimestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

/** Who is acting: the signed-in email when there is one, else the same word the
 *  actions inbox uses. Display + provenance material — the server owns identity. */
function actorName(): string {
  return claimsOf(getIdToken())?.email || "human";
}

// ── Human labels for typed payloads (PX-1: no machine text as a title) ────────

export function candidateLabel(kind: string, payload: Record<string, unknown>): string {
  const s = (k: string) => String(payload[k] ?? "").trim();
  switch (kind) {
    case "metric": return s("name") || "metric";
    case "synonym": return s("synonym") ? `“${s("synonym")}” → ${s("subject_id") || s("subject_kind")}` : "synonym";
    case "glossary": return s("table") || "glossary entry";
    case "rule": case "join": case "definition": return s("title") || kind;
    case "trusted_query": return s("question") || "trusted query";
    case "pack": {
      const md = s("skill_md");
      const heading = md.split("\n").find(l => l.startsWith("# "));
      return heading ? heading.slice(2).trim() : "skill";
    }
    default: {
      const first = Object.values(payload).find(v => typeof v === "string" && v.trim());
      return typeof first === "string" ? first.trim().slice(0, 80) : kind;
    }
  }
}

const KIND_WORD: Record<string, string> = {
  metric: "Metric", synonym: "Synonym", glossary: "Glossary", rule: "Rule",
  join: "Join", definition: "Definition", trusted_query: "Trusted query", pack: "Skill",
};

const VERDICT_STYLE: Record<IntakeVerdict, { word: string; color: string }> = {
  new: { word: "new", color: "var(--grn4)" },
  changed: { word: "changed", color: "var(--blue4)" },
  conflict: { word: "conflict", color: "var(--amb4)" },
  identical: { word: "already declared", color: "var(--t4)" },
};

function VerdictChip({ verdict }: { verdict: IntakeVerdict }) {
  const v = VERDICT_STYLE[verdict] ?? VERDICT_STYLE.new;
  return (
    <span className="aug-fs-xs" style={{
      color: v.color, border: `1px solid color-mix(in srgb, ${v.color} 45%, transparent)`,
      borderRadius: "var(--r-chip)", padding: "1px 8px", whiteSpace: "nowrap",
    }}>{v.word}</span>
  );
}

// ── Payload disclosure ────────────────────────────────────────────────────────

const LONG_FIELDS = new Set(["sql", "body", "skill_md", "description"]);

function PayloadView({ payload }: { payload: Record<string, unknown> }) {
  const entries = Object.entries(payload);
  if (!entries.length) return null;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", padding: "8px 0 2px" }}>
      {entries.map(([k, v]) => (
        <React.Fragment key={k}>
          <span className="aug-fs-xs" style={{ color: "var(--t4)", paddingTop: 1 }}>{k}</span>
          {LONG_FIELDS.has(k) && typeof v === "string" ? (
            <pre className="aug-fs-xs" style={{
              margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word",
              fontFamily: "var(--font-mono)", color: "var(--t2)",
              background: "var(--bg-1)", border: "1px solid var(--b0)",
              borderRadius: "var(--r2)", padding: "6px 8px", maxHeight: 180, overflow: "auto",
            }}>{v}</pre>
          ) : (
            <span className="aug-fs-sm" style={{ color: "var(--t2)", wordBreak: "break-word" }}>
              {typeof v === "string" ? v : JSON.stringify(v)}
            </span>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ── One candidate row ─────────────────────────────────────────────────────────

type Decision = "accept" | "dismiss" | undefined;

function CandidateRow({ cand, decision, onDecide, edit, onEdit, applyError }: {
  cand: IntakeCandidate;
  decision: Decision;
  onDecide: (d: Decision) => void;
  edit: string | undefined;                    // JSON text while the editor is open
  onEdit: (text: string | undefined) => void;  // undefined closes the editor
  applyError?: string;
}) {
  const [open, setOpen] = useState(false);
  const pending = cand.status === "pending";
  const label = candidateLabel(cand.kind, cand.payload);
  let editInvalid = false;
  if (edit !== undefined) {
    try { JSON.parse(edit); } catch { editInvalid = true; }
  }
  return (
    <div data-testid={`intake-cand-${cand.id}`} style={{
      border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: "8px 12px",
      background: decision === "accept" ? "color-mix(in srgb, var(--grn4) 6%, transparent)"
        : decision === "dismiss" ? "color-mix(in srgb, var(--t4) 8%, transparent)" : "var(--bg-2)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Button variant="ghost" onClick={() => setOpen(o => !o)} data-testid={`intake-open-${cand.id}`}
          className="aug-fs-sm h-auto min-w-0 flex-1 justify-start gap-2 border-none p-0 text-left font-normal hover:bg-transparent"
          style={{ color: "var(--t1)" }}>
          <Icon name={open ? "chevd" : "chevr"} size={14} />
          <span className="aug-fs-xs" style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>
            {KIND_WORD[cand.kind] ?? cand.kind}
          </span>
          <span style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {label}
          </span>
          <VerdictChip verdict={cand.verdict} />
        </Button>
        {pending ? (
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <Button size="xs" variant={decision === "accept" ? "default" : "minimal"}
              onClick={() => onDecide(decision === "accept" ? undefined : "accept")}>
              <Icon name="check" size={12} /> Accept
            </Button>
            <Button size="xs" variant={decision === "dismiss" ? "destructive" : "minimal"}
              onClick={() => onDecide(decision === "dismiss" ? undefined : "dismiss")}>
              <Icon name="close" size={12} /> Dismiss
            </Button>
          </div>
        ) : (
          <span className="aug-fs-xs" style={{ color: "var(--t4)", flexShrink: 0 }}>
            {cand.status === "accepted" && cand.target_ref
              ? <>applied → <span style={{ fontFamily: "var(--font-mono)" }}>{cand.target_ref}</span></>
              : cand.status}
          </span>
        )}
      </div>
      {cand.detail && (
        <p className="aug-fs-xs" style={{ color: cand.verdict === "conflict" ? "var(--amb4)" : "var(--t3)",
          margin: "6px 0 0 22px" }}>{cand.detail}</p>
      )}
      {applyError && (
        <p className="aug-fs-xs" style={{ color: "var(--red4)", margin: "6px 0 0 22px" }}>
          Could not apply — {applyError}. It stays pending; edit it and try again.
        </p>
      )}
      {open && (
        <div style={{ margin: "4px 0 0 22px" }}>
          <PayloadView payload={cand.edited_payload ?? cand.payload} />
          {pending && edit === undefined && (
            <Button size="xs" variant="ghost"
              onClick={() => onEdit(JSON.stringify(cand.payload, null, 2))}>
              <Icon name="edit" size={12} /> Edit before accepting
            </Button>
          )}
          {edit !== undefined && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <textarea value={edit} onChange={e => onEdit(e.target.value)} rows={8}
                data-testid={`intake-edit-${cand.id}`}
                className="aug-fs-xs"
                style={{ width: "100%", fontFamily: "var(--font-mono)", color: "var(--t1)",
                  background: "var(--bg-1)", border: `1px solid ${editInvalid ? "var(--red4)" : "var(--b1)"}`,
                  borderRadius: "var(--r2)", padding: 8, boxSizing: "border-box", resize: "vertical" }} />
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span className="aug-fs-xs" style={{ color: editInvalid ? "var(--red4)" : "var(--t4)" }}>
                  {editInvalid ? "Not valid JSON yet." : "An edited object is accepted with your version."}
                </span>
                <Button size="xs" variant="ghost" onClick={() => onEdit(undefined)}>Discard edit</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Provenance trail (an accepted object walked back to its import) ──────────

function ProvenanceNote({ targetRef }: { targetRef: string }) {
  const [trail, setTrail] = useState<Record<string, unknown>[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(`${getApiBase()}/intake/provenance?ref=${encodeURIComponent(targetRef)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();
        if (live) setTrail(d.trail ?? []);
      } catch (e) { if (live) setErr(String(e)); }
    })();
    return () => { live = false; };
  }, [targetRef]);
  if (err) return <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>trail unavailable</span>;
  if (!trail) return <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>…</span>;
  const t = trail[0] as { bundle_source?: string; uploaded_by?: string; uploaded_at?: string;
    resolved_by?: string; content_hash?: string } | undefined;
  if (!t) return <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>no trail recorded</span>;
  return (
    <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
      from <strong>{t.bundle_source || "an import"}</strong>, uploaded by {t.uploaded_by || "?"}
      {" "}({formatTimestamp(t.uploaded_at, "short")}), accepted by {t.resolved_by || "?"} ·
      bundle <span style={{ fontFamily: "var(--font-mono)" }}>{(t.content_hash || "").slice(0, 10)}</span>
    </span>
  );
}

// ── The staging doors ─────────────────────────────────────────────────────────

type DoorId = "file" | "paste" | "sheet" | "usage" | "wiki" | "prose";
type IconName = React.ComponentProps<typeof Icon>["name"];

const DOORS: { id: DoorId; word: string; icon: IconName }[] = [
  { id: "file", word: "File", icon: "upload" },
  { id: "paste", word: "Paste a bundle", icon: "edit" },
  { id: "sheet", word: "Google Sheet", icon: "table" },
  { id: "usage", word: "Mine usage", icon: "spark" },
  { id: "wiki", word: "Mine a wiki", icon: "brief" },
  { id: "prose", word: "Prose (model)", icon: "wand" },
];

function Doors({ connId, onStaged, knowledgeConns }: {
  connId: string;
  onStaged: (r: IntakeStageResult) => void;
  knowledgeConns: Connection[];
}) {
  const [door, setDoor] = useState<DoorId>("file");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [yamlText, setYamlText] = useState("");
  const [sheetUrl, setSheetUrl] = useState("");
  const [sheetTab, setSheetTab] = useState("");
  const [proseText, setProseText] = useState("");
  const [wikiConn, setWikiConn] = useState("");
  const [stats, setStats] = useState<IntakeMapperStats | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (door !== "prose") return;
    getIntakeMapperStats().then(setStats).catch(() => setStats(null));
  }, [door]);

  async function run(fn: () => Promise<IntakeStageResult | null>, doneNote?: string) {
    setBusy(true); setErr(""); setNote("");
    try {
      const r = await fn();
      if (r) {
        onStaged(r);
        setNote(r.duplicate
          ? "This exact content was imported before — showing the existing plan."
          : doneNote ?? "Staged. Review the plan below.");
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  const label = { display: "flex", flexDirection: "column" as const, gap: 4 };
  const input: React.CSSProperties = {
    background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r2)",
    color: "var(--t1)", padding: "6px 8px", boxSizing: "border-box", width: "100%",
  };

  return (
    <div style={{ border: "1px solid var(--b0)", borderRadius: "var(--r3)",
      background: "var(--bg-2)", padding: 12 }}>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 10 }}>
        {DOORS.filter(d => d.id !== "wiki" || knowledgeConns.length > 0).map(d => (
          <Button key={d.id} size="xs" variant={door === d.id ? "secondary" : "ghost"}
            onClick={() => { setDoor(d.id); setErr(""); setNote(""); }}>
            <Icon name={d.icon} size={12} /> {d.word}
          </Button>
        ))}
      </div>

      {door === "file" && (
        <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <input ref={fileRef} type="file" hidden data-testid="intake-file-input"
            accept=".csv,.tsv,.xlsx,.json,.md,.markdown,.yaml,.yml"
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) run(() => uploadIntakeFile(f, connId, actorName()),
                `“${f.name}” staged. Review the plan below.`);
              e.target.value = "";
            }} />
          <Button size="sm" disabled={busy} onClick={() => fileRef.current?.click()}>
            <Icon name="upload" size={13} /> Choose a file
          </Button>
          <span style={{ color: "var(--t3)" }}>
            A metric dictionary (CSV / TSV / XLSX), a dbt <span style={{ fontFamily: "var(--font-mono)" }}>manifest.json</span>,
            or a SKILL.md. Every object still waits for your verdict.
          </span>
        </div>
      )}

      {door === "paste" && (
        <div style={label}>
          <textarea value={yamlText} onChange={e => setYamlText(e.target.value)} rows={6}
            placeholder={"version: 1\nsections:\n  metrics:\n    - name: revenue\n      sql: SUM(amount)"}
            className="aug-fs-xs" style={{ ...input, fontFamily: "var(--font-mono)", resize: "vertical" }} />
          <div>
            <Button size="sm" disabled={busy || !yamlText.trim()}
              onClick={() => run(() => uploadIntakeBundleYaml({
                yaml_text: yamlText, connection_id: connId, actor: actorName(), source: "pasted" }))}>
              Stage the bundle
            </Button>
          </div>
        </div>
      )}

      {door === "sheet" && (
        <div className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input value={sheetUrl} onChange={e => setSheetUrl(e.target.value)}
            placeholder="Spreadsheet link or id (link-shared)" style={{ ...input, flex: 2, minWidth: 220 }} />
          <input value={sheetTab} onChange={e => setSheetTab(e.target.value)}
            placeholder="Worksheet (first tab if empty)" style={{ ...input, flex: 1, minWidth: 140 }} />
          <Button size="sm" disabled={busy || !sheetUrl.trim()}
            onClick={() => run(() => uploadIntakeSheet({
              spreadsheet: sheetUrl.trim(), sheet: sheetTab.trim(),
              connection_id: connId, actor: actorName() }))}>
            Fetch & stage
          </Button>
        </div>
      )}

      {door === "usage" && (
        <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Button size="sm" disabled={busy}
            onClick={() => { setBusy(true); setErr(""); setNote("");
              mineIntakeUsage(connId, actorName())
                .then(r => {
                  if (r.staged && r.bundle) { onStaged(r as IntakeStageResult); setNote("Mined. Review the plan below."); }
                  else setNote(r.note || "Nothing minable yet.");
                })
                .catch(e => setErr(e instanceof Error ? e.message : String(e)))
                .finally(() => setBusy(false)); }}>
            <Icon name="spark" size={13} /> Mine what this connection has witnessed
          </Button>
          <span style={{ color: "var(--t3)" }}>
            Validated runs become trusted-query proposals; recurring guard fires become rules. No model call.
          </span>
        </div>
      )}

      {door === "wiki" && (
        <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <select value={wikiConn} onChange={e => setWikiConn(e.target.value)} style={{ ...input, width: "auto" }}>
            <option value="">Choose a wiki connection…</option>
            {knowledgeConns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <Button size="sm" disabled={busy || !wikiConn}
            onClick={() => { setBusy(true); setErr(""); setNote("");
              fetch(`${getApiBase()}/intake/mine`, { method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ knowledge_connection_id: wikiConn,
                  connection_id: connId, actor: actorName() }) })
                .then(async res => { if (!res.ok) throw new Error(await res.text()); return res.json(); })
                .then(d => setNote(`${d.staged} page(s) staged, ${d.duplicates} unchanged, ${d.skipped} without a dictionary table.`))
                .catch(e => setErr(e instanceof Error ? e.message : String(e)))
                .finally(() => setBusy(false)); }}>
            Walk its pages for definition tables
          </Button>
          <span style={{ color: "var(--t3)" }}>Deterministic — tables only; each page becomes its own bundle.</span>
        </div>
      )}

      {door === "prose" && (
        <div style={label}>
          <textarea value={proseText} onChange={e => setProseText(e.target.value)} rows={5}
            placeholder="Paste prose or markdown that states definitions — e.g. “MRR is monthly recurring revenue, computed as …”"
            className="aug-fs-sm" style={{ ...input, resize: "vertical" }} />
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <Button size="sm" disabled={busy || !proseText.trim()}
              onClick={() => { setBusy(true); setErr(""); setNote("");
                uploadIntakeProse({ connection_id: connId, actor: actorName(), text: proseText })
                  .then(r => {
                    if (r.bundle && r.candidates) { onStaged(r as IntakeStageResult); setNote("Extracted. Review the plan below."); }
                    else setNote(r.note || "The model extracted nothing it could state as a fact.");
                    if (r.mapper_stats) setStats(r.mapper_stats);
                  })
                  .catch(e => setErr(e instanceof Error ? e.message : String(e)))
                  .finally(() => setBusy(false)); }}>
              <Icon name="wand" size={13} /> Extract with the model — one call
            </Button>
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              This is the lane&rsquo;s only model-spending door, and only this button presses it.
              {stats && stats.edit_rate !== null && (
                <> Running edit-rate on its candidates: <strong>{Math.round((stats.edit_rate ?? 0) * 100)}%</strong> (parks at {Math.round(stats.threshold * 100)}%).</>
              )}
            </span>
          </div>
        </div>
      )}

      {busy && <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "8px 0 0" }}>Working…</p>}
      {note && !busy && <p className="aug-fs-xs" style={{ color: "var(--grn4)", margin: "8px 0 0" }}>{note}</p>}
      {err && <p className="aug-fs-xs" style={{ color: "var(--red4)", margin: "8px 0 0" }}>{err}</p>}
    </div>
  );
}

// ── The panel ─────────────────────────────────────────────────────────────────

export function IntakePanel({ connId }: { connId: string }) {
  const [bundles, setBundles] = useState<IntakeBundle[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [plan, setPlan] = useState<IntakePlan | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [applyErrors, setApplyErrors] = useState<Record<string, string>>({});
  const [refused, setRefused] = useState<string[]>([]);
  const [resolveNote, setResolveNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [knowledgeConns, setKnowledgeConns] = useState<Connection[]>([]);
  const [showNoop, setShowNoop] = useState(false);
  const [exportText, setExportText] = useState<string | null>(null);

  const loadBundles = useCallback(async () => {
    try { setBundles(await listIntakeBundles(connId)); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, [connId]);

  useEffect(() => {
    setSelected(""); setPlan(null); setDecisions({}); setEdits({});
    setApplyErrors({}); setRefused([]); setResolveNote(""); setErr(""); setExportText(null);
    loadBundles();
  }, [connId, loadBundles]);

  useEffect(() => {
    getConnections()
      .then(cs => setKnowledgeConns(cs.filter(c => c.conn_type === "confluence" || c.conn_type === "notion")))
      .catch(() => setKnowledgeConns([]));
  }, []);

  const openPlan = useCallback(async (bundleId: string) => {
    setSelected(bundleId); setDecisions({}); setEdits({}); setApplyErrors({});
    setResolveNote(""); setErr("");
    try { setPlan(await getIntakePlan(bundleId)); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, []);

  function onStaged(r: IntakeStageResult) {
    setRefused(r.refused ?? []);
    loadBundles();
    setSelected(r.bundle.id);
    setPlan({ bundle: r.bundle, summary: r.summary, candidates: r.candidates });
    setDecisions({}); setEdits({}); setApplyErrors({}); setResolveNote("");
  }

  const pending = useMemo(() => (plan?.candidates ?? []).filter(c => c.status === "pending"), [plan]);
  const noops = useMemo(() => (plan?.candidates ?? []).filter(c => c.status === "noop"), [plan]);
  const settled = useMemo(() => (plan?.candidates ?? []).filter(c => c.status === "accepted" || c.status === "dismissed"), [plan]);
  const acceptIds = useMemo(() => Object.entries(decisions).filter(([, d]) => d === "accept").map(([id]) => id), [decisions]);
  const dismissIds = useMemo(() => Object.entries(decisions).filter(([, d]) => d === "dismiss").map(([id]) => id), [decisions]);

  async function applyVerdicts() {
    if (!plan || (!acceptIds.length && !dismissIds.length)) return;
    setBusy(true); setErr(""); setResolveNote("");
    try {
      const editPayloads: Record<string, Record<string, unknown>> = {};
      for (const id of acceptIds) {
        const text = edits[id];
        if (text !== undefined) {
          try { editPayloads[id] = JSON.parse(text); }
          catch { throw new Error("One of your edits is not valid JSON — fix or discard it first."); }
        }
      }
      const res = await resolveIntakeBundle(plan.bundle.id, {
        actor: actorName(), accept: acceptIds, dismiss: dismissIds, edits: editPayloads,
      });
      const errRows: Record<string, string> = {};
      for (const r of res.results) if (r.outcome === "error") errRows[r.id] = r.reason ?? "apply failed";
      setApplyErrors(errRows);
      setResolveNote(`${res.accepted} applied · ${res.dismissed} dismissed`
        + (res.errors ? ` · ${res.errors} failed and stay pending` : ""));
      setDecisions({}); setEdits({});
      setPlan(await getIntakePlan(plan.bundle.id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function doExport() {
    setBusy(true); setErr("");
    try { setExportText((await exportIntakeBundle(connId)).yaml_text); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "flex-start",
        padding: "10px 12px", borderRadius: "var(--r3)",
        background: "color-mix(in srgb, var(--blue4) 7%, transparent)",
        border: "1px solid color-mix(in srgb, var(--blue4) 22%, transparent)", color: "var(--t2)" }}>
        <span style={{ color: "var(--blue4)", display: "inline-flex", marginTop: 1 }}><Icon name="info" size={14} /></span>
        <p style={{ margin: 0, lineHeight: 1.55 }}>
          Bring declared knowledge in from files, sheets, wikis or this platform&rsquo;s own usage.
          Every object is diffed against what&rsquo;s already declared and waits for your verdict —
          nothing lands until you accept it, and each accept goes through the target store&rsquo;s
          own governance.
        </p>
      </div>

      <Doors connId={connId} onStaged={onStaged} knowledgeConns={knowledgeConns} />

      {refused.length > 0 && (
        <div className="aug-fs-xs" style={{ border: "1px solid color-mix(in srgb, var(--amb4) 40%, transparent)",
          borderRadius: "var(--r2)", padding: "8px 12px", color: "var(--amb4)" }}>
          {refused.length} row{refused.length === 1 ? "" : "s"} could not be taken and {refused.length === 1 ? "was" : "were"} refused at the door:
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {refused.slice(0, 5).map((r, i) => <li key={i}>{r}</li>)}
            {refused.length > 5 && <li>…and {refused.length - 5} more</li>}
          </ul>
        </div>
      )}

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        {/* Imports rail */}
        <div style={{ width: 260, flexShrink: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span className="aug-fs-xs" style={{ color: "var(--t3)", fontWeight: 600,
              textTransform: "uppercase", letterSpacing: "0.06em" }}>Imports</span>
            <Button size="xs" variant="ghost" onClick={doExport} disabled={busy}>
              <Icon name="download" size={12} /> Export
            </Button>
          </div>
          {bundles.length === 0 && (
            <p className="aug-fs-sm" style={{ color: "var(--t4)", margin: "8px 0" }}>
              Nothing imported yet — pick a door above to stage your first plan.
            </p>
          )}
          {bundles.map(b => (
            <Button key={b.id} variant="ghost" onClick={() => openPlan(b.id)}
              data-testid={`intake-bundle-${b.id}`}
              className="h-auto w-full flex-col items-start gap-0.5 whitespace-normal p-2 text-left font-normal"
              style={{ background: selected === b.id ? "var(--bg-sel)" : "var(--bg-2)",
                border: `1px solid ${selected === b.id ? "var(--b2)" : "var(--b0)"}`,
                borderRadius: "var(--r2)" }}>
              <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500, maxWidth: "100%",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {b.source || "bundle"}
              </span>
              <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
                {formatTimestamp(b.uploaded_at, "short")} · {b.uploaded_by || "?"}
              </span>
            </Button>
          ))}
        </div>

        {/* Plan */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          {!plan && (
            <p className="aug-fs-sm" style={{ color: "var(--t4)", margin: "8px 0" }}>
              {bundles.length ? "Select an import to review its plan." : ""}
            </p>
          )}
          {plan && (
            <>
              <div className="aug-fs-sm" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", color: "var(--t3)" }}>
                <span style={{ color: "var(--t1)", fontWeight: 600 }}>{plan.bundle.source || "bundle"}</span>
                <span style={{ color: "var(--grn4)" }}>{plan.summary.new} new</span>
                <span style={{ color: "var(--blue4)" }}>{plan.summary.changed} changed</span>
                {plan.summary.conflict > 0 && <span style={{ color: "var(--amb4)" }}>{plan.summary.conflict} in conflict</span>}
                <span style={{ color: "var(--t4)" }}>{plan.summary.identical} already declared</span>
              </div>

              {pending.length > 0 && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Button size="xs" variant="minimal" data-testid="intake-accept-safe"
                    onClick={() => setDecisions(d => {
                      const next = { ...d };
                      for (const c of pending) if (c.verdict !== "conflict") next[c.id] = "accept";
                      return next;
                    })}>
                    Accept every new &amp; changed ({pending.filter(c => c.verdict !== "conflict").length})
                  </Button>
                  <Button size="xs" variant="ghost"
                    onClick={() => setDecisions(d => {
                      const next = { ...d };
                      for (const c of pending) if (!next[c.id]) next[c.id] = "dismiss";
                      return next;
                    })}>
                    Dismiss the rest
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => setDecisions({})}>Clear marks</Button>
                </div>
              )}

              {pending.map(c => (
                <CandidateRow key={c.id} cand={c}
                  decision={decisions[c.id]}
                  onDecide={d => setDecisions(prev => ({ ...prev, [c.id]: d }))}
                  edit={edits[c.id]}
                  onEdit={text => {
                    setEdits(prev => {
                      const next = { ...prev };
                      if (text === undefined) delete next[c.id]; else next[c.id] = text;
                      return next;
                    });
                    if (text !== undefined) setDecisions(prev => ({ ...prev, [c.id]: "accept" }));
                  }}
                  applyError={applyErrors[c.id]} />
              ))}

              {pending.length === 0 && settled.length + noops.length > 0 && (
                <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: "4px 0" }}>
                  Every decision on this import is made.
                </p>
              )}

              {settled.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {settled.map(c => (
                    <div key={c.id} className="aug-fs-sm" style={{ display: "flex", gap: 8,
                      alignItems: "baseline", flexWrap: "wrap", color: "var(--t3)",
                      padding: "4px 12px", borderLeft: "2px solid var(--b1)" }}>
                      <span style={{ color: "var(--t2)" }}>{candidateLabel(c.kind, (c.edited_payload ?? c.payload))}</span>
                      {c.status === "accepted"
                        ? <><span style={{ color: "var(--grn4)" }}>accepted</span>
                            {c.target_ref && <ProvenanceNote targetRef={c.target_ref} />}</>
                        : <span style={{ color: "var(--t4)" }}>dismissed</span>}
                    </div>
                  ))}
                </div>
              )}

              {noops.length > 0 && (
                <div>
                  <Button size="xs" variant="ghost" onClick={() => setShowNoop(s => !s)}>
                    <Icon name={showNoop ? "chevd" : "chevr"} size={12} />
                    {noops.length} already declared — nothing to decide
                  </Button>
                  {showNoop && (
                    <ul className="aug-fs-sm" style={{ color: "var(--t4)", margin: "6px 0 0", paddingLeft: 26 }}>
                      {noops.map(c => <li key={c.id}>{KIND_WORD[c.kind] ?? c.kind}: {candidateLabel(c.kind, c.payload)}</li>)}
                    </ul>
                  )}
                </div>
              )}

              {(acceptIds.length > 0 || dismissIds.length > 0) && (
                <div style={{ position: "sticky", bottom: 0, display: "flex", gap: 10,
                  alignItems: "center", padding: "10px 12px", background: "var(--bg-1)",
                  border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
                  <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
                    {acceptIds.length} to accept · {dismissIds.length} to dismiss
                  </span>
                  <Button size="sm" disabled={busy} onClick={applyVerdicts} data-testid="intake-apply">
                    <Icon name="check" size={13} /> Apply verdicts
                  </Button>
                </div>
              )}

              {resolveNote && <p className="aug-fs-sm" style={{ color: "var(--grn4)", margin: 0 }}>{resolveNote}</p>}
            </>
          )}
        </div>
      </div>

      {exportText !== null && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="aug-fs-sm" style={{ display: "flex", gap: 10, alignItems: "center", color: "var(--t2)" }}>
            <span style={{ fontWeight: 600 }}>This connection&rsquo;s declared knowledge, as a bundle</span>
            <Button size="xs" variant="ghost" onClick={() => { navigator.clipboard?.writeText(exportText).catch(() => {}); }}>
              <Icon name="copy" size={12} /> Copy YAML
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setExportText(null)}>Hide</Button>
          </div>
          <pre className="aug-fs-xs" style={{ margin: 0, maxHeight: 260, overflow: "auto",
            fontFamily: "var(--font-mono)", color: "var(--t2)", background: "var(--bg-1)",
            border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: 10 }}>{exportText}</pre>
          <p className="aug-fs-xs" style={{ color: "var(--t4)", margin: 0 }}>
            Import it on another deployment and an identical re-import plans zero changes.
          </p>
        </div>
      )}

      {err && <p className="aug-fs-sm" style={{ color: "var(--red4)", margin: 0 }}>{err}</p>}
    </div>
  );
}
