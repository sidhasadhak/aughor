"use client";

/**
 * OrgByokSection — Settings ▸ Organization: "Models & keys (BYOK)" (CI-5b).
 *
 * Edits the ORG's own inference binding: its provider, per-role models, and its own
 * API key — stored encrypted server-side, resolved per-request above the deployment
 * config. Deliberately not the deployment Settings → Inference form: this one writes
 * a tenant row, never the global config, so saving here can never reload another
 * tenant's providers (or cancel an in-flight exploration).
 *
 * Key handling: the server never returns a key value — only which keys are set — so
 * the input is write-only. An empty input on save means "unchanged", and the
 * explicit Clear action removes the whole row (back to the deployment binding).
 */
import { useCallback, useEffect, useState } from "react";
import { clearOrgLLM, getOrgLLM, updateOrgLLM, type OrgLLMConfig } from "@/lib/api";
import { Button } from "@/components/ui/button";

const BACKENDS = ["", "openrouter", "anthropic", "gemini", "groq", "together", "ollama", "lmstudio"];
const KEYED = new Set(["openrouter", "anthropic", "gemini", "groq", "together"]);
const ROLES: Array<{ key: "coder" | "narrator" | "fast"; label: string; hint: string }> = [
  { key: "coder", label: "Coder model", hint: "SQL generation, structured reasoning" },
  { key: "narrator", label: "Narrator model", hint: "report synthesis, long-form prose" },
  { key: "fast", label: "Fast model", hint: "cheap per-phase interpret calls" },
];

const labelStyle: React.CSSProperties = { fontSize: 11, color: "var(--t3)", marginBottom: 4, display: "block" };
const hintStyle: React.CSSProperties = { fontSize: 11, color: "var(--t4)", marginTop: 6 };
const gridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 };

export function OrgByokSection() {
  const [cfg, setCfg] = useState<OrgLLMConfig | null>(null);
  const [backend, setBackend] = useState("");
  const [models, setModels] = useState<Record<string, string>>({});
  const [keyInput, setKeyInput] = useState("");
  const [allowPaid, setAllowPaid] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const c = await getOrgLLM();
      setCfg(c);
      setBackend(c.backend || "");
      setModels(c.models || {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load model settings");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    setSaving(true); setError(""); setSaved(false);
    try {
      const patch: Parameters<typeof updateOrgLLM>[0] = { backend, models, allow_paid: allowPaid };
      // Write-only key: an empty input means "leave the stored key unchanged".
      if (backend && KEYED.has(backend) && keyInput.trim() !== "") {
        patch.keys = { [backend]: keyInput.trim() };
      }
      const c = await updateOrgLLM(patch);
      setCfg(c); setKeyInput(""); setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save model settings");
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setSaving(true); setError(""); setSaved(false);
    try {
      const c = await clearOrgLLM();
      setCfg(c); setBackend(""); setModels({}); setKeyInput("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to clear model settings");
    } finally {
      setSaving(false);
    }
  };

  // Three states. A stored key whose vault key is gone reported "set ✓" while every call
  // using it failed — the one reading that points away from the actual fault.
  const keyState = backend ? (cfg?.keys_state?.[backend]
    ?? (cfg?.keys_set?.[backend] ? "set" : "unset")) : "unset";
  const keySet = keyState === "set";
  const keyUnreadable = keyState === "unreadable";

  return (
    <div>
      <div className="aug-label" style={{ marginBottom: 10 }}>Models &amp; keys (BYOK)</div>
      <div style={gridStyle}>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <label style={labelStyle}>Provider</label>
          <select
            className="aug-input"
            value={backend}
            style={{ cursor: "pointer" }}
            onChange={(e) => { setSaved(false); setBackend(e.target.value); }}
          >
            {BACKENDS.map((b) => (
              <option key={b} value={b}>{b === "" ? "(deployment default)" : b}</option>
            ))}
          </select>
        </div>
        {backend && KEYED.has(backend) && (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <label style={labelStyle}>
              API key {keySet ? "· set ✓" : keyUnreadable ? "· stored, unreadable" : "· not set"}
            </label>
            <input
              className="aug-input"
              type="password"
              value={keyInput}
              placeholder={keySet ? "(unchanged)"
                : keyUnreadable ? "re-paste — the stored key cannot be decrypted"
                : "paste your key"}
              onChange={(e) => { setSaved(false); setKeyInput(e.target.value); }}
              autoComplete="off"
            />
          </div>
        )}
        {backend && ROLES.map((r) => (
          <div key={r.key} style={{ display: "flex", flexDirection: "column" }}>
            <label style={labelStyle}>{r.label}</label>
            <input
              className="aug-input"
              value={models[r.key] ?? ""}
              placeholder="(backend default)"
              onChange={(e) => {
                setSaved(false);
                const v = e.target.value;
                setModels((prev) => ({ ...prev, [r.key]: v }));
              }}
            />
            <div style={hintStyle}>{r.hint}</div>
          </div>
        ))}
      </div>
      {backend === "openrouter" && (
        <label style={{ ...hintStyle, display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={allowPaid}
            onChange={(e) => setAllowPaid(e.target.checked)}
          />
          Allow paid models (off = free-tier models only)
        </label>
      )}
      <div style={hintStyle}>
        Your organization&apos;s own provider binding. The key is stored encrypted and never
        shown again; leave it blank to keep the current one. “Deployment default” uses the
        operator&apos;s configuration.
      </div>
      {error && <div style={{ fontSize: 11, color: "var(--red4)", marginTop: 8 }}>{error}</div>}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
        <Button variant="default" size="sm" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save models & keys"}
        </Button>
        {cfg?.configured && (
          <Button variant="ghost" size="sm" onClick={reset} disabled={saving}>
            Clear (use deployment default)
          </Button>
        )}
        {saved && !saving && <span style={{ fontSize: 11, color: "var(--grn4)" }}>Saved ✓</span>}
      </div>
    </div>
  );
}
