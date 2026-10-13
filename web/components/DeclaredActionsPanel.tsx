"use client";

/**
 * Actions — what Aughor may do on a connection (the Intelligence workspace's Actions tab), laid out to CLARITY
 * (`aughor-v2/CLARITY.md`) as the ledger it is. The declared actions come first, read like a document: each one's name
 * and what it does in a line, what it changes as one muted line of facts, and its gate as a chip whose title is the rule.
 * Beside them, in amber, what waits for a person: the approvals, and an outbox call no retry will deliver. Then the edit
 * layer — the values actions and people set over the data, by the object they sit on, each withdrawable — and the calls
 * the actions made to other systems.
 *
 * It was numbered sections beside a rail: three tables, two forms open on a reading view and the permission model in
 * prose. The forms open when asked for (New action · Propose from a finding · Annotate a value), and the permission model
 * is the title of each gate.
 *
 * Proposals are staged, never run from here: proposing writes each valid one to the approvals, where it waits until a
 * person approves it — which runs it exactly once — or rejects it. (This panel once executed a proposal directly and
 * left its staged row pending, so the same side effect could later be approved and run a second time.)
 *
 * Drawn only from stored data. Left out because nothing keeps them: an action's runs in the last 30 days, an edit's
 * previous value, a dry run, a "disabled" gate.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";

import { CARD, Chip, Empty, Label, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import { ActionDesigner } from "@/components/ontology/ActionDesigner";
import { humanName } from "@/components/ontology/TypeOverview";
import { ProposalCard } from "@/components/ProposalCard";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { getProposals, type StagedProposal } from "@/lib/api";
import { claimsOf, getIdToken } from "@/lib/auth";
import { getApiBase } from "@/lib/config";
import { countNoun, formatCount, formatTimestamp, relTime } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { byWho, keyToWords } from "@/lib/names";
import { dismissSend, getSends, retrySend, type ActionSend } from "@/lib/objects";
import { useMe } from "@/lib/useMe";

// ── Reading ──────────────────────────────────────────────────────────────────────

/** A refused read, with its HTTP status: a 404 on the declared actions means the connection has no ontology yet. */
class Refused extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

/** The server's own words for a refusal — its `detail`, not the JSON around it. */
function detailOf(text: string): string {
  try {
    const d = JSON.parse(text)?.detail;
    if (typeof d === "string") return d;
    if (d && typeof d.message === "string") return d.message;
  } catch { /* not JSON: the text is the words */ }
  return text;
}

