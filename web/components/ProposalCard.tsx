"use client";

/**
 * SP-9 — ONE approval card per proposal kind, the same wherever a proposal is read:
 * Attention, the Automations inbox, the Actions rail and chat. A person deciding
 * Accept or Reject sees WHAT either click creates — an agent's scope and
 * instructions, a chain's trigger, steps and destination, its first run, who it runs
 * as — never a raw params dump (the ratchet in
 * tests/unit/test_proposal_card_ratchet.py holds that line).
 *
 * The card also closes SP-7's loop: a draft's OPEN choices (a Slack channel nobody
 * named) render as fields to fill, and Accept sends the answers as `fills` — the
 * person making the choice at the moment of arming, which is the only actor allowed
 * to. The server re-checks everything; these fields are an offer, not an authority.
 */

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { acceptProposal, getProposalById, rejectProposal, type StagedProposal } from "@/lib/api";
import { relTime } from "@/lib/format";

/** "2026-09-16T09:00:00Z" → "Tue, 16 Sep 2026 09:00 UTC" — the clock is always named. */
export function utcWords(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toUTCString().replace(/:\d{2} GMT$/, " UTC");
}

type OpenChoice = { action: number; key: string };

/** The fillable open choices stamped at stage time (advisory; accept re-checks). */
function openChoicesOf(p: StagedProposal): OpenChoice[] {
  const raw = p.detail?.open_choices;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((c): c is Record<string, unknown> => !!c && typeof c === "object")
    .map(c => ({ action: Number(c.action), key: String(c.key ?? "") }))
    .filter(c => Number.isFinite(c.action) && c.key !== "");
}

const KIND_CHIP: Record<string, { hue: ChipHue; label: string }> = {
  declared_action: { hue: "caution", label: "action" },
  integration: { hue: "caution", label: "integration write" },
  agent_draft: { hue: "info", label: "new agent" },
  automation_draft: { hue: "info", label: "new automation" },
  agent_bundle: { hue: "info", label: "agent + schedule" },
  automation_state: { hue: "accent", label: "pause / resume" },
  agent_grant: { hue: "accent", label: "agent grant" },
};

const STATUS_TONE: Record<string, string> = {
  executed: "var(--grn4)", accepted: "var(--grn4)",
  failed: "var(--red4)", rejected: "var(--t3)",
  expired: "var(--t3)", uncertain: "var(--amb4)",
};

/** One labeled fact. The card is built from these instead of a JSON dump. */
function Row({ label, children, mono }: {
  label: string; children: React.ReactNode; mono?: boolean;
}) {
  return (
    <div className="flex gap-2 items-baseline min-w-0">
      <span className="aug-text-xs shrink-0" style={{ color: "var(--t3)", width: 88 }}>{label}</span>
      <span className={`aug-text-sm min-w-0 ${mono ? "font-mono" : ""}`}
        style={{ color: "var(--t2)", overflowWrap: "anywhere" }}>{children}</span>
    </div>
  );
}

/** A scalar rendered as itself; a structure as its parts, one per line. Never the
 *  whole params object in one breath. */
