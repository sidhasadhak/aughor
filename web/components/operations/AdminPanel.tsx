"use client";

/**
 * Operations ▸ Admin — "see every door in and out and what guards it" (the 2027 study §V,
 * screen 12).
 *
 * The gate map is a screen: every place a statement reaches a warehouse with how its dialect is
 * handled, the sites nothing guards with the reason each is still there, and every law of the
 * departure gate with what it held. Policies are read back as sentences. Groups, identity and
 * the audit's way out are stated as they are — including what is recorded and not yet enforced.
 * The five settings pages are the last view, unchanged.
 */
import { getApiBase } from "@/lib/config";
import { countNoun, formatTableNumber } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { keyToWords } from "@/lib/names";
import { whoLabel } from "@/lib/record";
import { Absent, Gate, Ledger, Page, Section, day, useLoad, type LedgerColumn } from "@/components/record/kit";
import { Button } from "@/components/ui/button";

type Lens = "gates" | "policies" | "settings";

const LENSES: { id: Lens; label: string; blurb: string }[] = [
  { id: "gates", label: "Gate map", blurb: "Every door in and out, and what guards it" },
  { id: "policies", label: "Policies and groups", blurb: "Each policy as a sentence, who is in which group, identity and the audit's way out" },
  { id: "settings", label: "Settings", blurb: "Organisation, access, appearance, models and system" },
];

