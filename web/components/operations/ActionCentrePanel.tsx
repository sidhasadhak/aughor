"use client";

/**
 * Operations ▸ Action centre — "what may the system do?" (the 2027 study §V, screen 11).
 *
 * Authority is a table, not a setting: one row per declared action on a connection, with the
 * level it may run at, the ceiling a person set, what its record has earned, and whether its
 * change can be undone. Every level cites what gave it; a demotion names the miss that caused
 * it. A person takes authority away in one gesture, with a reason.
 *
 * What waits on approval and what is declared stay on the page that already resolves them
 * (declared actions and their overlay edits); the trail of what the gate decided moved here
 * from Security & Audit, so everything about authority is read in one place.
 */
import { useState } from "react";

import dynamic from "next/dynamic";

import type { Connection } from "@/lib/api";
import { countNoun } from "@/lib/format";
import { connectionLabel, keyToWords } from "@/lib/names";
import {
  demoteAction, getAuthorityRecord, getAuthorityTable, getGatewayWrites, graduateAction, undoExecution, whoLabel,
  type ActionExecution, type AuthorityRow, type AuthorityTable,
} from "@/lib/record";
import {
  Absent, BackHeader, Fact, Gate, Ledger, Page, Section, day, useLoad, type LedgerColumn,
} from "@/components/record/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loading } from "@/components/ui/states";

const DeclaredActionsPanel = dynamic(() => import("@/components/DeclaredActionsPanel").then(m => ({ default: m.DeclaredActionsPanel })),
  { ssr: false, loading: () => <Loading what="declared actions" style={{ padding: 24 }} /> });
const ActionApprovalsSection = dynamic(
  () => import("@/components/SecurityAuditPanel").then(m => ({ default: m.ActionApprovalsSection })),
  { ssr: false, loading: () => <Loading what="the approval trail" style={{ padding: 24 }} /> });

type Lens = "authority" | "declared" | "trail";

const LENSES: { id: Lens; label: string; blurb: string }[] = [
  { id: "authority", label: "Authority", blurb: "Every declared action, the level it may run at, and its record" },
  { id: "declared", label: "Waiting and declared", blurb: "What waits on approval, each declaration, and the overlay edits" },
  { id: "trail", label: "Approval trail", blurb: "What the approval gate decided, and what is on its allowlist" },
];

type Row = AuthorityRow;

const LEVEL_HUE: ChipHue[] = ["muted", "muted", "info", "caution", "positive", "accent"];

function LevelChip({ level, label }: { level: number; label: string }) {
  return <StatusChip hue={LEVEL_HUE[level] ?? "muted"}>L{level} · {label}</StatusChip>;
}

export function ActionCentrePanel({ connections, selectedConn, onSelectConnection }: {
  connections: Connection[];
  selectedConn: string;
  onSelectConnection: (id: string) => void;
}) {
  const [lens, setLens] = useState<Lens>("authority");
  const [openAction, setOpenAction] = useState<string | null>(null);
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      {openAction === null && (
        <div className="aug-toolbar">
          <div role="group" aria-label="Action centre views" className="aug-segmented">
            {LENSES.map(l => (
              <Button key={l.id} variant="ghost" size="xs" aria-pressed={lens === l.id} title={l.blurb}
                className={`aug-seg-item${lens === l.id ? " active" : ""}`} onClick={() => setLens(l.id)}>{l.label}</Button>
            ))}
          </div>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span className="aug-label">Connection</span>
            <select value={selectedConn} onChange={e => onSelectConnection(e.target.value)} aria-label="Connection"
              className="aug-fs-sm"
              style={{ color: "var(--t2)", background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: "3px 8px", maxWidth: 220 }}>
              {!selectedConn && <option value="">Choose a connection</option>}
              {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        </div>
      )}
      {!selectedConn ? (
        <Page><Absent>Authority is held per connection: an action earns its level on the record of one. Choose a connection above.</Absent></Page>
      ) : lens === "authority" ? (
        openAction
          ? <ActionRecord actionId={openAction} connectionId={selectedConn} connections={connections} onBack={() => setOpenAction(null)} />
          : <AuthorityLedger connectionId={selectedConn} connections={connections} onOpen={setOpenAction} />
      ) : lens === "declared" ? (
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}><DeclaredActionsPanel connectionId={selectedConn} /></div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px 20px" }}><ActionApprovalsSection /></div>
      )}
    </div>
  );
}

