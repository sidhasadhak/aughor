"use client";

/**
 * OrgSettingsPanel — the Settings ▸ "Organization & Localization" form.
 *
 * Edits the app-wide OrgSettings singleton (identity + localization), and — when a
 * workspace is active — its per-workspace OVERRIDE (the hybrid scope: a workspace
 * value wins over the app default; a blank field inherits it). A set currency/industry
 * is in turn authoritative over what Aughor infers per connection (override-wins),
 * which is why blank = "use the inferred value".
 *
 * Redone to `aughor-v2/CLARITY.md` (2026-10-12): four figures first — the industries read, this quarter's
 * priorities, the owners the platform can reach, the Explorer's monthly budget — then what needs a person (an owner
 * nobody can reach), then the form as cards: what the one Save below them writes, then the sections that save
 * themselves (industries, the playbook, the agent policy, the organisation's own keys). The owners' list is its own
 * panel under this one (`OwnersPanel`); a link there is announced, and the figure and "Needs you" follow it.
 */
import { useCallback, useEffect, useState } from "react";
import {
  getCapabilities,
  getEffectiveSettings,
  getOrgAllows,
  getOrgSettings,
  getWorkspace,
  listOwners,
  updateOrgSettings,
  updateWorkspace,
  type IndustryChoice,
  type OrgAllowSetting,
  type OrgAllows,
  type OrgSettings,
  type OwnerEntry,
} from "@/lib/api";
import { setOrgSettingsCache } from "@/lib/orgSettings";
import { CHART_PALETTE_NAMES, chartPaletteLabel } from "@/lib/chartPalettes";
import { compactNumber, formatCount } from "@/lib/format";
import { Card, Chip, Figure, Figures, NeedsRow, NeedsYou, ONE_LINE, ROW } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { OrgByokSection } from "@/components/OrgByokSection";
import { AgentPolicySection } from "@/components/AgentPolicySection";
import { OrgIndustriesSection } from "@/components/OrgIndustriesSection";
import { OrgPlaybookSection } from "@/components/OrgPlaybookSection";
import { OrgPrioritiesSection } from "@/components/OrgPrioritiesSection";
import { OWNERS_CHANGED, usesLabel } from "@/components/OwnersPanel";
import { Loading } from "@/components/ui/states";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

import { Details, FIELDS, Field, Note, Pair, SaveLine, Stack, goTo, plural } from "./settings/parts";

const EMPTY: OrgSettings = {
  company_name: "", website: "", hq_location: "", industry: "",
  currency_code: "", timezone: "", date_format: "", fiscal_year_start_month: 1,
  chart_palette: "", chat_first_home: false, priorities: [],
};

const CURRENCIES = ["", "USD", "EUR", "GBP", "JPY", "CNY", "INR", "AUD", "CAD", "CHF", "SGD", "BRL", "ZAR"];
const DATE_FORMATS = ["", "YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY", "DD MMM YYYY"];
const TIMEZONES = [
  "", "UTC", "America/New_York", "America/Chicago", "America/Los_Angeles",
  "Europe/London", "Europe/Paris", "Europe/Berlin", "Asia/Kolkata", "Asia/Singapore",
  "Asia/Tokyo", "Asia/Shanghai", "Australia/Sydney",
];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const same = (a: OrgSettings, b: OrgSettings) => JSON.stringify(a) === JSON.stringify(b);