interface Site { key: string; path: string; function: string; door: string; label: string; dialect: string; author: string; note: string }
interface GateMap {
  statements: {
    present: boolean; sites: number; note: string;
    by_dialect: { dialect: string; sites: number; means: string }[];
    by_door: { door: string; sites: number }[];
    unguarded: Site[];
  };
  departures: {
    over: number; note: string;
    laws: { guard: string; label: string; law: string; sentence: string; meaning: string; passed: number; held: number; asked: number; last_held: string }[];
  };
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`);
  if (!res.ok) throw new Error(`${path} could not be read (${res.status})`);
  return res.json();
}

export function AdminPanel({ lens, onLensChange, settings, onOpenSpend, onOpenAudit }: {
  lens: Lens;
  onLensChange: (l: Lens) => void;
  /** The five settings pages, as the shell renders them. */
  settings: React.ReactNode;
  onOpenSpend: () => void;
  onOpenAudit: () => void;
}) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <div className="aug-toolbar">
        <div role="group" aria-label="Admin views" className="aug-segmented">
          {LENSES.map(l => (
            <Button key={l.id} variant="ghost" size="xs" aria-pressed={lens === l.id} title={l.blurb}
              className={`aug-seg-item${lens === l.id ? " active" : ""}`} onClick={() => onLensChange(l.id)}>{l.label}</Button>
          ))}
        </div>
      </div>
      {lens === "gates" && <GateMapView />}
      {lens === "policies" && <Policies onOpenSettings={() => onLensChange("settings")} onOpenSpend={onOpenSpend} onOpenAudit={onOpenAudit} />}
      {lens === "settings" && <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>{settings}</div>}
    </div>
  );
}

export type AdminLens = Lens;

// ── the gate map ─────────────────────────────────────────────────────────────────────────

function GateMapView() {
  const load = useLoad(() => get<GateMap>("/governance/gate-map"), []);
  type DialectRow = GateMap["statements"]["by_dialect"][number];
  type LawRow = GateMap["departures"]["laws"][number];
  const dialectColumns: LedgerColumn<DialectRow>[] = [
    { head: "How the dialect is handled", cell: r => r.dialect, width: 220 },
    { head: "Sites", cell: r => r.sites, num: true, width: 80 },
    { head: "What that means", cell: r => r.means },
  ];
  const doorColumns: LedgerColumn<{ door: string; sites: number }>[] = [
    { head: "Door", cell: r => keyToWords(r.door) },
    { head: "Sites", cell: r => r.sites, num: true, width: 80 },
  ];
  const lawColumns: LedgerColumn<LawRow>[] = [
    { head: "Guard", cell: r => r.label, width: 170 },
    { head: "Law", cell: r => r.law || "—", width: 80 },
    { head: "What it holds", cell: r => r.sentence || r.meaning },
    { head: "Passed", cell: r => r.passed, num: true, width: 80 },
    { head: "Held", cell: r => r.held, num: true, width: 70 },
    { head: "Asked", cell: r => r.asked, num: true, width: 70 },
    { head: "Last held", cell: r => (r.last_held ? day(r.last_held) : "never"), width: 110 },
  ];
  return (
    <Page wide>
      <Gate load={load} what="the gate map">
        {g => (
          <>
            <Section label="Statements in" meta={g.statements.present ? `${countNoun(g.statements.sites, "place")} a statement reaches a warehouse` : undefined}>
              {!g.statements.present ? <Absent>{g.statements.note}.</Absent> : (
                <>
                  <Ledger name="statement-doors-by-dialect" columns={dialectColumns} rows={g.statements.by_dialect}
                    rowKey={r => r.dialect} empty="No statement door is recorded." />
                  <Absent>{g.statements.note}.</Absent>
                </>
              )}
            </Section>

            {g.statements.present && (
              <Section label="Sites nothing guards" meta={countNoun(g.statements.unguarded.length, "site")}>
                {g.statements.unguarded.length === 0 ? (
                  <Absent>Every statement declares its dialect, is written for its engine, or is rendered for it.</Absent>
                ) : g.statements.unguarded.map(s => (
                  <div className="aug-item" key={s.key}>
                    <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{s.note || "no reason recorded"}</div>
                    <div className="aug-item-foot aug-fs-sm">
                      <span className="aug-mono">{s.path}</span>
                      <span>in {s.function}</span>
                      <span>written by {s.author === "person" ? "a person" : s.author === "model" ? "a model" : `the ${s.author}`}</span>
                    </div>
                  </div>
                ))}
              </Section>
            )}

            {g.statements.present && (
              <Section label="By door" meta={countNoun(g.statements.by_door.length, "door")}>
                <Ledger name="statement-doors" columns={doorColumns} rows={g.statements.by_door} rowKey={r => r.door}
                  empty="No door is recorded." />
              </Section>
            )}

            <Section label="Messages out" meta={`${countNoun(g.departures.laws.length, "guard")} on the departure gate`}>
              <Ledger name="departure-laws" columns={lawColumns} rows={g.departures.laws} rowKey={r => r.guard}
                empty="The departure gate declares no guard." />
              <Absent>{g.departures.note}.</Absent>
            </Section>
          </>
        )}
      </Gate>
    </Page>
  );
}

// ── policies, groups, identity, the audit's way out ──────────────────────────────────────

interface AgentPolicy {
  effective: { level: string; connections: string[] | null; tools: string[] | null; set_by: string; updated_at: string; source: string; narrowed_by: string[] };
  levels: string[];
}
interface Caps { caps: { scope: string; subject: string; metric: string; limit: number; window_hours: number; action: string }[] }
interface Role { name: string; label: string; description: string; permissions: string[] }
interface Assignment { user_id?: string; principal?: string; role: string; [k: string]: unknown }
interface Me { user_id: string | null; org_id: string; roles: string[] }

const LEVEL_SENTENCE: Record<string, string> = {
  read: "An agent may look things up, and nothing else.",
  run: "An agent may look things up, start work and book an entry with its warrant. It may not change anything outside the conversation.",
  act: "An agent may look things up, start work, book entries and change something outside the conversation.",
};

const METRIC_WORDS: Record<string, string> = { calls: "model calls", total_tokens: "tokens", cost_usd: "US dollars" };

function Policies({ onOpenSettings, onOpenSpend, onOpenAudit }: {
  onOpenSettings: () => void; onOpenSpend: () => void; onOpenAudit: () => void;
}) {
  const policy = useLoad(() => get<AgentPolicy>("/org-settings/agent-policy"), []);
  const caps = useLoad(() => get<Caps>("/governance/caps"), []);
  const roles = useLoad(() => Promise.all([get<Role[]>("/rbac/roles"), get<Assignment[]>("/rbac/assignments")]), []);
  const me = useLoad(() => get<Me>("/rbac/me"), []);
  return (
    <Page>
      <Section label="What an agent may do" action={<Button size="xs" variant="ghost" onClick={onOpenSettings}>Change it</Button>}>
        <Gate load={policy} what="the agent policy">
          {p => {
            const e = p.effective;
            return (
              <div className="aug-item">
                <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{LEVEL_SENTENCE[e.level] ?? `Agents are held at "${e.level}".`}</div>
                <div className="aug-item-foot aug-fs-sm">
                  <span>{e.connections ? `on ${countNoun(e.connections.length, "connection")} only` : "on every connection"}</span>
                  <span>{e.tools ? `with ${countNoun(e.tools.length, "tool")} only` : "with every tool its level allows"}</span>
                  <span>{e.source === "default" ? "the default — nobody has set it" : `set by ${whoLabel(e.set_by)}${e.updated_at ? ` on ${day(e.updated_at)}` : ""}`}</span>
                  {e.narrowed_by.length > 0 && <span>narrowed by {e.narrowed_by.join(", ")}</span>}
                </div>
              </div>
            );
          }}
        </Gate>
      </Section>

      <Section label="What may be spent" action={<Button size="xs" variant="ghost" onClick={onOpenSpend}>Spend</Button>}>
        <Gate load={caps} what="the spend caps">
          {c => c.caps.length === 0 ? (
            <Absent>No cap is set: nothing alerts or blocks on usage. A cap reads back here as a sentence once one is written.</Absent>
          ) : <>{c.caps.map(cap => (
            <div className="aug-item aug-fs-ui" key={`${cap.scope}:${cap.subject}:${cap.metric}`} style={{ color: "var(--t1)" }}>
              {cap.action === "block" ? "Block" : "Alert"} when {cap.subject === "*" ? `any ${cap.scope === "org" ? "organisation" : cap.scope}` : `${cap.scope} ${cap.subject}`} uses
              more than {formatTableNumber(cap.limit)} {METRIC_WORDS[cap.metric] ?? cap.metric} in {cap.window_hours} hours.
            </div>
          ))}</>}
        </Gate>
      </Section>

      <Section label="Groups" action={<Button size="xs" variant="ghost" onClick={onOpenSettings}>Access</Button>}>
        <Gate load={roles} what="the groups">
          {([rs, as]) => (
            <>
              {withUniqueKeys(rs, r => r.name).map(([key, r]) => {
                const members = as.filter(a => a.role === r.name);
                return (
                  <div className="aug-item" key={key}>
                    <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{r.label} — {r.description}</div>
                    <div className="aug-item-foot aug-fs-sm">
                      <span>{members.length ? members.map(m => whoLabel(String(m.user_id ?? m.principal ?? ""))).join(", ") : "nobody assigned"}</span>
                      <span>{countNoun(r.permissions.length, "permission")}</span>
                    </div>
                  </div>
                );
              })}
              <Absent>A group&apos;s grants are read when a caller is identified. With identity off, every caller holds the owner&apos;s role, so nothing here narrows what anyone sees yet.</Absent>
            </>
          )}
        </Gate>
      </Section>

      <Section label="Identity">
        <Gate load={me} what="who you are to the platform">
          {m => (
            <div className="aug-item">
              <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                {m.user_id
                  ? `You are ${whoLabel(m.user_id)}, holding ${m.roles.join(" and ")}.`
                  : "Identity is off: nobody is asked who they are, and every caller is treated as the owner."}
              </div>
              {!m.user_id && (
                <div className="aug-item-foot aug-fs-sm">
                  <span>It is turned on when the server starts, with <span className="aug-mono">AUGHOR_REQUIRE_IDENTITY=1</span> — a restart, by design.</span>
                </div>
              )}
            </div>
          )}
        </Gate>
      </Section>

      <Section label="The audit's way out" action={<Button size="xs" variant="ghost" onClick={onOpenAudit}>Audit</Button>}>
        <div className="aug-item">
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
            The whole ledger leaves as one file of JSON lines: every claim, decision, outcome, inquiry and mission as it stands.
          </div>
          <div className="aug-item-foot aug-fs-sm">
            <a href={`${getApiBase()}/ledger/v1/export`} download="aughor-ledger.jsonl" style={{ color: "var(--blue4)" }}>Download the ledger</a>
            <span>The governance events of every audit sink are read on the Audit page.</span>
          </div>
        </div>
      </Section>
    </Page>
  );
}