function AuthorityLedger({ connectionId, connections, onOpen }: {
  connectionId: string; connections: Connection[]; onOpen: (actionId: string) => void;
}) {
  const load = useLoad<AuthorityTable | null>(
    () => getAuthorityTable(connectionId).catch(e => {
      // No ontology on this connection is a state, not a failure: nothing can be declared on it yet.
      if (e && typeof e === "object" && "status" in e && (e as { status: number }).status === 404) return null;
      throw e;
    }), [connectionId]);
  const writes = useLoad(() => getGatewayWrites(), []);
  const columns: LedgerColumn<Row>[] = [
    { head: "Action", cell: r => keyToWords(r.action_id) },
    { head: "May run at", cell: r => <LevelChip level={r.level} label={r.label} />, width: 230 },
    { head: "Ceiling", cell: r => `L${r.ceiling}`, width: 80 },
    { head: "Record earned", cell: r => `L${r.earned}`, width: 120 },
    { head: "Verified", cell: r => (r.record.executions ? `${r.record.verified} of ${r.record.executions}` : "never run"), num: true, width: 110 },
    { head: "Last run", cell: r => (r.record.last_run ? day(r.record.last_run) : "—"), width: 110 },
    { head: "Can it be undone", cell: r => (r.undo_declared ? "yes, an undo is declared" : r.reversibility === "irreversible" ? "no — declared irreversible" : keyToWords(r.reversibility)), width: 220 },
    { head: "Demoted", cell: r => (r.demotion ? <StatusChip hue="negative">demoted</StatusChip> : "—"), width: 100 },
  ];
  return (
    <Page wide>
      <Section label="The authority table" meta={connectionLabel(connectionId, connections)}>
        <Gate load={load} what="the authority table">
          {t => t === null ? (
            <Absent>No object model is built for this connection yet, so no action can be declared on it. Actions are declared on the model, each with the read that verifies it and how it is undone.</Absent>
          ) : (
            <>
              <Ledger name="authority" columns={columns} rows={t.actions} rowKey={r => r.action_id} onOpen={r => onOpen(r.action_id)}
                empty="No action is declared on this connection. A declared action names its verification read and its undo; until then nothing here can change anything outside the platform." />
              <Absent>{t.note}. Graduating to L4 takes {t.graduation_n} approved executions whose verification passed.</Absent>
            </>
          )}
        </Gate>
      </Section>

      <Section label="Demotions">
        <Gate load={load} what="demotions">
          {t => {
            const demoted = (t?.actions ?? []).filter(r => r.demotion);
            return demoted.length === 0
              ? <Absent>No action has been demoted on this connection. A failed verification demotes its action by itself and withdraws its standing grants; a person can do the same with a reason.</Absent>
              : <>{demoted.map(r => (
                <div className="aug-item" key={r.action_id}>
                  <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{keyToWords(r.action_id)}</div>
                  <div className="aug-item-foot aug-fs-sm">
                    <span>{r.why.split("; demoted").slice(1).map(x => `demoted${x}`).join("; ") || r.why}</span>
                    <span style={{ flex: 1 }} />
                    <Button size="xs" variant="ghost" onClick={() => onOpen(r.action_id)}>Open its record</Button>
                  </div>
                </div>
              ))}</>;
          }}
        </Gate>
      </Section>

      <Section label="Writes through other doors" meta={writes.data ? countNoun(writes.data.count, "write") : undefined}>
        <Gate load={writes} what="the gateway's writes">
          {w => w.writes.length === 0 ? <Absent>{w.note}. None is on the record.</Absent> : (
            <>
              {w.writes.slice(0, 20).map((x, i) => (
                <div className="aug-item" key={String(x.id ?? i)}>
                  <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{keyToWords(String(x.action_id ?? "a write"))}</div>
                  <div className="aug-item-foot aug-fs-sm">
                    <span>through {String(x.door ?? "a door")}</span><span>{String(x.status ?? "")}</span>
                    <span>by {whoLabel(String(x.actor ?? ""))}</span><span>{day(String(x.at ?? x.recorded_at ?? ""))}</span>
                  </div>
                </div>
              ))}
              <Absent>{w.note}.</Absent>
            </>
          )}
        </Gate>
      </Section>
    </Page>
  );
}

// ── one action's record ──────────────────────────────────────────────────────────────────

