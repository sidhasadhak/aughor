"use client";

/**
 * Operations ▸ Developer — "extend the platform without opening a second write path, and see
 * how what you built is measured" (the 2027 study §V, screen 13).
 *
 * Packs with their measured record; the doors an outside agent uses, with the events it can
 * subscribe to; service principals and their keys; the kits; and the agent contract as a
 * document, rendered from what the code enforces. Nothing here runs inside the process.
 *
 * A pack is checked here before it is uploaded — the check writes nothing — and arrives as a
 * draft that steers nothing until a person activates it. A projection method is registered with
 * the backtest it carries, and runs as a tool on a server already connected.
 */
import { useState } from "react";

import { getApiBase } from "@/lib/config";
import { countNoun, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { keyToWords } from "@/lib/names";
import {
  checkPack, getContract, getEventCatalogue, getMethods, getServicePrincipals, mintServicePrincipal,
  registerMethod, revokeServicePrincipal, uploadPack, withdrawMethod,
  type AgentContract, type ContractDuty, type EventKind, type PackVerdict, type RegisteredMethod, type ServicePrincipal,
} from "@/lib/record";
import { Absent, Gate, Ledger, Page, Section, day, useLoad, type LedgerColumn } from "@/components/record/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Callout } from "@/components/ui/callout";

interface PackListing {
  id: string; name: string; status: string; layer: string; source: string; description: string;
  claims: { measured: number; supported: number; refuted: number; open: number; held_share: number | null; connections: number };
  gates: { dataset: string; measured: boolean; in_range: number; metrics: number }[];
  demotion_due: boolean;
}

interface PackKit {
  version: string;
  principle: string;
  anatomy: { file: string; required?: boolean; declares: string }[];
  [k: string]: unknown;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`);
  if (!res.ok) throw new Error(`${path} could not be read (${res.status})`);
  return res.json();
}

const STATUS_HUE: Record<string, ChipHue> = { active: "positive", draft: "info", demoted: "negative", deprecated: "muted" };

export function DeveloperPanel({ onOpenPacks, onOpenIntegrations, onOpenDeclared }: {
  onOpenPacks: () => void;
  onOpenIntegrations: () => void;
  /** Intelligence ▸ Actions, where an action is declared with its verification and its undo. */
  onOpenDeclared: () => void;
}) {
  const packs = useLoad(() => get<{ packs: PackListing[]; rule: string }>("/packs/listing"), []);
  const contract = useLoad(() => getContract(), []);
  const events = useLoad(() => getEventCatalogue(), []);
  const principals = useLoad(() => getServicePrincipals(), []);
  const kit = useLoad(() => get<PackKit>("/packs/kit"), []);
  const methods = useLoad(() => getMethods(), []);

  const packColumns: LedgerColumn<PackListing>[] = [
    { head: "Pack", cell: p => p.name || p.id },
    { head: "Status", cell: p => <StatusChip hue={STATUS_HUE[p.status] ?? "muted"}>{p.status}</StatusChip>, width: 110 },
    { head: "Layer", cell: p => p.layer || "—", width: 110 },
    { head: "Claims that held", cell: p => (p.claims.held_share != null ? `${pct(p.claims.held_share)} of ${p.claims.measured}` : "not measured on an install"), width: 220 },
    { head: "Installs", cell: p => p.claims.connections, num: true, width: 80 },
    { head: "Measured on", cell: p => (p.gates.length ? p.gates.map(g => `${g.dataset}: ${g.in_range} of ${g.metrics} in range`).join("; ") : "no public dataset") },
    { head: "Demotion", cell: p => (p.demotion_due ? <StatusChip hue="negative">due</StatusChip> : "—"), width: 100 },
  ];

  const eventColumns: LedgerColumn<EventKind>[] = [
    { head: "Event", cell: e => <span className="aug-mono">{e.kind}</span>, width: 240 },
    { head: "What it says", cell: e => e.what },
    { head: "Carries", cell: e => e.payload.map(keyToWords).join(", ") },
    { head: "Subscribable", cell: e => (e.subscribable ? "yes" : "no"), width: 110 },
  ];

  const dutyColumns: LedgerColumn<ContractDuty>[] = [
    { head: "Duty", cell: d => d.duty, width: 110 },
    { head: "Books", cell: d => d.books.join(", "), width: 190 },
    { head: "May propose", cell: d => d.proposes.join(", ") || "—", width: 220 },
    { head: "Carried today by", cell: d => d.today },
    { head: "Why it exists", cell: d => d.why },
  ];

  return (
    <Page wide>
      <Section label="Packs" meta={packs.data ? countNoun(packs.data.packs.length, "pack") : undefined}
        action={<Button size="xs" variant="ghost" onClick={onOpenPacks} title="Bind a pack to a connection, measure it, activate or demote it">Manage packs</Button>}>
        <Gate load={packs} what="the packs">
          {p => (
            <>
              <Ledger name="packs" columns={packColumns} rows={p.packs} rowKey={x => x.id} empty="No pack is installed." />
              <Absent>{p.rule}.</Absent>
            </>
          )}
        </Gate>
        <PackUpload onUploaded={packs.reload} />
      </Section>

      <Section label="Doors" action={<Button size="xs" variant="ghost" onClick={onOpenIntegrations}>Integrations</Button>}>
        <Gate load={contract} what="the doors">
          {c => <Doors contract={c} />}
        </Gate>
      </Section>

      <Section label="Events out" meta={events.data ? countNoun(events.data.kinds.length, "kind") : undefined}>
        <Gate load={events} what="the event catalogue">
          {e => <Ledger name="event-catalogue" columns={eventColumns} rows={e.kinds} rowKey={k => k.kind} empty="No event kind is declared." />}
        </Gate>
      </Section>

      <Section label="Principals and keys" meta={principals.data ? countNoun(principals.data.principals.length, "service principal") : undefined}>
        <Gate load={principals} what="service principals">
          {p => <Principals principals={p.principals} onChanged={principals.reload} />}
        </Gate>
      </Section>

      <Section label="The kits">
        <Gate load={kit} what="the pack kit">
          {k => (
            <>
              <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: "0 0 8px", maxWidth: "72ch" }}>{k.principle}</p>
              {k.anatomy.map(a => (
                <div className="aug-item" key={a.file}>
                  <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                    <span className="aug-mono">{a.file}</span>{a.required ? " — required" : ""}
                  </div>
                  <div className="aug-item-foot aug-fs-sm"><span>{a.declares}</span></div>
                </div>
              ))}
            </>
          )}
        </Gate>
      </Section>

      <Section label="Projection methods" meta={methods.data ? `${countNoun(methods.data.builtin.length, "built-in method")} · ${methods.data.registered.length} registered` : undefined}>
        <Gate load={methods} what="the methods">
          {m => <Methods builtin={m.builtin} registered={m.registered} rule={m.rule} onChanged={methods.reload} />}
        </Gate>
      </Section>

      <Section label="Declared actions">
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <Absent>An action is declared on a connection&apos;s object model, with the read that verifies it and how it is undone.</Absent>
          <Button size="xs" variant="outline" onClick={onOpenDeclared}>Declare an action</Button>
        </div>
      </Section>

      <Section label="The agent contract" meta={contract.data ? `version ${contract.data.version}` : undefined}>
        <Gate load={contract} what="the agent contract">
          {c => (
            <>
              <Ledger name="agent-contract-duties" columns={dutyColumns} rows={c.duties} rowKey={d => d.duty} empty="No duty is declared." />
              <ContractRest contract={c} />
            </>
          )}
        </Gate>
      </Section>
    </Page>
  );
}

// ── a pack, checked and uploaded ─────────────────────────────────────────────────────────

/** Files a pack is made of are text; anything else in the folder is left behind, and said. */
const PACK_TEXT = /\.(ya?ml|md|json|sql|txt|csv)$/i;
const PACK_FILE_LIMIT = 512 * 1024;

function PackUpload({ onUploaded }: { onUploaded: () => void }) {
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [verdict, setVerdict] = useState<PackVerdict | null>(null);
  const [said, setSaid] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const choose = async (list: FileList | null) => {
    setVerdict(null); setSaid(""); setError("");
    const chosen = Array.from(list ?? []);
    if (chosen.length === 0) { setFiles(null); setSkipped([]); return; }
    // A chosen folder prefixes every path with its own name; the pack's paths start inside it.
    const paths = chosen.map(f => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
    const root = paths.every(p => p.includes("/")) && new Set(paths.map(p => p.split("/")[0])).size === 1 ? paths[0].split("/")[0] + "/" : "";
    const read: Record<string, string> = {};
    const left: string[] = [];
    setBusy(true);
    try {
      for (let i = 0; i < chosen.length; i++) {
        const path = paths[i].slice(root.length);
        if (!PACK_TEXT.test(path) || chosen[i].size > PACK_FILE_LIMIT) { left.push(path); continue; }
        read[path] = await chosen[i].text();
      }
      setFiles(read); setSkipped(left);
      setVerdict(await checkPack(read));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const upload = async (overwrite: boolean) => {
    if (!files) return;
    setBusy(true); setError("");
    try {
      await uploadPack(files, overwrite);
      setSaid(`${verdict?.pack_id || "The pack"} is uploaded as a draft. It steers nothing until a person activates it.`);
      setFiles(null); setVerdict(null); setSkipped([]);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const declares = Object.entries(verdict?.declares ?? {}).filter(([, v]) => v !== 0 && v !== false)
    .map(([k, v]) => (typeof v === "boolean" ? keyToWords(k) : `${v} ${keyToWords(k)}`));
  const exists = /already exists/.test(error);
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Check a pack, then upload it:</span>
        <Input type="file" multiple aria-label="A pack's folder" disabled={busy} onChange={e => void choose(e.target.files)}
          {...({ webkitdirectory: "" } as Record<string, string>)} style={{ width: 300 }} />
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>choose the pack&apos;s folder; checking writes nothing</span>
      </div>
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "8px 0 0" }}>{error}</p>}
      {said && <p className="aug-fs-sm" role="status" style={{ color: "var(--t2)", margin: "8px 0 0" }}>{said}</p>}
      {verdict && (
        <Callout tone={verdict.ok ? "green" : "amber"} style={{ marginTop: 10 }}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
            {verdict.ok
              ? `${verdict.pack_id} passes the static checks (${countNoun(verdict.files, "file")}).`
              : `${verdict.pack_id || "This pack"} does not pass the static checks: ${countNoun(verdict.errors.length, "error")}.`}
          </div>
          {verdict.errors.map(x => <div className="aug-fs-sm" key={x} style={{ color: "var(--red4)", marginTop: 4 }}>{x}</div>)}
          {verdict.warnings.map(x => <div className="aug-fs-sm" key={x} style={{ color: "var(--t2)", marginTop: 4 }}>Warning: {x}</div>)}
          <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 4 }}>
            {declares.length ? `It declares ${declares.join(", ")}.` : "It declares nothing the platform reads."}
            {skipped.length ? ` Left behind, not text or over the size limit: ${skipped.slice(0, 6).join(", ")}${skipped.length > 6 ? ` and ${skipped.length - 6} more` : ""}.` : ""}
          </div>
          {verdict.ok && (
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <Button size="xs" disabled={busy} onClick={() => void upload(false)}>Upload as a draft</Button>
              {exists && <Button size="xs" variant="outline" disabled={busy} onClick={() => void upload(true)}>Replace the one that exists</Button>}
            </div>
          )}
        </Callout>
      )}
    </div>
  );
}

// ── projection methods ───────────────────────────────────────────────────────────────────

const METHOD_KINDS = ["forecaster", "estimator", "simulator"] as const;

function backtestWords(m: RegisteredMethod): string {
  const b = m.backtest;
  const error = b.mape != null ? `mean error ${pct(b.mape)}` : b.mae != null ? `mean error ${b.mae}` : "";
  const held = b.coverage_observed != null ? `its interval held ${pct(b.coverage_observed)} of the time` : "";
  return `scored on ${countNoun(b.n, "case")}${b.metric ? ` of ${keyToWords(b.metric)}` : ""} (${b.measured_on.join(", ")}): ${[error, held].filter(Boolean).join("; ")}`;
}

function Methods({ builtin, registered, rule, onChanged }: {
  builtin: string[]; registered: RegisteredMethod[]; rule: string; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<string>("forecaster");
  const [server, setServer] = useState("");
  const [tool, setTool] = useState("");
  const [n, setN] = useState("");
  const [measuredOn, setMeasuredOn] = useState("");
  const [mape, setMape] = useState("");
  const [coverage, setCoverage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const share = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v) / 100);
  const act = async (fn: () => Promise<unknown>, then?: () => void) => {
    setBusy(true); setError("");
    try { await fn(); then?.(); onChanged(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const submit = () => act(() => registerMethod({
    name: name.trim(), kind,
    adapter: { server_id: server.trim(), tool: tool.trim() },
    backtest: { n: Number(n) || 0, measured_on: measuredOn.split(",").map(x => x.trim()).filter(Boolean), mape: share(mape), coverage_observed: share(coverage) },
  }), () => { setOpen(false); setName(""); setServer(""); setTool(""); setN(""); setMeasuredOn(""); setMape(""); setCoverage(""); });
  return (
    <>
      <div className="aug-item">
        <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>Built in: {builtin.join(", ")}.</div>
        <div className="aug-item-foot aug-fs-sm"><span>{rule.charAt(0).toUpperCase() + rule.slice(1)}.</span></div>
      </div>
      {registered.length === 0 ? <Absent>No method is registered from outside.</Absent> : withUniqueKeys(registered, m => m.name).map(([key, m]) => (
        <div className="aug-item" key={key}>
          <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <span className="aug-fs-ui aug-mono" style={{ color: "var(--t1)" }}>{m.name}</span>
            <StatusChip hue="muted">{m.kind}</StatusChip>
          </div>
          <div className="aug-item-foot aug-fs-sm">
            <span>{backtestWords(m)}</span>
            <span>runs as {m.adapter.tool} on {m.adapter.server_id}</span>
            {m.declared_by && <span>registered by {m.declared_by}</span>}
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="outline" disabled={busy} onClick={() => void act(() => withdrawMethod(m.name))}>Withdraw</Button>
          </div>
        </div>
      ))}
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "8px 0 0" }}>{error}</p>}
      {!open ? (
        <Button size="xs" variant="outline" style={{ marginTop: 10 }} onClick={() => setOpen(true)}>Register a method</Button>
      ) : (
        <div className="aug-form-grid" style={{ marginTop: 10 }}>
          <label className="aug-fs-sm" htmlFor="me-name">Name</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Input id="me-name" value={name} onChange={e => setName(e.target.value)} placeholder="vendor-forecaster" style={{ width: 240 }} />
            <Segmented label="Kind of method" value={kind} onChange={setKind}
              options={METHOD_KINDS.map(k => ({ value: k, label: k }))} />
          </div>
          <label className="aug-fs-sm" htmlFor="me-server">Runs as</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Input id="me-server" value={server} onChange={e => setServer(e.target.value)} placeholder="the connected tool server's id" style={{ flex: "1 1 220px" }} />
            <Input aria-label="Tool" value={tool} onChange={e => setTool(e.target.value)} placeholder="the tool it calls" style={{ flex: "1 1 180px" }} />
          </div>
          <label className="aug-fs-sm" htmlFor="me-n">Its backtest</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Input id="me-n" value={n} onChange={e => setN(e.target.value)} placeholder="cases" inputMode="numeric" style={{ width: 90 }} />
            <Input aria-label="Measured on" value={measuredOn} onChange={e => setMeasuredOn(e.target.value)} placeholder="where: datasets or installs, comma-separated" style={{ flex: "1 1 260px" }} />
            <Input aria-label="Mean error, percent" value={mape} onChange={e => setMape(e.target.value)} placeholder="mean error %" inputMode="decimal" style={{ width: 120 }} />
            <Input aria-label="Interval held, percent" value={coverage} onChange={e => setCoverage(e.target.value)} placeholder="interval held %" inputMode="decimal" style={{ width: 130 }} />
          </div>
          <span />
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Button size="xs" disabled={busy || !name.trim()} onClick={() => void submit()}>Register it</Button>
            <Button size="xs" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>A method with no backtest is refused: a projection nobody has scored is a guess with a name.</span>
          </div>
        </div>
      )}
    </>
  );
}

function Doors({ contract }: { contract: AgentContract }) {
  const doors = (contract.doors ?? {}) as {
    ledger_api?: { prefix: string; routes: string[] };
    mcp?: { server: string; tools: string[]; note: string };
    never?: string[];
  };
  return (
    <>
      <div className="aug-item">
        <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>The ledger API, under <span className="aug-mono">{doors.ledger_api?.prefix}</span></div>
        <ul className="aug-fs-sm" style={{ margin: "4px 0 0", paddingLeft: 18, color: "var(--t2)", lineHeight: 1.6 }}>
          {(doors.ledger_api?.routes ?? []).map(r => <li key={r}><span className="aug-mono">{r.split(" — ")[0]}</span>{r.includes(" — ") ? ` — ${r.split(" — ").slice(1).join(" — ")}` : ""}</li>)}
        </ul>
      </div>
      <div className="aug-item">
        <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>The tool server&apos;s contract tools: {(doors.mcp?.tools ?? []).map(keyToWords).join(", ")}</div>
        <div className="aug-item-foot aug-fs-sm"><span>{doors.mcp?.note}</span></div>
      </div>
      {(doors.never ?? []).length > 0 && (
        <Absent>What no door offers: {doors.never!.join("; ")}.</Absent>
      )}
    </>
  );
}

function ContractRest({ contract }: { contract: AgentContract }) {
  const verdicts = (contract.verdicts ?? []) as string[];
  const refusals = (contract.refusals ?? {}) as Record<string, string>;
  const scoring = (contract.scoring ?? {}) as { principle?: string };
  return (
    <div style={{ marginTop: 12 }}>
      {scoring.principle && <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: "0 0 8px" }}>{scoring.principle}.</p>}
      <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "0 0 8px" }}>
        A run ends in one of: {verdicts.map(keyToWords).join(" · ")}.
      </p>
      <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 4 }}>What a door refuses, by name</div>
      {Object.entries(refusals).map(([code, why]) => (
        <div className="aug-item" key={code}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{why}</div>
          <div className="aug-item-foot aug-fs-sm"><span className="aug-mono">{code}</span></div>
        </div>
      ))}
    </div>
  );
}

function Principals({ principals, onChanged }: { principals: ServicePrincipal[]; onChanged: () => void }) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [minted, setMinted] = useState<{ name: string; key: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mint = async () => {
    setBusy(true);
    setError("");
    try {
      const out = await mintServicePrincipal({ name: name.trim(), note: note.trim() });
      setMinted({ name: name.trim(), key: String(out.key ?? "") });
      setName("");
      setNote("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (p: ServicePrincipal) => {
    setError("");
    try { await revokeServicePrincipal(p.name, "revoked from the Developer page"); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <>
      {principals.length === 0 ? (
        <Absent>No outside agent has a principal. One is minted by a person; it is then held to the organisation&apos;s agent policy and scored in the same rows as the built-in agents.</Absent>
      ) : withUniqueKeys(principals, p => p.name).map(([key, p]) => (
        <div className="aug-item" key={key}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{p.name}{p.note ? ` — ${String(p.note)}` : ""}</div>
          <div className="aug-item-foot aug-fs-sm">
            {p.created_at && <span>minted {day(String(p.created_at))}</span>}
            {p.created_by && <span>by {String(p.created_by)}</span>}
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="outline" onClick={() => void revoke(p)}>Revoke</Button>
          </div>
        </div>
      ))}
      {minted && (
        <Callout tone="amber" style={{ margin: "10px 0" }}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
            The key for {minted.name} is shown once and stored hashed. Copy it now.
          </div>
          <div className="aug-mono aug-fs-sm" style={{ marginTop: 6, overflowWrap: "anywhere", userSelect: "all" }}>{minted.key}</div>
          <Button size="xs" variant="ghost" style={{ marginTop: 6 }} onClick={() => setMinted(null)}>I have copied it</Button>
        </Callout>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
        <Input value={name} onChange={e => setName(e.target.value)} placeholder="a name: vendor-forecaster" aria-label="Service principal name" style={{ width: 240 }} />
        <Input value={note} onChange={e => setNote(e.target.value)} placeholder="what it is for" aria-label="What it is for" style={{ flex: "1 1 220px", maxWidth: 360 }} />
        <Button size="xs" disabled={busy || !name.trim()} onClick={() => void mint()}>Mint a principal</Button>
        {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
      </div>
    </>
  );
}
