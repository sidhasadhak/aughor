"use client";

/**
 * Operations ▸ Developer — "extend the platform without opening a second write path, and see
 * how what you built is measured" (the 2027 study §V, screen 13).
 *
 * Packs with their measured record; the doors an outside agent uses, with the events it can
 * subscribe to; service principals and their keys; the kits; and the agent contract as a
 * document, rendered from what the code enforces. Nothing here runs inside the process.
 */
import { useState } from "react";

import { getApiBase } from "@/lib/config";
import { countNoun, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { keyToWords } from "@/lib/names";
import {
  getContract, getEventCatalogue, getMethods, getServicePrincipals, mintServicePrincipal, revokeServicePrincipal,
  type AgentContract, type ContractDuty, type EventKind, type ServicePrincipal,
} from "@/lib/record";
import { Absent, Gate, Ledger, Page, Section, day, useLoad, type LedgerColumn } from "@/components/record/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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

export function DeveloperPanel({ onOpenPacks, onOpenIntegrations }: {
  onOpenPacks: () => void;
  onOpenIntegrations: () => void;
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
        action={<Button size="xs" variant="ghost" onClick={onOpenPacks} title="Upload a pack, run its checks, activate or demote one">Manage packs</Button>}>
        <Gate load={packs} what="the packs">
          {p => (
            <>
              <Ledger name="packs" columns={packColumns} rows={p.packs} rowKey={x => x.id} empty="No pack is installed." />
              <Absent>{p.rule}.</Absent>
            </>
          )}
        </Gate>
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
        <Gate load={methods} what="the methods">
          {m => (
            <div className="aug-item">
              <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                Projection methods: {m.builtin.join(", ")}{m.registered.length ? `, and ${countNoun(m.registered.length, "registered method")}` : "; none registered from outside"}.
              </div>
              <div className="aug-item-foot aug-fs-sm"><span>{m.rule}</span></div>
            </div>
          )}
        </Gate>
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
        <div className="aug-callout aug-callout-amber" style={{ margin: "10px 0" }}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
            The key for {minted.name} is shown once and stored hashed. Copy it now.
          </div>
          <div className="aug-mono aug-fs-sm" style={{ marginTop: 6, overflowWrap: "anywhere", userSelect: "all" }}>{minted.key}</div>
          <Button size="xs" variant="ghost" style={{ marginTop: 6 }} onClick={() => setMinted(null)}>I have copied it</Button>
        </div>
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
