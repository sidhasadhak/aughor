"use client";

/**
 * Operations ▸ Action centre — "what may the system do?" (the 2027 study §V, screen 11).
 *
 * Authority is a table, not a setting: one row per declared action on a connection, with the
 * level it may run at, the ceiling a person set, what its record has earned, and whether its
 * change can be undone. Every level cites what gave it; a demotion names the miss that caused
 * it. A person takes authority away in one gesture, with a reason — for real or as a drill —
 * caps an action below what it earned, and signs or withdraws the standing grants that let an
 * action at L4 run on one target without asking.
 *
 * What is declared and what waits on approval stay where they already are — Intelligence ▸
 * Actions — and the trail of what the gate decided stays under Security & Audit ▸ Approvals.
 * This page links to both rather than showing either a second time.
 */
import { useState } from "react";

import { getGrants, revokeGrant, type StandingGrant } from "@/lib/api";
import { countNoun } from "@/lib/format";
import { connectionLabel, keyToWords } from "@/lib/names";
import {
  demoteAction, getAuthorityRecord, getAuthorityTable, getGatewayWrites, graduateAction, setActionCeiling,
  signStandingGrant, undoExecution, whoLabel,
  type ActionExecution, type AuthorityRow, type AuthorityTable,
} from "@/lib/record";
import {
  Absent, ActorField, BackHeader, Fact, Gate, Ledger, Page, Section, day, useActor, useLoad, type LedgerColumn,
} from "@/components/record/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Row = AuthorityRow;
/** A connection as this page needs it: its id, and its name for the picker and the labels. */
type Conn = { id: string; name: string };

const LEVEL_HUE: ChipHue[] = ["muted", "muted", "info", "caution", "positive", "accent"];

function LevelChip({ level, label }: { level: number; label: string }) {
  return <StatusChip hue={LEVEL_HUE[level] ?? "muted"}>L{level} · {label}</StatusChip>;
}

export function ActionCentrePanel({ connections, selectedConn, onOpenDeclared, onOpenApprovals }: {
  /** For names. The connection itself is the workspace's — chosen in its context bar. */
  connections: Conn[];
  selectedConn: string;
  /** Intelligence ▸ Actions: each declaration, the overlay edits, and what waits on approval. */
  onOpenDeclared: () => void;
  /** Security & Audit ▸ Approvals: what the approval gate decided, and its allowlist. */
  onOpenApprovals: () => void;
}) {
  const [openAction, setOpenAction] = useState<string | null>(null);
  if (!selectedConn) {
    return <Page><Absent>Authority is held per connection: an action earns its level on the record of one. Choose a connection in the bar above.</Absent></Page>;
  }
  if (openAction) {
    return <ActionRecord actionId={openAction} connectionId={selectedConn} connections={connections} onBack={() => setOpenAction(null)} />;
  }
  return <AuthorityLedger connectionId={selectedConn} connections={connections} onOpen={setOpenAction}
    onOpenDeclared={onOpenDeclared} onOpenApprovals={onOpenApprovals} />;
}