/** A rule as the ladder states it, without the module path or plan clause it cites for a developer. */
function plainRule(text: string): string {
  return text.replace(/\s*\((?:[a-z_]+\/)+[a-z_]+\)/g, "").replace(/\s+—\s+phase \d+'s exit.*$/, "");
}

const VERIFY_HUE: Record<string, ChipHue> = { passed: "positive", failed: "negative", unavailable: "caution", not_declared: "muted" };
const VERIFY_WORDS: Record<string, string> = {
  passed: "verified", failed: "verification failed", unavailable: "verification could not run", not_declared: "no verification declared",
};

function ActionRecord({ actionId, connectionId, connections, onBack }: {
  actionId: string; connectionId: string; connections: Connection[]; onBack: () => void;
}) {
  const load = useLoad(() => getAuthorityRecord(actionId, connectionId), [actionId, connectionId]);
  const [why, setWhy] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); load.reload(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const r = load.data;
  return (
    <>
      <BackHeader from="Authority" onBack={onBack} title={keyToWords(actionId)}
        chips={r && <LevelChip level={r.level} label={r.label} />} />
      <Gate load={load} what="the action's record">
        {rec => {
          const check = rec.graduation_check;
          const rail = (
            <>
              <div className="aug-rail-head"><span className="aug-label">This action</span></div>
              <Fact label="On">{connectionLabel(connectionId, connections)}</Fact>
              <Fact label="May run at">L{rec.level} · {rec.label}</Fact>
              <Fact label="Ceiling">L{rec.ceiling}</Fact>
              <Fact label="Record earned">L{rec.earned}</Fact>
              <Fact label="Executions">{rec.record.executions}</Fact>
              <Fact label="Verified">{rec.record.verified}</Fact>
              <Fact label="Failed checks">{rec.record.failed_verifications}</Fact>
              <Fact label="Undone">{rec.record.undone}</Fact>
            </>
          );
          return (
            <Page rail={rail}>
              {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "0 0 12px" }}>{error}</p>}
              <Section label="Why it runs at this level">
                <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: "0 0 6px" }}>{plainRule(rec.why)}</p>
                {rec.notes.map(n => <Absent key={n}>{plainRule(n)}</Absent>)}
              </Section>

              <Section label="What the next level needs"
                action={check.can_graduate && (
                  <Button size="xs" disabled={busy} onClick={() => void act(() => graduateAction(actionId, connectionId))}>
                    Book the graduation
                  </Button>
                )}>
                {check.can_graduate
                  ? <Absent>The record earns L4. Booking the graduation writes the receipt that grants it.</Absent>
                  : check.reasons.map(x => <div className="aug-item aug-fs-ui" key={x} style={{ color: "var(--t1)" }}>{plainRule(x)}</div>)}
              </Section>

              <Section label="Executions" meta={countNoun(rec.executions.length, "execution")}>
                {rec.executions.length === 0 ? <Absent>It has never run on this connection.</Absent>
                  : rec.executions.map(x => <Execution key={x.id} x={x} busy={busy}
                      onUndo={() => void act(() => undoExecution(actionId, String(x.id), connectionId))} />)}
              </Section>

              <Section label="Take authority away">
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Input value={why} onChange={e => setWhy(e.target.value)} placeholder="Why — it is written on the demotion" aria-label="Why it is demoted" style={{ flex: "1 1 320px", maxWidth: 480 }} />
                  <Button size="xs" variant="outline" disabled={busy || !why.trim()}
                    onClick={() => void act(async () => { await demoteAction(actionId, connectionId, why.trim()); setWhy(""); })}>
                    Demote it
                  </Button>
                </div>
                <Absent>A demotion withdraws every standing grant of this action on this connection. It is the same entry a failed verification books by itself.</Absent>
              </Section>
            </Page>
          );
        }}
      </Gate>
    </>
  );
}

/** Whether an execution's undo can still be fired, from its declared window. */
function undoState(x: ActionExecution): { open: boolean; words: string } {
  const undo = x.undo;
  if (!undo) return { open: false, words: "no undo is declared for this action" };
  const hours = Number(undo.window_hours ?? 0);
  const at = Date.parse(String(x.at ?? ""));
  if (hours <= 0) return { open: true, words: "it can be undone at any time" };
  if (Number.isNaN(at)) return { open: false, words: "its time is not recorded, so its undo window cannot be read" };
  const closes = new Date(at + hours * 3_600_000);
  return Date.now() <= closes.getTime()
    ? { open: true, words: `it can be undone until ${closes.toISOString().slice(0, 16).replace("T", " ")} UTC` }
    : { open: false, words: `its ${hours}-hour undo window closed on ${closes.toISOString().slice(0, 10)}` };
}

function Execution({ x, busy, onUndo }: { x: ActionExecution; busy: boolean; onUndo: () => void }) {
  const status = x.verification?.status ?? "not_declared";
  const undo = undoState(x);
  const params = Object.entries(x.params ?? {}).map(([k, v]) => `${keyToWords(k)} ${String(v)}`).join(" · ");
  const undone = typeof x.undone_by === "string" && x.undone_by;
  return (
    <div className="aug-item">
      <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{params || "no parameters"}</span>
        <StatusChip hue={VERIFY_HUE[status] ?? "muted"}>{VERIFY_WORDS[status] ?? status}</StatusChip>
        {undone && <StatusChip hue="muted">undone</StatusChip>}
      </div>
      <div className="aug-item-foot aug-fs-sm">
        {x.verification?.why && <span>{x.verification.why}</span>}
        <span>by {whoLabel(String(x.actor ?? ""))} under {String(x.under ?? "the gate")}</span>
        <span>{String(x.at ?? "").slice(0, 16).replace("T", " ")}</span>
        <span>{undone ? "its undo has run" : undo.words}</span>
        <span style={{ flex: 1 }} />
        {undo.open && !undone && (
          <Button size="xs" variant="outline" disabled={busy} onClick={onUndo}
            title="Runs the declared undo of this execution through the same approval gate">Run the undo</Button>
        )}
      </div>
    </div>
  );
}