export function OrgSettingsPanel({ workspaceId, workspaceName }: { workspaceId?: string; workspaceName?: string }) {
  const [scope, setScope] = useState<"app" | "workspace">("app");
  const [s, setS] = useState<OrgSettings>(EMPTY);
  // What the form was loaded with — so the Save line can say an edit is not saved yet.
  const [loaded, setLoaded] = useState<OrgSettings>(EMPTY);
  // ROADMAP §3.65 — each choice's answer as the server reads it, so one never set shows what it does now
  const [allows, setAllows] = useState<OrgAllows | null>(null);
  const [appDefaults, setAppDefaults] = useState<OrgSettings>(EMPTY);
  const [loading, setLoading] = useState(true);
  // BYOK is a per-ORG override. With a single tenant it can only restate the
  // deployment's own Settings ▸ Models, so it stays hidden rather than presenting a
  // second, identical set of model fields.
  const [multiTenant, setMultiTenant] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  // What the figures say, handed up by the section that reads it (the industries), or read here (the owners — their
  // list is its own panel, and announces a change).
  const [industries, setIndustries] = useState<IndustryChoice | null>(null);
  const [owners, setOwners] = useState<OwnerEntry[] | null>(null);
  const [ownersFailed, setOwnersFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const app = await getOrgSettings();
      setAppDefaults(app);
      getOrgAllows().then(setAllows).catch(() => setAllows(null));
      if (scope === "workspace" && workspaceId) {
        const ws = await getWorkspace(workspaceId);
        const over = { ...EMPTY, ...((ws.settings_override ?? {}) as Partial<OrgSettings>) };
        setS(over); setLoaded(over);
      } else {
        setS(app); setLoaded(app);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, [scope, workspaceId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    getCapabilities()
      .then(c => setMultiTenant(!!c.multi_tenant))
      .catch(() => setMultiTenant(false));   // unknown ⇒ hide, never offer a dead control
  }, []);

  const readOwners = useCallback(() => {
    listOwners()
      .then(d => { setOwners(d.owners); setOwnersFailed(false); })
      .catch(() => setOwnersFailed(true));
  }, []);
  useEffect(() => {
    readOwners();
    window.addEventListener(OWNERS_CHANGED, readOwners);
    return () => window.removeEventListener(OWNERS_CHANGED, readOwners);
  }, [readOwners]);

  const save = async () => {
    setSaving(true); setError(""); setSaved(false);
    try {
      if (scope === "workspace" && workspaceId) {
        // Only fields the user actually set go into the override; everything else inherits.
        const override: Record<string, unknown> = {};
        (Object.keys(s) as (keyof OrgSettings)[]).forEach((k) => {
          const v = s[k];
          if (k === "fiscal_year_start_month") { if (v !== 1) override[k] = v; }
          else if (v !== "") override[k] = v;
        });
        await updateWorkspace(workspaceId, { settings_override: override });
      } else {
        await updateOrgSettings(s);
      }
      setSaved(true);
      await load();  // reflect server-side normalization (e.g. currency upper-cased)
      // Refresh the app-wide formatter cache so tables/dates pick up the new settings.
      getEffectiveSettings(workspaceId || undefined).then(setOrgSettingsCache).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const onChange = (k: keyof OrgSettings) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      const raw = e.target.value;
      setSaved(false);
      setS((prev) => ({ ...prev, [k]: k === "fiscal_year_start_month" ? Number(raw) : raw }));
    };

  const inheritPh = (k: keyof OrgSettings) =>
    scope === "workspace" && appDefaults[k] ? `Inherits: ${appDefaults[k]}` : "";

  const TextField = (k: keyof OrgSettings, label: string) => (
    <Field label={label} htmlFor={`org-${k}`}>
      <Input id={`org-${k}`} value={String(s[k] ?? "")} onChange={onChange(k)} placeholder={inheritPh(k)} />
    </Field>
  );

  const SettingSelect = (
    k: keyof OrgSettings, label: string, opts: Array<string | number>,
    render?: (o: string | number) => string,
  ) => (
    <Field label={label}>
      <SelectField value={String(s[k] ?? "")} onChange={onChange(k)} aria-label={label} style={{ cursor: "pointer" }}>
        {opts.map((o) => (
          <option key={String(o)} value={String(o)}>
            {render ? render(o) : (o === "" ? (scope === "workspace" ? "(inherit)" : "(none)") : String(o))}
          </option>
        ))}
      </SelectField>
    </Field>
  );

  /** A yes/no setting. Its own helper because `onChange` reads `value`, and a
      checkbox carries its state on `checked`. */
  const BoolField = (k: keyof OrgSettings, label: string, hint: string) => (
    <label style={{ display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer" }}>
      <Checkbox
        checked={!!s[k]}
        onChange={(e) => { setSaved(false); setS((prev) => ({ ...prev, [k]: e.target.checked })); }}
        style={{ marginTop: 2, cursor: "pointer" }}
      />
      <span style={{ display: "flex", flexDirection: "column" }}>
        <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>{label}</span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{hint}</span>
      </span>
    </label>
  );

  // ROADMAP §3.65 — the four choices an organisation makes about what Aughor may do; everything else is the platform's.
  const ALLOWS: { k: OrgAllowSetting; label: string; hint: string }[] = [
    { k: "share_aggregates", label: "Share summary statistics with other installs",
      hint: "How often packs' claims held here. Names, ids and values never leave." },
    { k: "outside_row_model", label: "Send row text to an outside, cheaper model",
      hint: "TypeSafe's Jev judges text rows before your own strong model. Row text leaves this install." },
    { k: "reason_to_read_runs", label: "Ask for a reason before anyone reads a run's details",
      hint: "The reason is kept with who read it. Exporting the ledger asks too." },
    { k: "scheduled_model_work", label: "Let Aughor run model work on its own schedule",
      hint: "Nightly runs of each custom agent's checked questions, and re-tests after reviews, within the Spend budget." },
  ];
  const allowField = ({ k, label, hint }: { k: OrgAllowSetting; label: string; hint: string }) => {
    const chosen = s[k];
    const fromServer = chosen == null && !!allows?.[k]?.allowed;
    return (
      <label key={k} data-testid={`org-allows-${k}`} data-on={chosen ?? !!allows?.[k]?.allowed}
        style={{ display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer" }}>
        <Checkbox
          checked={chosen ?? !!allows?.[k]?.allowed}
          onChange={(e) => { setSaved(false); setS((prev) => ({ ...prev, [k]: e.target.checked })); }}
          style={{ marginTop: 2, cursor: "pointer" }}
          aria-label={label}
        />
        <span style={{ display: "flex", flexDirection: "column" }}>
          <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>{label}</span>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{hint}</span>
          {fromServer && (
            <span className="aug-fs-xs" data-testid={`org-allows-${k}-from-server`} style={{ color: "var(--amb4)" }}>
              On through this server&apos;s environment until you choose here.
            </span>
          )}
        </span>
      </label>
    );
  };

  if (loading) return <Loading what="settings" />;

  const app = scope === "app";
  const dirty = !same(s, loaded);

  // ── The figures, and what needs a person ─────────────────────────────────────────────────────────────────────
  const unresolved = (owners ?? []).filter(o => !o.resolved);
  const reachable = (owners ?? []).length - unresolved.length;
  const priorities = (appDefaults.priorities ?? []).filter(p => p.metric.trim());
  const kept = industries?.industries ?? null;
  const shippedName = (id: string) => industries?.shipped.find(i => i.id === id)?.name ?? id;
  const savedBudget = appDefaults.exploration_monthly_tokens ?? 0;

  return (
    <Stack testId="org-settings">
      <Figures testId="org-figures">
        <Figure label="Industries" testId="fig-industries"
          value={!industries ? "—" : !industries.shipped.length ? "None" : kept === null ? "Every" : `${kept.length} of ${industries.shipped.length}`}
          sub={!industries ? "not read"
            : !industries.shipped.length ? "no industry package ships"
            : kept === null ? "each connection's, detected from its data"
            : kept.length ? <span style={ONE_LINE} title={kept.map(shippedName).join(", ")}>{kept.map(shippedName).join(" · ")}</span>
            : "none — shared knowledge only"} />
        <Figure label="Priorities" testId="fig-priorities" value={formatCount(priorities.length)}
          sub={priorities.length
            ? <span style={ONE_LINE} title={priorities.map(p => p.metric).join(", ")}>{priorities.map(p => p.metric).join(" · ")}</span>
            : "none set this quarter"} />
        <Figure label="Owners reachable" testId="fig-owners" tone={unresolved.length ? "amber" : undefined}
          value={owners === null ? "—" : `${reachable} of ${owners.length}`}
          sub={ownersFailed && owners === null ? "could not be read"
            : owners === null ? "reading…"
            : unresolved.length ? `${unresolved.length} unresolved`
            : owners.length ? "every owner reachable" : "no declaration names an owner"} />
        <Figure label="Exploration budget" testId="fig-budget"
          value={savedBudget > 0 ? compactNumber(savedBudget) : "None"}
          title={savedBudget > 0 ? `${formatCount(savedBudget)} model tokens a month` : undefined}
          sub={savedBudget > 0 ? "model tokens a month, every connection" : "the Explorer's own runs have no monthly cap"} />
      </Figures>

      <NeedsYou testId="org-needs"
        empty={ownersFailed && owners === null ? "Nothing needs you that could be read · the owners could not be read"
          : "Nothing needs you · every owner the declarations name is reachable"}>
        {unresolved.length > 0 && (
          <NeedsRow key="owners" testId="needs-owners"
            title={`${plural(unresolved.length, "owner")} ${unresolved.length === 1 ? "is" : "are"} unresolved`}
            detail={`${unresolved.map(o => `${o.owner_text} · ${usesLabel(o)}`).join("  ·  ")} — a question for ${unresolved.length === 1 ? "it" : "them"} has nowhere to go`}
            actions={<Button size="xs" variant="secondary"
              onClick={() => goTo("settings-owners", "[data-owner-unlinked] input")}>Link</Button>} />
        )}
      </NeedsYou>

      {workspaceId && (
        <div style={{ ...ROW, gap: 6 }}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)", marginRight: 2 }}>Scope</span>
          {(["app", "workspace"] as const).map((sc) => (
            <Button
              key={sc}
              variant={scope === sc ? "secondary" : "ghost"}
              size="xs"
              onClick={() => { setSaved(false); setScope(sc); }}
            >
              {sc === "app" ? "App default" : (workspaceName || "This workspace")}
            </Button>
          ))}
          {scope === "workspace" && (
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              Overrides for <b>{workspaceName}</b>. Blank fields inherit the app default; a set value also
              wins over what Aughor infers from the data.
            </span>
          )}
        </div>
      )}

      {/* Identity · Localization */}
      <Pair>
        <Card label="Organization">
          <div style={FIELDS}>
            {TextField("company_name", "Company name")}
            {TextField("website", "Website")}
            {TextField("hq_location", "HQ location")}
            {TextField("industry", "Industry")}
          </div>
          <Note>Steers briefings, metric recipes and exploration. A set industry overrides what Aughor infers.</Note>
        </Card>
        <Card label="Localization">
          <div style={FIELDS}>
            {SettingSelect("currency_code", "Reporting currency", CURRENCIES)}
            {SettingSelect("timezone", "Timezone", TIMEZONES)}
            {SettingSelect("date_format", "Date format", DATE_FORMATS)}
            {SettingSelect("fiscal_year_start_month", "Fiscal year starts", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], (m) => MONTHS[(m as number) - 1])}
          </div>
          <Note>Empty = inferred from the data; a set currency renders every figure in it.</Note>
        </Card>
      </Pair>

      {/* CB-6 — the quarter's priorities, written by people; saved with the organisation settings. */}
      {app && (
        <OrgPrioritiesSection value={s.priorities ?? []} onChange={(next) => { setSaved(false); setS((prev) => ({ ...prev, priorities: next })); }} />
      )}

      <Pair>
        <Card label="Display">
          <div style={FIELDS}>
            {SettingSelect("chart_palette", "Chart palette", ["", ...CHART_PALETTE_NAMES], (p) => chartPaletteLabel(String(p)))}
          </div>
          <Note>“Default” follows the light or dark theme.</Note>
          <div style={{ marginTop: 12 }}>
            {BoolField(
              "chat_first_home",
              "Open on the conversation",
              "Land on the chat; the workbench stays one click away.",
            )}
          </div>
        </Card>

        {/* Arc MC, MC-6 — how many approved headline metrics a Briefing measures (the user's call, 2026-10-26: 24 by
            default). A workspace may set its own. */}
        <Card label="Briefing">
          <div style={FIELDS}>
            <Field label="Headline metrics per Briefing" htmlFor="org-briefing-cap">
              <Input id="org-briefing-cap" inputMode="numeric" placeholder="default"
                value={s.briefing_metric_cap ? String(s.briefing_metric_cap) : ""}
                onChange={(e) => {
                  setSaved(false);
                  const n = Number(e.target.value.replace(/[, ]/g, ""));
                  setS((prev) => ({ ...prev, briefing_metric_cap: Number.isFinite(n) && n > 0 ? Math.min(60, Math.round(n)) : 0 }));
                }} />
            </Field>
          </div>
          <Note>Empty = the default: 24 while the Briefing reads by area, 12 otherwise. Each one is three warehouse queries per Briefing.</Note>
        </Card>

        {/* The exploration principles §7 — the organisation's monthly budget for what the Explorer spends on its
            own initiative. A connection may set its own in the Catalog; the tighter holds. */}
        {app && (
          <Card label="Exploration budget">
            <div style={FIELDS}>
              <Field label="Monthly budget (model tokens)" htmlFor="org-exploration-budget">
                <Input id="org-exploration-budget" inputMode="numeric" placeholder="none"
                  value={s.exploration_monthly_tokens ? String(s.exploration_monthly_tokens) : ""}
                  onChange={(e) => {
                    setSaved(false);
                    const n = Number(e.target.value.replace(/[, ]/g, ""));
                    setS((prev) => ({ ...prev, exploration_monthly_tokens: Number.isFinite(n) && n > 0 ? Math.round(n) : 0 }));
                  }} />
              </Field>
            </div>
            <Note>What the Explorer spends on its own each month, across every connection. Empty = no budget.</Note>
            <Details>
              A connection may set its own in the Catalog; the tighter holds, and a held run says so. A person&apos;s own
              Start is capped at what is left, and once it is spent asks before it runs.
            </Details>
          </Card>
        )}
      </Pair>

      {app && (
        <Pair>
          <Card label="What Aughor may do">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }} data-testid="org-allows">
              {ALLOWS.map(allowField)}
            </div>
            <Note>Off unless chosen here. Everything else Aughor does is part of the platform, not a switch.</Note>
          </Card>
        </Pair>
      )}

      <SaveLine saved={saved && !saving} error={error} testId="org-save">
        <Button variant="default" size="sm" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {dirty && !saving && <Chip tone="amber">unsaved changes</Chip>}
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          {app ? "Saves everything above" : `Saves ${workspaceName || "this workspace"}'s overrides above`}
        </span>
      </SaveLine>

      {/* Industries (IP-2) — the installer's question, deployment-wide, so app scope only. It saves on
          its own: the choice is a server file, not a field of the settings row. The playbook sits BESIDE
          the industries because that is the only lever a person has over it: its entries arrive from the
          industry packages this org installs, not from anything typed here. It used to be a top-level nav
          door of its own, which promised a screen people would browse — measured 2026-09-19, 55% of its
          rows were Verifier rule-outs and 0 of 878 carried the success rate that would make browsing worth
          it. The user's call, and the right one: this is org configuration, not a plane of the product. */}
      {app && (
        <Pair>
          <OrgIndustriesSection onChoice={setIndustries} />
          <OrgPlaybookSection />
        </Pair>
      )}

      {/* DE-2b — what an outside agent (MCP) may do here. Every install has the policy, so it is not
          gated on multi-tenancy; it saves itself, like the BYOK block, because it is its own row. */}
      {app && <AgentPolicySection />}

      {/* Models & keys (CI-5b) — org scope AND multi-tenant only. Single-tenant
          deployments configure models in Settings ▸ Models; showing this there would
          be two places to set the same three fields, one of which cannot differ. */}
      {app && multiTenant && <OrgByokSection />}
    </Stack>
  );
}
