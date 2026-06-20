"use client";

/**
 * OrgSettingsPanel — the Settings ▸ "Organization & Localization" form.
 *
 * Edits the app-wide OrgSettings singleton (identity + localization), and — when a
 * workspace is active — its per-workspace OVERRIDE (the hybrid scope: a workspace
 * value wins over the app default; a blank field inherits it). A set currency/industry
 * is in turn authoritative over what Aughor infers per connection (override-wins),
 * which is why blank = "use the inferred value".
 */
import { useCallback, useEffect, useState } from "react";
import {
  getEffectiveSettings,
  getOrgSettings,
  getWorkspace,
  updateOrgSettings,
  updateWorkspace,
  type OrgSettings,
} from "@/lib/api";
import { setOrgSettingsCache } from "@/lib/orgSettings";
import { CHART_PALETTE_NAMES, chartPaletteLabel } from "@/lib/chartPalettes";

const EMPTY: OrgSettings = {
  company_name: "", website: "", hq_location: "", industry: "",
  currency_code: "", timezone: "", date_format: "", fiscal_year_start_month: 1,
  chart_palette: "",
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

const labelStyle: React.CSSProperties = { fontSize: 11, color: "var(--t3)", marginBottom: 4, display: "block" };
const hintStyle: React.CSSProperties = { fontSize: 10, color: "var(--t4)", marginTop: 6 };
const gridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 };

export function OrgSettingsPanel({ workspaceId, workspaceName }: { workspaceId?: string; workspaceName?: string }) {
  const [scope, setScope] = useState<"app" | "workspace">("app");
  const [s, setS] = useState<OrgSettings>(EMPTY);
  const [appDefaults, setAppDefaults] = useState<OrgSettings>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const app = await getOrgSettings();
      setAppDefaults(app);
      if (scope === "workspace" && workspaceId) {
        const ws = await getWorkspace(workspaceId);
        setS({ ...EMPTY, ...((ws.settings_override ?? {}) as Partial<OrgSettings>) });
      } else {
        setS(app);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, [scope, workspaceId]);

  useEffect(() => { void load(); }, [load]);

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
    <div style={{ display: "flex", flexDirection: "column" }}>
      <label style={labelStyle}>{label}</label>
      <input className="aug-input" value={String(s[k] ?? "")} onChange={onChange(k)} placeholder={inheritPh(k)} />
    </div>
  );

  const SelectField = (
    k: keyof OrgSettings, label: string, opts: Array<string | number>,
    render?: (o: string | number) => string,
  ) => (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <label style={labelStyle}>{label}</label>
      <select className="aug-input" value={String(s[k] ?? "")} onChange={onChange(k)} style={{ cursor: "pointer" }}>
        {opts.map((o) => (
          <option key={String(o)} value={String(o)}>
            {render ? render(o) : (o === "" ? (scope === "workspace" ? "(inherit)" : "(none)") : String(o))}
          </option>
        ))}
      </select>
    </div>
  );

  if (loading) return <div style={{ fontSize: 12, color: "var(--t3)" }}>Loading…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 560 }}>
      {workspaceId && (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--t3)", marginRight: 2 }}>Scope</span>
          {(["app", "workspace"] as const).map((sc) => (
            <button
              key={sc}
              className={`aug-btn aug-btn-sm ${scope === sc ? "aug-btn-secondary" : "aug-btn-ghost"}`}
              onClick={() => { setSaved(false); setScope(sc); }}
            >
              {sc === "app" ? "App default" : (workspaceName || "This workspace")}
            </button>
          ))}
        </div>
      )}
      {scope === "workspace" && (
        <div style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.5 }}>
          Overrides for <b>{workspaceName}</b>. Blank fields inherit the app default; a set value also
          wins over what Aughor infers from the data.
        </div>
      )}

      {/* Identity */}
      <div>
        <div className="aug-label" style={{ marginBottom: 10 }}>Organization</div>
        <div style={gridStyle}>
          {TextField("company_name", "Company name")}
          {TextField("website", "Website")}
          {TextField("hq_location", "HQ location")}
          {TextField("industry", "Industry")}
        </div>
        <div style={hintStyle}>
          Industry &amp; company context steer the intelligence (briefings, metric recipes, exploration).
          A set industry overrides what Aughor infers.
        </div>
      </div>

      {/* Localization */}
      <div>
        <div className="aug-label" style={{ marginBottom: 10 }}>Localization</div>
        <div style={gridStyle}>
          {SelectField("currency_code", "Reporting currency", CURRENCIES)}
          {SelectField("timezone", "Timezone", TIMEZONES)}
          {SelectField("date_format", "Date format", DATE_FORMATS)}
          {SelectField("fiscal_year_start_month", "Fiscal year starts", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], (m) => MONTHS[(m as number) - 1])}
        </div>
        <div style={hintStyle}>
          A set currency renders all figures in that currency (briefings, metrics, tables). Empty = inferred from the data.
        </div>
      </div>

      {/* Appearance */}
      <div>
        <div className="aug-label" style={{ marginBottom: 10 }}>Appearance</div>
        <div style={gridStyle}>
          {SelectField("chart_palette", "Chart palette", ["", ...CHART_PALETTE_NAMES], (p) => chartPaletteLabel(String(p)))}
        </div>
        <div style={hintStyle}>Colour scheme for charts. “Default” uses the app theme palette (adapts to light/dark).</div>
      </div>

      {error && <div style={{ fontSize: 11, color: "var(--red4)" }}>{error}</div>}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="aug-btn aug-btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {saved && !saving && <span style={{ fontSize: 11, color: "var(--grn4)" }}>Saved ✓</span>}
      </div>
    </div>
  );
}