function AuthorityLedger({ connectionId, connections, onOpen, onOpenDeclared, onOpenApprovals }: {
  connectionId: string; connections: Conn[]; onOpen: (actionId: string) => void;
  onOpenDeclared: () => void; onOpenApprovals: () => void;
}) {
  const load = useLoad<AuthorityTable | null>(
    () => getAuthorityTable(connectionId).catch(e => {
      // No ontology on this connection is a state, not a failure: nothing can be declared on it yet.
      if (e && typeof e === "object" && "status" in e && (e as { status: number }).status === 404) return null;
      throw e;
    }), [connectionId]);
  const writes = useLoad(() => getGatewayWrites(), []);
  const grants = useLoad(() => getGrants(connectionId), [connectionId]);
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
      <Section label="The authority table" meta={connectionLabel(connectionId, connections)}
        action={
          <span style={{ display: "inline-flex", gap: 4 }}>
            <Button size="xs" variant="ghost" onClick={onOpenDeclared}
              title="Each declaration, the overlay edits, and what waits on approval">Declared actions</Button>
            <Button size="xs" variant="ghost" onClick={onOpenApprovals}
              title="What the approval gate decided, and what is on its allowlist">Approval trail</Button>
          </span>
        }>
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

      <Section label="Standing grants" meta={grants.data ? countNoun(grants.data.length, "grant") : undefined}>
        <Gate load={grants} what="the standing grants">
          {gs => <GrantList grants={gs} onChanged={grants.reload} onOpen={onOpen}
            empty="No standing grant is signed on this connection, so every execution asks a person. One is signed from an action's record, once the action is at L4." />}
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

// ── standing grants ──────────────────────────────────────────────────────────────────────

/** What a grant still allows, in words. */
function grantLimits(g: StandingGrant): string {
  const uses = g.max_uses ? `${g.use_count} of ${g.max_uses} uses` : `${countNoun(g.use_count, "use")}, no cap`;
  const until = g.expires_at ? `until ${day(g.expires_at)}` : "no expiry";
  return `${uses} · ${until}`;
}

/** A person's pre-authorisations: one action on one target value, each withdrawn in one gesture. */
function GrantList({ grants, onChanged, onOpen, empty }: {
  grants: StandingGrant[]; onChanged: () => void; empty: string;
  /** On the connection's list, a grant opens its action's record. */
  onOpen?: (actionId: string) => void;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const withdraw = async (id: string) => {
    setBusy(id);
    setError("");
    try { await revokeGrant(id); onChanged(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  };
  const columns: LedgerColumn<StandingGrant>[] = [
    { head: "Allows", cell: g => `${keyToWords(g.action_id)} where ${keyToWords(g.target_arg)} is ${g.target_value}` },
    { head: "Signed by", cell: g => whoLabel(g.created_by), width: 150 },
    { head: "Signed", cell: g => day(g.created_at), width: 110 },
    { head: "Limits", cell: g => grantLimits(g), width: 230 },
    { head: "Licensed by", cell: g => (g.graduation_receipt ? "its graduation receipt" : g.owner_kind === "manual" ? "a person, when approving" : `an ${g.owner_kind}`), width: 190 },
    { head: "", cell: g => (
      <Button size="xs" variant="ghost" disabled={busy === g.id} onClick={e => { e.stopPropagation(); void withdraw(g.id); }}>Withdraw</Button>
    ), width: 100, control: true },
  ];
  return (
    <>
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "0 0 8px" }}>{error}</p>}
      <Ledger name="standing-grants" columns={columns} rows={grants} rowKey={g => g.id}
        onOpen={onOpen ? g => onOpen(g.action_id) : undefined} empty={empty} />
    </>
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
  actionId: string; connectionId: string; connections: Conn[]; onBack: () => void;
}) {
  const load = useLoad(() => getAuthorityRecord(actionId, connectionId), [actionId, connectionId]);
  const grants = useLoad(() => getGrants(connectionId).then(gs => gs.filter(g => g.action_id === actionId)), [actionId, connectionId]);
  const actor = useActor();
  const [why, setWhy] = useState("");
  const [drill, setDrill] = useState(false);
  const [capAt, setCapAt] = useState<number | null>(null);
  const [capWhy, setCapWhy] = useState("");
  const [target, setTarget] = useState("");
  const [expires, setExpires] = useState("30");
  const [maxUses, setMaxUses] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); load.reload(); grants.reload(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
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
              <Fact label="Ceiling">L{rec.ceiling}{rec.person_ceiling ? ` — set by ${whoLabel(rec.person_ceiling.by)}` : ""}</Fact>
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

              {!actor.signedIn && (
                <div style={{ marginBottom: 12 }}><ActorField actor={actor} id="ac-actor" /></div>
              )}
              <Section label="The ceiling a person set">
                <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: "0 0 8px" }}>
                  {rec.person_ceiling
                    ? `Capped at L${rec.person_ceiling.level} by ${whoLabel(rec.person_ceiling.by)} on ${day(rec.person_ceiling.at)}${rec.person_ceiling.why ? `: ${rec.person_ceiling.why}` : "."}`
                    : "No ceiling is set here. This action runs at the level its record earned, unless a mission caps it."}
                </p>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <div role="group" aria-label="Cap it at" className="aug-segmented">
                    {[0, 1, 2, 3, 4].map(l => (
                      <Button key={l} variant="ghost" size="xs" aria-pressed={capAt === l}
                        className={`aug-seg-item${capAt === l ? " active" : ""}`} onClick={() => setCapAt(l)}>L{l}</Button>
                    ))}
                  </div>
                  <Input value={capWhy} onChange={e => setCapWhy(e.target.value)} placeholder="Why (optional)" aria-label="Why it is capped" style={{ flex: "1 1 220px", maxWidth: 360 }} />
                  <Button size="xs" variant="outline" disabled={busy || capAt === null}
                    onClick={() => void act(async () => { await setActionCeiling(actionId, connectionId, capAt, capWhy.trim(), actor.by); setCapAt(null); setCapWhy(""); })}>
                    Set the ceiling
                  </Button>
                  {rec.person_ceiling && (
                    <Button size="xs" variant="ghost" disabled={busy} onClick={() => void act(() => setActionCeiling(actionId, connectionId, null, "", actor.by))}>Lift it</Button>
                  )}
                </div>
                <Absent>A ceiling only lowers. Setting it above L{rec.earned}, what the record earned, grants nothing.</Absent>
              </Section>

              <Section label="Standing grants" meta={grants.data ? countNoun(grants.data.length, "grant") : undefined}>
                <Gate load={grants} what="the standing grants">
                  {gs => <GrantList grants={gs} onChanged={() => { grants.reload(); load.reload(); }}
                    empty="No standing grant is signed for this action here, so each execution asks a person." />}
                </Gate>
                {rec.level >= 4 ? (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
                    <Input value={target} onChange={e => setTarget(e.target.value)} placeholder="The one target value it may run on" aria-label="Target value" style={{ flex: "1 1 240px", maxWidth: 320 }} />
                    <Input value={expires} onChange={e => setExpires(e.target.value)} inputMode="numeric" aria-label="Expires in days" style={{ width: 70 }} />
                    <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>days</span>
                    <Input value={maxUses} onChange={e => setMaxUses(e.target.value)} inputMode="numeric" placeholder="no cap" aria-label="Most uses" style={{ width: 90 }} />
                    <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>uses</span>
                    <Button size="xs" variant="outline" disabled={busy || !target.trim()}
                      onClick={() => void act(async () => {
                        await signStandingGrant(actionId, connectionId, { target_value: target.trim(), expires_days: Number(expires) || 0, max_uses: Number(maxUses) || 0, by: actor.by });
                        setTarget("");
                      })}>
                      Sign the grant
                    </Button>
                  </div>
                ) : (
                  <Absent>A standing grant is signed for an action at L4 — it cites the graduation receipt. This one runs at L{rec.level}.</Absent>
                )}
              </Section>

              <Section label="Take authority away">
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <div role="group" aria-label="For real or as a drill" className="aug-segmented">
                    <Button variant="ghost" size="xs" aria-pressed={!drill} className={`aug-seg-item${!drill ? " active" : ""}`} onClick={() => setDrill(false)}>For real</Button>
                    <Button variant="ghost" size="xs" aria-pressed={drill} className={`aug-seg-item${drill ? " active" : ""}`} onClick={() => setDrill(true)}>As a drill</Button>
                  </div>
                  <Input value={why} onChange={e => setWhy(e.target.value)} placeholder="Why — it is written on the demotion" aria-label="Why it is demoted" style={{ flex: "1 1 320px", maxWidth: 480 }} />
                  <Button size="xs" variant="outline" disabled={busy || !why.trim()}
                    onClick={() => void act(async () => { await demoteAction(actionId, connectionId, why.trim(), drill, actor.by); setWhy(""); })}>
                    {drill ? "Run the drill" : "Demote it"}
                  </Button>
                </div>
                <Absent>
                  A demotion withdraws every standing grant of this action on this connection. It is the same entry a failed verification books by itself.
                  {drill ? " A drill is that same demotion, marked as a drill: the action really drops to L3 and has to earn its way back." : ""}
                </Absent>
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