function valueWords(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "object") {
    if (Array.isArray(v)) return v.map(x => valueWords(x)).join(", ");
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${k}: ${valueWords(x)}`).join(" · ");
  }
  return String(v);
}

function ParamRows({ params, omit }: { params: Record<string, unknown>; omit?: string[] }) {
  const skip = new Set(omit ?? []);
  const entries = Object.entries(params ?? {}).filter(([k]) => !skip.has(k));
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      {entries.map(([k, v]) => <Row key={k} label={k} mono>{valueWords(v)}</Row>)}
    </div>
  );
}

/* ── the chain, read as a strip: trigger → steps, each saying where it lands ── */

const EFFECT_DEST_KEYS = ["channel", "bot_id", "trigger_id", "rule_id", "url", "action_id", "agent_id"];

function stepWords(e: Record<string, unknown>): string {
  const cfg = (e.config ?? {}) as Record<string, unknown>;
  const dest = EFFECT_DEST_KEYS
    .filter(k => cfg[k] != null && cfg[k] !== "")
    .map(k => `${k} ${String(cfg[k])}`);
  return dest.length ? `${String(e.kind ?? "step")} → ${dest.join(" · ")}` : String(e.kind ?? "step");
}

function triggerWords(c: Record<string, unknown>): string {
  const cfg = (c.config ?? {}) as Record<string, unknown>;
  if (c.kind === "schedule" && cfg.cron) return `schedule · ${String(cfg.cron)} (UTC)`;
  return String(c.kind ?? "trigger");
}

function ChainStrip({ chain, openKeys }: {
  chain: Record<string, unknown>;
  /** "N.key" specs still open, so the strip can mark the step that waits. */
  openKeys: Set<string>;
}) {
  const conditions = (chain.conditions ?? []) as Record<string, unknown>[];
  const effects = (chain.effects ?? []) as Record<string, unknown>[];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {conditions.map((c, i) => (
        <span key={`c${i}`} className="aug-text-xs font-mono rounded px-1.5 py-0.5"
          style={{ background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t2)" }}>
          {triggerWords(c)}
        </span>
      ))}
      {effects.map((e, i) => {
        const waits = EFFECT_DEST_KEYS.some(k => openKeys.has(`${i + 1}.${k}`));
        return (
          <span key={`e${i}`} className="flex items-center gap-1.5">
            <span aria-hidden style={{ color: "var(--t3)" }}>›</span>
            <span className="aug-text-xs font-mono rounded px-1.5 py-0.5"
              style={{
                background: "var(--bg-3)", color: waits ? "var(--amb4)" : "var(--t2)",
                border: `1px solid ${waits ? "var(--amb4)" : "var(--b1)"}`,
              }}>
              {stepWords(e)}{waits ? " · a choice is open" : ""}
            </span>
          </span>
        );
      })}
    </div>
  );
}

/* ── kind bodies ── */

function AgentBody({ d, connectionId }: { d: Record<string, unknown>; connectionId: string }) {
  const docs = (d.doc_ids ?? []) as unknown[];
  return (
    <div className="flex flex-col gap-1">
      <Row label="Agent">{String(d.name ?? "")}</Row>
      <Row label="Scope">
        {connectionId}{d.schema_scope ? ` · schema ${String(d.schema_scope)}` : " · every schema the connection has"}
      </Row>
      <Row label="Instructions">{String(d.instructions ?? "")}</Row>
      <Row label="Documents">
        {docs.length > 0 ? `${docs.length} attached`
          : "none — this agent will see less context than plain chat until documents are added"}
      </Row>
    </div>
  );
}

function AutomationBody({ chain, detail, openKeys }: {
  chain: Record<string, unknown>;
  detail: Record<string, unknown>;
  openKeys: Set<string>;
}) {
  const firstRun = String(detail.first_run ?? "");
  const runsAs = String(detail.runs_as ?? "");
  return (
    <div className="flex flex-col gap-1.5">
      <Row label="Automation">{String(chain.name ?? "")}</Row>
      {chain.description ? <Row label="Does">{String(chain.description)}</Row> : null}
      <ChainStrip chain={chain} openKeys={openKeys} />
      {runsAs && <Row label="Runs as">{runsAs}</Row>}
      {firstRun && <Row label="First run">{utcWords(firstRun)}</Row>}
      {detail.dry_run_ok === true && (
        <Row label="Dry run">walked without dispatching — the draft validates end to end</Row>
      )}
    </div>
  );
}

/* ── the card ── */

export function ProposalCard({ proposal, actor, onResolved, onOpenInEditor, inboxHref, accountLabel }: {
  proposal: StagedProposal;
  /** Recorded as the accept/reject actor — the surface's own name until SP-14 binds identity. */
  actor: string;
  /** Called after a resolve lands (accept or reject), with the outcome sentence. */
  onResolved?: (status: "ok" | "err", message: string) => void;
  /** Opens the draft on the real editing surface. Offered only for drafts that have one. */
  onOpenInEditor?: (p: StagedProposal) => void;
  /** Where this proposal lives — rendered as a link on surfaces away from the inbox. */
  inboxHref?: () => void;
  /** Resolves an integration grant id to the account's own words ("slack · Aughor HQ"). */
  accountLabel?: (grantId: string) => string;
}) {
  const p = proposal;
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [mint, setMint] = useState(false);
  const [fills, setFills] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string>(p.status);
  // The record can settle from OUTSIDE this card (another surface, or the
  // by-id wrapper's pending poll) — the rendered status follows the prop.
  useEffect(() => { setStatus(p.status); }, [p.status]);

  const choices = useMemo(() => openChoicesOf(p), [p]);
  const openKeys = useMemo(
    () => new Set(choices.filter(c => !fills[`${c.action}.${c.key}`]?.trim()).map(c => `${c.action}.${c.key}`)),
    [choices, fills]);
  const unfilled = choices.filter(c => !fills[`${c.action}.${c.key}`]?.trim());
  const chip = KIND_CHIP[p.kind] ?? { hue: "caution" as ChipHue, label: p.kind };
  const pending = status === "pending";

  const accept = async () => {
    setBusy(true);
    try {
      const filled = Object.fromEntries(Object.entries(fills).filter(([, v]) => v.trim()));
      const r = await acceptProposal(p.id, actor, mint, filled);
      setStatus(r.status);
      setNote(String((r.outcome as Record<string, unknown>)?.message ?? ""));
      onResolved?.("ok", `Accepted → ${r.status}${r.minted_grant ? " (grant minted)" : ""}`);
    } catch (e) {
      setNote((e as Error).message);
      onResolved?.("err", (e as Error).message);
    } finally { setBusy(false); }
  };
  const reject = async () => {
    setBusy(true);
    try {
      await rejectProposal(p.id, actor);
      setStatus("rejected");
      onResolved?.("ok", "Rejected — nothing changed");
    } catch (e) {
      setNote((e as Error).message);
      onResolved?.("err", (e as Error).message);
    } finally { setBusy(false); }
  };

  const agentD = (p.params?.agent ?? {}) as Record<string, unknown>;
  const chainD = (p.kind === "agent_bundle"
    ? (p.params?.automation ?? {})
    : p.params ?? {}) as Record<string, unknown>;

  return (
    <div className="flex flex-col gap-2 rounded-md p-3"
      style={{ border: "1px solid var(--b1)", background: "var(--bg-2)" }}>
      <div className="flex items-center gap-2 flex-wrap">
        <StatusChip hue={chip.hue} strength="soft">{chip.label}</StatusChip>
        {p.kind === "integration" && p.grant_id && (
          <span className="aug-text-xs" style={{ color: "var(--amb4)" }}>
            as {accountLabel ? accountLabel(p.grant_id) : p.grant_id}
          </span>
        )}
        <span className="aug-text-xs" style={{ color: "var(--t3)" }}>
          by {p.proposer} · waiting {relTime(p.created_at)}
        </span>
        <span className="flex-1" />
        {inboxHref && (
          <Button variant="ghost" size="xs" onClick={inboxHref}>Open in inbox</Button>
        )}
      </div>

      {p.kind === "agent_draft" && <AgentBody d={p.params ?? {}} connectionId={p.connection_id} />}
      {p.kind === "automation_draft" && (
        <AutomationBody chain={chainD} detail={p.detail ?? {}} openKeys={openKeys} />
      )}
      {p.kind === "agent_bundle" && (
        <div className="flex flex-col gap-2">
          <AgentBody d={agentD} connectionId={p.connection_id} />
          <AutomationBody chain={chainD} detail={p.detail ?? {}} openKeys={openKeys} />
          <span className="aug-text-xs" style={{ color: "var(--t3)" }}>
            One decision: accepting creates the agent and saves the chain running as it —
            all or nothing. Rejecting creates neither.
          </span>
        </div>
      )}
      {p.kind === "automation_state" && (
        <Row label="Change">
          {String(p.params?.action ?? "")} automation {String(p.params?.automation_id ?? "")}
          {p.params?.until ? ` until ${utcWords(String(p.params.until))}` : ""}
        </Row>
      )}
      {p.kind === "agent_grant" && (
        <div className="flex flex-col gap-1">
          <Row label="Grant">let agent {String(p.params?.agent_id ?? "")} propose {String(p.params?.action_id ?? "")}</Row>
          <span className="aug-text-xs" style={{ color: "var(--t3)" }}>
            A grant is permission to propose — its proposals still land here for a person.
          </span>
        </div>
      )}
      {(p.kind === "declared_action" || p.kind === "integration") && (
        <div className="flex flex-col gap-1">
          <Row label="Action" mono>{p.action_id}</Row>
          <ParamRows params={p.params ?? {}} />
        </div>
      )}

      {p.reasoning && (
        <span className="aug-text-xs" style={{ color: "var(--t3)" }}>{p.reasoning}</span>
      )}

      {pending && choices.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="aug-text-xs" style={{ color: "var(--amb4)" }}>
            Open choices — yours to make; Accept waits until each has a value.
          </span>
          {choices.map(c => {
            const spec = `${c.action}.${c.key}`;
            return (
              <label key={spec} className="flex items-center gap-2">
                <span className="aug-text-xs font-mono shrink-0" style={{ color: "var(--t3)", width: 88 }}>
                  step {c.action} · {c.key}
                </span>
                <input
                  className="aug-text-sm rounded px-2 py-1 flex-1 min-w-0"
                  style={{ background: "var(--bg-1)", border: "1px solid var(--b1)", color: "var(--t1)" }}
                  value={fills[spec] ?? ""}
                  placeholder={c.key === "channel" ? "#channel" : c.key}
                  onChange={e => setFills(f => ({ ...f, [spec]: e.target.value }))}
                />
              </label>
            );
          })}
        </div>
      )}

      {pending ? (
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="secondary" size="xs" disabled={busy || unfilled.length > 0}
            title={unfilled.length > 0 ? "Fill the open choices first — accepting would arm a placeholder" : undefined}
            onClick={accept}>Accept</Button>
          {(p.kind === "automation_draft" || p.kind === "agent_bundle") && onOpenInEditor && (
            <Button variant="ghost" size="xs" onClick={() => onOpenInEditor(p)}>Open in editor</Button>
          )}
          <Button variant="ghost" size="xs" disabled={busy} style={{ color: "var(--red3)" }}
            onClick={reject}>Reject</Button>
          {p.kind === "declared_action" && (
            <label className="aug-text-xs flex items-center gap-1.5 cursor-pointer" style={{ color: "var(--t3)" }}>
              <input type="checkbox" checked={mint} onChange={e => setMint(e.target.checked)} />
              also allow this target unattended
            </label>
          )}
          {p.kind === "integration" && (
            <span className="aug-text-xs" style={{ color: "var(--t3)" }}>
              to allow this account unattended, approve it under Approvals
            </span>
          )}
        </div>
      ) : (
        <span className="aug-text-xs" style={{ color: STATUS_TONE[status] ?? "var(--t3)" }}>
          {status}{note ? ` — ${note}` : ""}
        </span>
      )}
      {pending && note && (
        <span className="aug-text-xs" style={{ color: "var(--red4)" }}>{note}</span>
      )}
    </div>
  );
}

/** The card, fetched by id — for surfaces that hold only a reference: a chat turn's
 *  `proposal_staged` frame, an Attention row. undefined = loading; null = the record
 *  is gone (resolved and swept, or never staged), said plainly rather than crashed on. */
export function ProposalCardById({ proposalId, actor, onResolved, onOpenInEditor }: {
  proposalId: string;
  actor: string;
  onResolved?: (status: "ok" | "err", message: string) => void;
  onOpenInEditor?: (p: StagedProposal) => void;
}) {
  const [p, setP] = useState<StagedProposal | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    const read = () => getProposalById(proposalId)
      .then(x => { if (live) setP(x); })
      .catch(() => { if (live) setP(prev => prev ?? null); });
    read();
    // SP-10 — live status: a proposal resolved on ANOTHER surface (the inbox,
    // Attention, Slack) settles on this card too. A modest poll only while the
    // record is still pending; a settled card stops asking.
    const iv = setInterval(() => {
      setP(prev => {
        if (prev && prev.status !== "pending") { clearInterval(iv); return prev; }
        void read();
        return prev;
      });
    }, 15_000);
    return () => { live = false; clearInterval(iv); };
  }, [proposalId]);
  if (p === undefined) {
    return <span className="aug-text-xs" style={{ color: "var(--t3)" }}>loading proposal…</span>;
  }
  if (p === null) {
    return (
      <span className="aug-text-xs" style={{ color: "var(--t3)" }}>
        proposal {proposalId} is no longer in the inbox — resolved elsewhere, or swept.
      </span>
    );
  }
  return <ProposalCard proposal={p} actor={actor} onResolved={onResolved} onOpenInEditor={onOpenInEditor} />;
}