async function apiFetch(path: string, opts?: RequestInit) {
  const res = await fetch(`${getApiBase()}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Refused(res.status, detailOf(text) || `HTTP ${res.status}`);
  }
  return res.json();
}
const post = (p: string, b: unknown) => apiFetch(p, { method: "POST", body: JSON.stringify(b) });
const said = (e: unknown) => String((e as Error)?.message || e);
const on = (c: string) => `connection_id=${encodeURIComponent(c)}`;

/** The edit layer's one route (the frozen wire path keeps its old name). */
const EDITS = "/kinetic-actions/annotations";

interface Param { name: string; display_name?: string; data_type?: string; kind?: string; object_type?: string; required?: boolean }
interface ObjectEdit { object: string; property: string; value?: string }
interface SideEffect { kind: string; lane?: string; config?: Record<string, unknown> }
/** A declared action, as the ontology's declared-actions read answers it (secrets masked). */
interface Declared {
  id: string;
  display_name?: string;
  description?: string;
  kind?: string;
  risk?: string;
  object_type?: string;
  creates?: string;
  params?: Param[];
  edits?: ObjectEdit[];
  side_effects?: SideEffect[];
  submission_criteria?: { expr: string }[];
  verification?: { sql?: string } | null;
  reversibility?: string;
  undo?: { action_id?: string; window_hours?: number } | null;
}
/** One value in the edit layer, as `GET …/annotations` answers it. */
interface LayerEdit {
  id: string;
  table: string;
  column?: string;
  key_column?: string;
  row_key?: string;
  kind?: string;
  body: string;
  source?: string;
  actor?: string;
  origin?: string;
  note?: string;
  object_type?: string;
  version?: number;
  created_at?: string;
}

const readActions = (c: string) => apiFetch(`/ontology/kinetic-actions?${on(c)}`).then(r => Object.values(r ?? {}) as Declared[]);
const readEdits = (c: string) => apiFetch(`${EDITS}?${on(c)}`).then(r => (r?.edits ?? []) as LayerEdit[]);
const readPending = (c: string) => getProposals(c, "pending");
const readOutbox = (c: string) => getSends(c).then(r => ({ enabled: !!r?.enabled, sends: r?.sends ?? [] }));

interface Read<T> { data: T | null; error: string | null; status: number; reload: () => void }

/** One read of this connection: its answer, or why it failed — never an empty list for a failed read. What another
 *  connection answered is not this one's, so a switch reads as loading until this connection answers. */
function useRead<T>(connectionId: string, read: (c: string) => Promise<T>): Read<T> {
  const [got, setGot] = useState<{ conn: string; data: T | null; error: string | null; status: number } | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    read(connectionId)
      .then(data => { if (alive) setGot({ conn: connectionId, data, error: null, status: 200 }); })
      .catch(e => {
        if (!alive) return;
        setGot(prev => ({ conn: connectionId, data: prev?.conn === connectionId ? prev.data : null, error: said(e),
          status: e instanceof Refused ? e.status : 0 }));
      });
    return () => { alive = false; };
  }, [connectionId, read, tick]);
  const reload = useCallback(() => setTick(t => t + 1), []);
  const mine = got?.conn === connectionId ? got : null;
  return { data: mine?.data ?? null, error: mine?.error ?? null, status: mine?.status ?? 0, reload };
}

/** Who is acting — the signed-in email, else the word the approvals use. Provenance, not auth. */
const actorName = () => claimsOf(getIdToken())?.email || "human";

// ── Words ────────────────────────────────────────────────────────────────────────

const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };
const SUB: React.CSSProperties = { color: "var(--t2)", marginTop: -4, marginBottom: 6 };
const ERR: React.CSSProperties = { color: "var(--red4)", margin: "4px 0" };

/** The gate an action's risk puts on it, as `govern/actions.py` enforces it — the permission model, one rule per title.
 *  An action declares no risk only before it is classified, and the server reads that as high. */
const GATE: Record<string, { label: string; ask: boolean; title: string }> = {
  read_only: { label: "runs, audited", ask: false, title: "Reads only: never gated, and every run is audited" },
  low: { label: "runs, audited", ask: false, title: "Low risk — reversible or additive: runs without asking, and every run is audited" },
  high: { label: "needs approval", ask: true,
    title: "High risk: a person approves each run. Approving a staged proposal is that approval, once; a standing grant can pre-approve one target" },
};

/** Nodes joined by ", " — the values one action sets, said in one breath. */
function joined(nodes: React.ReactNode[]): React.ReactNode {
  return nodes.map((n, i) => <React.Fragment key={i}>{i ? ", " : ""}{n}</React.Fragment>);
}

const setNode = (e: ObjectEdit) => <><span style={MONO}>{e.property}</span>{e.value ? ` = ${e.value}` : ""}</>;

/** What an action does, as facts: what it is about, what it makes and sets, the calls it makes, what it takes, what it
 *  must satisfy, how it is checked and undone. Long text (a URL, a read's SQL, a parameter's type) is in the title. */
function actionFacts(a: Declared, nameOf: (id: string) => string): { key: string; node: React.ReactNode; title?: string }[] {
  const out: { key: string; node: React.ReactNode; title?: string }[] = [];
  if (a.object_type) out.push({ key: "on", node: <>on {humanName(a.object_type)}</> });
  const edits = a.edits ?? [];
  const made = edits.filter(e => e.object === "created" && a.creates);
  const sets = edits.filter(e => !(e.object === "created" && a.creates));
  if (a.creates) {
    out.push({ key: "creates", title: "A new object the platform keeps; its values sit in the edit layer",
      node: <>creates a {humanName(a.creates)}{made.length ? <> with {joined(made.map(setNode))}</> : null}</> });
  }
  if (sets.length) out.push({ key: "sets", title: "Set in the edit layer — never written to the source", node: <>sets {joined(sets.map(setNode))}</> });
  (a.side_effects ?? []).forEach((se, i) => {
    const url = String(se.config?.url ?? "");
    const method = String(se.config?.method ?? "POST");
    let host = url;
    try { host = url ? new URL(url).host : ""; } catch { /* not a URL: say it as written */ }
    out.push({ key: `call${i}`, title: se.kind === "http" ? `${method} ${url}` : undefined,
      node: se.kind === "http"
        ? <>calls {method} {host}{se.config?.auth_secret ? " · key set" : ""}{se.lane === "writeback" ? " · its edits wait on it" : ""}</>
        : <>{keyToWords(se.kind)}</> });
  });
  const params = a.params ?? [];
  if (params.length) {
    out.push({ key: "takes", node: <>takes {params.map(p => p.display_name || p.name).join(", ")}</>,
      title: params.map(p => `${p.name}: ${p.kind === "object" ? p.object_type : p.data_type}${p.required === false ? " (optional)" : ""}`).join(" · ") });
  }
  (a.submission_criteria ?? []).forEach((c, i) => out.push({ key: `must${i}`, node: <>must satisfy <span style={MONO}>{c.expr}</span></> }));
  if (a.verification?.sql) out.push({ key: "verified", node: <>checked by a read</>, title: a.verification.sql });
  if (a.undo?.action_id) {
    const hours = Number(a.undo.window_hours) || 0;
    out.push({ key: "undo", node: <>undone by {nameOf(a.undo.action_id)}{hours > 0 ? ` within ${hours} h` : ""}</> });
  }
  if (!a.creates && !edits.length && !(a.side_effects ?? []).length) {
    out.push({ key: "kind", node: <>{a.kind === "query" ? "reads only" : a.kind === "side_effect" ? "has a side effect" : "annotates"}</> });
  }
  return out;
}

const SEND_WORDS: Record<ActionSend["status"], string> = {
  queued: "waiting to be sent again", sending: "being sent", delivered: "delivered",
  unknown: "no answer — being checked", dead: "could not be delivered", dismissed: "left undelivered",
};
/** A call waits for a person when no retry will deliver it, or when no answer came back. */
const waits = (s: ActionSend) => s.status === "dead" || s.status === "unknown";
/** The calls listed below the approvals: the newest this many. */
const CALLS_SHOWN = 20;

// ── The page ─────────────────────────────────────────────────────────────────────

export function DeclaredActionsPanel({ connectionId }: { connectionId: string }) {
  const actions = useRead(connectionId, readActions);
  const edits = useRead(connectionId, readEdits);
  const pending = useRead<StagedProposal[]>(connectionId, readPending);
  const outbox = useRead(connectionId, readOutbox);
  const [designing, setDesigning] = useState(false);
  const [proposing, setProposing] = useState(false);

  const names = useMemo(() => new Map((actions.data ?? []).map(a => [a.id, a.display_name || humanName(a.id)])), [actions.data]);
  const nameOf = useCallback((id: string) => names.get(id) ?? humanName(id), [names]);

  if (!connectionId) {
    return <Page testId="actions-page"><section style={CARD}><Empty>Choose a connection to see what Aughor may do on it.</Empty></section></Page>;
  }

  return (
    <Page testId="actions-page">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-start" }}>
        <section aria-label="Declared actions" data-testid="actions-ledger" style={{ ...CARD, flex: "999 1 560px" }}>
          <Label right={<>
            <Button variant="ghost" size="xs" aria-expanded={proposing} onClick={() => setProposing(p => !p)}
              title="Paste a finding; the agent stages any declared action it warrants for a person to approve">
              Propose from a finding
            </Button>
            {!designing && (
              <Button variant="outline" size="xs" data-testid="actions-new" onClick={() => setDesigning(true)}>
                <Icon name="plus" size={12} /> New action
              </Button>
            )}
          </>}>
            Declared actions{actions.data && <span style={{ ...NUM, color: "var(--t2)" }}>{formatCount(actions.data.length)}</span>}
          </Label>
          <div className="aug-fs-sm" style={SUB}>What Aughor may do on this connection, and which runs a person approves first.</div>
          <Ledger read={actions} nameOf={nameOf} />
          {proposing && <ProposeForm connectionId={connectionId} nameOf={nameOf} onClose={() => setProposing(false)} onStaged={pending.reload} />}
          {designing && (
            <div style={{ display: "flex", border: "1px solid var(--b1)", borderRadius: "var(--r3)", marginTop: 10 }}>
              <ActionDesigner connectionId={connectionId} within=""
                onClose={() => { setDesigning(false); actions.reload(); }} onDeclared={() => actions.reload()} />
            </div>
          )}
        </section>

        <div style={{ flex: "1 1 320px", minWidth: 0 }}>
          <Waiting connectionId={connectionId} pending={pending} outbox={outbox}
            onResolved={(t, m) => {
              if (t === "ok") { toast.info(m); edits.reload(); }
              pending.reload();
            }} />
        </div>
      </div>

      <EditLayer connectionId={connectionId} read={edits} nameOf={nameOf} />
      <Calls read={outbox} />
    </Page>
  );
}

// ── The ledger ───────────────────────────────────────────────────────────────────

function Ledger({ read, nameOf }: { read: Read<Declared[]>; nameOf: (id: string) => string }) {
  if (read.data === null) {
    if (read.status === 404) return <Empty title={read.error ?? undefined}>No ontology is built on this connection yet — an action is declared on one.</Empty>;
    if (read.error) return <ReadFailed what="the declared actions" error={read.error} onRetry={read.reload} />;
    return <Loading what="the declared actions" />;
  }
  return (
    <>
      {read.error && <RefreshFailed error={read.error} onRetry={read.reload} />}
      {read.data.length === 0
        ? <Empty>No action is declared yet.</Empty>
        : read.data.map((a, i) => <ActionRow key={a.id} a={a} first={i === 0} nameOf={nameOf} />)}
    </>
  );
}

function ActionRow({ a, first, nameOf }: { a: Declared; first: boolean; nameOf: (id: string) => string }) {
  const gate = GATE[a.risk || "high"];
  const facts = actionFacts(a, nameOf);
  return (
    <div data-testid="action-row" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12,
      alignItems: "start", padding: "8px 0", ...(first ? {} : RULE) }}>
      <div style={{ minWidth: 0 }}>
        <div className="aug-fs-chrome" style={{ color: "var(--t2)", lineHeight: 1.5 }}>
          <span title={a.id} style={{ color: "var(--t1)", fontWeight: 600 }}>{a.display_name || humanName(a.id)}</span>
          {a.description && <span style={{ marginLeft: 8 }}>{a.description}</span>}
        </div>
        {facts.length > 0 && (
          <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 2, lineHeight: 1.6, overflowWrap: "anywhere" }}>
            {facts.map((f, i) => <span key={f.key} title={f.title}>{i ? " · " : ""}{f.node}</span>)}
          </div>
        )}
      </div>
      <span style={{ ...ROW, flexWrap: "nowrap", gap: 6 }}>
        {a.reversibility === "irreversible" && (
          <Chip tone="down" title="Declared irreversible: no undo can take it back">irreversible</Chip>
        )}
        <Chip tone={gate?.ask ? "amber" : "plain"} title={gate?.title}>{gate ? gate.label : String(a.risk)}</Chip>
      </span>
    </div>
  );
}

/** A refresh that failed while an earlier answer is on screen: said, beside the answer it did not replace. */
function RefreshFailed({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="aug-fs-xs" style={{ ...ROW, marginBottom: 6 }}>
      <Chip tone="amber" title={error}>not refreshed — showing the last read</Chip>
      <Button variant="link" size="xs" onClick={onRetry}>Retry</Button>
    </div>
  );
}

// ── Proposing from a finding ─────────────────────────────────────────────────────

interface Proposed { action_id: string; inbox_id?: string; status?: string; ok?: boolean; message?: string;
  reasoning?: string; params?: Record<string, unknown> }

function ProposeForm({ connectionId, nameOf, onClose, onStaged }: {
  connectionId: string; nameOf: (id: string) => string; onClose: () => void; onStaged: () => void;
}) {
  const [context, setContext] = useState("");
  const [proposals, setProposals] = useState<Proposed[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const propose = async () => {
    setBusy(true); setErr(null); setProposals(null);
    try {
      const r = await post(`/kinetic-actions/propose?${on(connectionId)}`, { context });
      setProposals(r.proposals || []);
      onStaged();   // every valid proposal is now in the approvals: Needs you shows it
    } catch (e) { setErr(said(e)); }
    finally { setBusy(false); }
  };

  return (
    <div data-testid="actions-propose" style={{ ...RULE, marginTop: 6, paddingTop: 10 }}>
      <div className="aug-fs-sm" style={{ ...ROW, color: "var(--t2)", marginBottom: 6 }}>
        <span>The agent stages any declared action the finding warrants; nothing runs until a person approves it.</span>
        <Chip title="Proposing asks the model once">1 model call</Chip>
      </div>
      {err && <div className="aug-fs-sm" role="alert" style={ERR}>{err}</div>}
      <Textarea aria-label="A finding" style={{ minHeight: 72 }} value={context} onChange={e => setContext(e.target.value)}
        placeholder="e.g. Order X9001 was charged EUR 480 twice — a clear duplicate charge." />
      <div style={{ ...ROW, marginTop: 6 }}>
        <Button variant="secondary" size="xs" disabled={busy || !context.trim()} onClick={propose}>
          {busy ? "Proposing…" : "Propose actions"}
        </Button>
        <Button variant="ghost" size="xs" onClick={onClose}>Close</Button>
      </div>
      {proposals && proposals.length === 0 && <Empty>The agent abstained — nothing to propose.</Empty>}
      {proposals && proposals.length > 0 && withUniqueKeys(proposals, p => p.inbox_id || p.action_id).map(([key, p]) => (
        <div key={key} className="aug-fs-sm" style={{ ...RULE, padding: "6px 0", marginTop: 6 }}>
          <div style={ROW}>
            <span style={{ color: "var(--t1)", fontWeight: 600 }}>{nameOf(p.action_id)}</span>
            <span style={MUTED}>{p.inbox_id ? "staged — waits for approval" : String(p.status ?? "")}</span>
          </div>
          {p.reasoning && <div style={{ color: "var(--t2)" }}>{p.reasoning}</div>}
          <div className="aug-fs-xs" style={{ ...MUTED, ...MONO, overflowWrap: "anywhere" }}>
            {Object.entries(p.params ?? {}).map(([k, v]) => `${k}: ${String(v)}`).join(" · ") || "no parameters"}
          </div>
          {!p.ok && p.message && <div role="alert" style={ERR}>{p.message}</div>}
        </div>
      ))}
    </div>
  );
}

// ── What waits for a person ──────────────────────────────────────────────────────

function Waiting({ connectionId, pending, outbox, onResolved }: {
  connectionId: string;
  pending: Read<StagedProposal[]>;
  outbox: Read<{ enabled: boolean; sends: ActionSend[] }>;
  onResolved: (t: "ok" | "err", message: string) => void;
}) {
  const [busy, setBusy] = useState("");
  // the call a person is leaving undelivered, and why — asked on the row, never in a native prompt (an embedded
  // browser refuses `window.prompt`, and the button then did nothing; 2026-10-10)
  const [leaving, setLeaving] = useState<{ id: string; why: string } | null>(null);
  const calls = (outbox.data?.sends ?? []).filter(waits);
  const approvals = pending.data ?? [];
  const count = calls.length + approvals.length;

  const act = async (s: ActionSend, what: "retry" | "dismiss", why = "") => {
    setBusy(s.id);
    try {
      if (what === "retry") await retrySend(connectionId, s.id);
      else await dismissSend(connectionId, s.id, why);
      setLeaving(null);
      outbox.reload();
    } catch (e) {
      toast.error(what === "retry" ? "Not sent" : "Not dismissed", { description: said(e).slice(0, 240) });
    } finally { setBusy(""); }
  };

  return (
    <NeedsYou testId="actions-needs" waiting={count > 0} right={count > 0 ? [
      approvals.length ? countNoun(approvals.length, "approval") : "",
      calls.length ? countNoun(calls.length, "call") : "",
    ].filter(Boolean).join(" · ") : undefined}>
      {calls.map(s => (
        <React.Fragment key={s.id}>
          <NeedsRow testId="send-row"
            title={<>{s.action_name}<span className="aug-fs-xs" style={{ ...MUTED, fontWeight: 400 }}>{s.attempts ? ` · ${countNoun(s.attempts, "attempt")}` : ""}</span></>}
            detail={<span title={[SEND_WORDS[s.status], s.last_error].filter(Boolean).join(" — ")}>{s.last_error || SEND_WORDS[s.status]}</span>}
            actions={<>
              <Button size="xs" variant="secondary" disabled={!!busy} data-testid="send-retry" onClick={() => void act(s, "retry")}>
                Retry
              </Button>
              <Button size="xs" variant="ghost" disabled={!!busy} data-testid="send-dismiss" onClick={() => setLeaving({ id: s.id, why: "" })}>
                Dismiss
              </Button>
            </>} />
          {leaving?.id === s.id && (
            <div data-testid="send-dismiss-form" style={{ ...ROW, flexWrap: "nowrap", margin: "0 0 6px" }}>
              <Input value={leaving.why} aria-label="Why it is left undelivered" placeholder="Why is it left undelivered?"
                style={{ flex: 1 }} onChange={e => setLeaving({ id: s.id, why: e.target.value })} />
              <Button size="xs" variant="outline" disabled={!!busy || !leaving.why.trim()} data-testid="send-dismiss-confirm"
                onClick={() => void act(s, "dismiss", leaving.why.trim())}>
                Leave it undelivered
              </Button>
              <Button size="xs" variant="ghost" onClick={() => setLeaving(null)}>Cancel</Button>
            </div>
          )}
        </React.Fragment>
      ))}
      {pending.data === null
        ? (pending.error ? <ReadFailed what="the approvals" error={pending.error} onRetry={pending.reload} /> : <Loading what="the approvals" />)
        : approvals.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: calls.length ? 8 : 0 }}>
            {/* SP-9 — the ONE approval card; what either click creates, never raw params. */}
            {approvals.map(p => <ProposalCard key={p.id} proposal={p} actor={actorName()} onResolved={onResolved} />)}
          </div>
        )}
      {pending.data !== null && pending.error && <RefreshFailed error={pending.error} onRetry={pending.reload} />}
      {pending.data !== null && count === 0 && (
        <Empty title="A proposal lands here when the agent or an automation stages one, and approving it runs it once; an outbox call no retry will deliver waits here too">
          Nothing waits for you.
        </Empty>
      )}
    </NeedsYou>
  );
}

// ── The edit layer ───────────────────────────────────────────────────────────────

/** The values set on one object (or on a column or table, when no row is named), newest first. */
interface EditGroup { key: string; entity: string; rowKey: string; where: string; newest: string; edits: LayerEdit[] }

function groupEdits(edits: readonly LayerEdit[]): EditGroup[] {
  const groups = new Map<string, EditGroup>();
  for (const e of edits) {
    const key = `${e.table}|${e.key_column ?? ""}|${e.row_key ?? ""}`;
    const g = groups.get(key) ?? {
      key, entity: humanName(e.object_type || e.table), rowKey: e.row_key ?? "",
      where: `${e.table}${e.row_key ? ` · ${e.key_column || "key"} = ${e.row_key}` : ""}`, newest: "", edits: [],
    };
    g.edits.push(e);
    if ((e.created_at ?? "") > g.newest) g.newest = e.created_at ?? "";
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => b.newest.localeCompare(a.newest));
}

/** What an edit sets, in the reader's words: a property's name, or a note on one. */
function editLabel(e: LayerEdit): string {
  const col = e.column ? humanName(e.column) : "";
  if (e.kind === "property") return col || "Value";
  if (e.kind === "correction") return col ? `Corrected ${col.toLowerCase()}` : "Correction";
  return col ? `Note on ${col.toLowerCase()}` : "Note";
}

function EditLayer({ connectionId, read, nameOf }: { connectionId: string; read: Read<LayerEdit[]>; nameOf: (id: string) => string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [annotating, setAnnotating] = useState(false);
  const list = read.data;
  const groups = useMemo(() => groupEdits(list ?? []), [list]);
  // Said once: one person behind every edit is named in the label, not on each line.
  const me = useMe();
  const who = (e: LayerEdit) => byWho(e.actor || e.source || "", me?.actor);
  const people = [...new Set((list ?? []).map(who).filter(Boolean))];
  const shared = people.length === 1 ? people[0] : "";

  // ON-4 — one edit, unsaid. The connection-wide purge was the only way back before this.
  const withdraw = async (id: string) => {
    setFailed(null); setBusy(id);
    try {
      await apiFetch(`${EDITS}/${encodeURIComponent(id)}?${on(connectionId)}`, { method: "DELETE" });
      read.reload();
    } catch (e) { setFailed(said(e)); }
    finally { setBusy(null); }
  };

  return (
    <section aria-label="Edit layer" data-testid="actions-edits" style={CARD}>
      <Label right={<>
        {shared && <span>all by {shared}</span>}
        <Button variant="ghost" size="xs" aria-expanded={annotating} onClick={() => setAnnotating(a => !a)}>Annotate a value</Button>
      </>}>
        Edit layer{list && <span style={{ ...NUM, color: "var(--t2)" }}>{formatCount(list.length)}</span>}
      </Label>
      <div className="aug-fs-sm" style={SUB}>Values set over the data by an action or a person — merged when read, never written to the source.</div>
      {annotating && <AnnotateForm connectionId={connectionId} onClose={() => setAnnotating(false)} onSaved={read.reload} />}
      {failed && <div className="aug-fs-sm" role="alert" style={ERR}>Not withdrawn — {failed}</div>}
      {list === null
        ? (read.error ? <ReadFailed what="the edit layer" error={read.error} onRetry={read.reload} /> : <Loading what="the edit layer" />)
        : <>
          {read.error && <RefreshFailed error={read.error} onRetry={read.reload} />}
          {list.length === 0 ? <Empty>Nothing is set over the data yet.</Empty> : groups.map((g, i) => (
            <div key={g.key} data-testid="edit-group" style={{ padding: "6px 0", ...(i ? RULE : {}) }}>
              <div className="aug-fs-chrome" style={{ ...ROW, gap: 6 }} title={g.where}>
                <span style={{ color: "var(--t1)", fontWeight: 600 }}>{g.entity}</span>
                {g.rowKey
                  ? <span className="aug-fs-xs" style={{ ...MONO, color: "var(--t2)" }}>{g.rowKey}</span>
                  : <span className="aug-fs-xs" style={MUTED}>{g.edits.some(e => e.column) ? "every row" : "the whole table"}</span>}
              </div>
              {g.edits.map(e => {
                const via = e.origin?.startsWith("action:") ? `via ${nameOf(e.origin.slice(7))}` : e.origin ? keyToWords(e.origin) : "";
                const meta = [via, e.note, !shared && who(e) ? `by ${who(e)}` : ""].filter(Boolean).join(" · ");
                return (
                  <div key={e.id} data-testid="edit-row" title={e.version ? `version ${e.version}` : undefined}
                    style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0 10px", padding: "1px 0 1px 12px" }}>
                    <span className="aug-fs-sm" style={{ flex: "0 1 190px", color: "var(--t2)", ...ONE_LINE }} title={e.column || undefined}>
                      {editLabel(e)}
                    </span>
                    <span className="aug-fs-sm" style={{ flex: "1 1 220px", minWidth: 0, overflowWrap: "anywhere" }}>
                      <span style={{ color: "var(--t1)" }}>{e.body}</span>
                      {meta && <span className="aug-fs-xs" style={{ ...MUTED, marginLeft: 8 }}>{meta}</span>}
                    </span>
                    <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap", marginLeft: "auto" }}
                      title={e.created_at ? formatTimestamp(e.created_at) : undefined}>
                      {e.created_at ? relTime(e.created_at) : "—"}
                    </span>
                    <Button size="xs" variant="ghost" disabled={busy === e.id} onClick={() => void withdraw(e.id)}
                      title="Withdraw this edit — the next read stops merging it and the source value, never written, is what shows">
                      {busy === e.id ? "Withdrawing…" : "Withdraw"}
                    </Button>
                  </div>
                );
              })}
            </div>
          ))}
        </>}
    </section>
  );
}

function AnnotateForm({ connectionId, onClose, onSaved }: { connectionId: string; onClose: () => void; onSaved: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [f, setF] = useState({ table: "", column: "", key_column: "", row_key: "", body: "", kind: "annotation" });
  const save = async () => {
    setErr(null);
    try {
      await post(`/kinetic-actions/annotate?${on(connectionId)}`, f);
      setF({ ...f, body: "" }); onSaved();
    } catch (e) { setErr(said(e)); }
  };
  return (
    <div data-testid="actions-annotate" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 6,
      padding: "8px 0 10px" }}>
      {err && <div className="aug-fs-sm" role="alert" style={{ ...ERR, gridColumn: "1 / -1" }}>{err}</div>}
      <Input aria-label="Table" placeholder="table" value={f.table} onChange={e => setF({ ...f, table: e.target.value })} />
      <Input aria-label="Column" placeholder="column (optional)" value={f.column} onChange={e => setF({ ...f, column: e.target.value })} />
      <Input aria-label="Key column" placeholder="key column (optional)" value={f.key_column} onChange={e => setF({ ...f, key_column: e.target.value })} />
      <Input aria-label="Row key" placeholder="row key (optional)" value={f.row_key} onChange={e => setF({ ...f, row_key: e.target.value })} />
      <Input aria-label="Note" placeholder="the note" value={f.body} style={{ gridColumn: "1 / -1" }}
        onChange={e => setF({ ...f, body: e.target.value })} />
      <span style={{ ...ROW, gridColumn: "1 / -1" }}>
        <Button variant="default" size="xs" disabled={!f.table.trim() || !f.body.trim()} onClick={save}>Save note</Button>
        <Button variant="ghost" size="xs" onClick={onClose}>Close</Button>
      </span>
    </div>
  );
}

// ── Calls to other systems ───────────────────────────────────────────────────────

/** Arc OC-6 — the outbox of this connection's declared actions: what was delivered or is being sent again, and why.
 *  The calls that wait for a person are under Needs you, with Retry and Dismiss. Off is said, never implied: a section
 *  that hid itself read as a feature that does not exist (2026-10-10). */
function Calls({ read }: { read: Read<{ enabled: boolean; sends: ActionSend[] }> }) {
  const all = read.data?.sends ?? [];
  const rest = all.filter(s => !waits(s));
  const shown = rest.slice(0, CALLS_SHOWN);
  return (
    <section aria-label="Calls to other systems" data-testid="actions-calls" style={CARD}>
      <Label right={read.data && <>
        {rest.length > CALLS_SHOWN && <Chip title="The newest calls are listed; older ones are kept and not shown">newest {CALLS_SHOWN} of {formatCount(rest.length)}</Chip>}
        <Chip title={read.data.enabled ? "Each call is kept, retried by why it failed, and handed to you when no retry will deliver it"
          : "Switched off in Settings → System → Feature flags"}>
          {read.data.enabled ? "outbox on" : "outbox off"}
        </Chip>
      </>}>
        Calls to other systems
      </Label>
      {read.data === null
        ? (read.error ? <ReadFailed what="the outbox" error={read.error} onRetry={read.reload} /> : <Loading what="the outbox" />)
        : <>
          {read.error && <RefreshFailed error={read.error} onRetry={read.reload} />}
          {!read.data.enabled && all.length === 0 ? (
            <div data-testid="sends-off">
              <Empty>Calls go out once and are not kept. Switch the outbox on in Settings → System → Feature flags to keep and retry them.</Empty>
            </div>
          ) : rest.length === 0 ? (
            <Empty>{all.length ? "Every call is under Needs you." : "No call has been sent yet."}</Empty>
          ) : shown.map((s, i) => <CallRow key={s.id} s={s} first={i === 0} />)}
        </>}
    </section>
  );
}

function CallRow({ s, first }: { s: ActionSend; first: boolean }) {
  // a call that landed says what settled it — its check found it, nothing sent again — not the error before
  const settled = s.status === "delivered" ? s.reconciled : s.last_error || s.reconciled;
  return (
    <div data-testid="send-row" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, padding: "6px 0",
      ...(first ? {} : RULE) }}>
      <div style={{ minWidth: 0 }}>
        <div className="aug-fs-chrome" style={{ ...ROW, gap: 6 }}>
          <span style={{ color: "var(--t1)", fontWeight: 500 }}>{s.action_name}</span>
          <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
            {SEND_WORDS[s.status]}{s.attempts ? ` · ${countNoun(s.attempts, "attempt")}` : ""}
          </span>
          <span className="aug-fs-xs" style={MUTED} title={s.effect.target || undefined}>
            {s.effect.kind}{s.effect.lane === "writeback" ? " · writeback" : ""}
          </span>
        </div>
        {/* a call a person left undelivered says who and why — their reason, beside what the call itself met */}
        {s.status === "dismissed" && (s.resolved_by || s.note) && (
          <div className="aug-fs-xs" data-testid="send-left-by" style={{ color: "var(--t2)" }}>
            {[s.resolved_by && `by ${s.resolved_by}`, s.note].filter(Boolean).join(" — ")}
          </div>
        )}
        {settled && (
          <div className="aug-fs-xs" data-testid="send-said" style={{ ...MUTED, overflowWrap: "anywhere" }}>{settled}</div>
        )}
      </div>
      <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }} title={formatTimestamp(s.updated_at)}>
        {relTime(s.updated_at)}
      </span>
    </div>
  );
}
