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
 *
 * A card (CLARITY, 2026-10-12): the binding in force at the label's right end, the key's state as a chip, the
 * fields two to a row, one line on how the key is kept.
 */
import { useCallback, useEffect, useState } from "react";
import { clearOrgLLM, getOrgLLM, updateOrgLLM, type OrgLLMConfig } from "@/lib/api";
import { Card, Chip } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

import { FIELDS, Field, Note, SaveLine } from "./settings/parts";

const BACKENDS = ["", "openrouter", "anthropic", "gemini", "groq", "together", "ollama", "lmstudio"];
const KEYED = new Set(["openrouter", "anthropic", "gemini", "groq", "together"]);
const ROLES: Array<{ key: "coder" | "narrator" | "fast"; label: string; hint: string }> = [
  { key: "coder", label: "Coder model", hint: "SQL generation, structured reasoning" },
  { key: "narrator", label: "Narrator model", hint: "report synthesis, long-form prose" },
  { key: "fast", label: "Fast model", hint: "cheap per-phase interpret calls" },
];

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
    <Card label="Models & keys (BYOK)" testId="org-byok"
      right={cfg && (cfg.configured ? `this organisation's own · ${cfg.backend || "deployment default"}` : "the deployment's binding")}>
      <div style={FIELDS}>
        <Field label="Provider">
          <SelectField
            value={backend}
            aria-label="Organisation provider"
            onChange={(e) => { setSaved(false); setBackend(e.target.value); }}
          >
            {BACKENDS.map((b) => (
              <option key={b} value={b}>{b === "" ? "(deployment default)" : b}</option>
            ))}
          </SelectField>
        </Field>
        {backend && KEYED.has(backend) && (
          <Field label="API key" htmlFor="org-byok-key"
            meta={<Chip tone={keySet ? "up" : "amber"}>{keySet ? "set ✓" : keyUnreadable ? "stored, unreadable" : "not set"}</Chip>}>
            <Input
              id="org-byok-key"
              type="password"
              value={keyInput}
              placeholder={keySet ? "(unchanged)"
                : keyUnreadable ? "re-paste — the stored key cannot be decrypted"
                : "paste your key"}
              onChange={(e) => { setSaved(false); setKeyInput(e.target.value); }}
              autoComplete="off"
            />
          </Field>
        )}
        {backend && ROLES.map((r) => (
          <Field key={r.key} label={r.label} meta={<span>· {r.hint}</span>}>
            <Input
              value={models[r.key] ?? ""}
              placeholder="(backend default)"
              onChange={(e) => {
                setSaved(false);
                const v = e.target.value;
                setModels((prev) => ({ ...prev, [r.key]: v }));
              }}
            />
          </Field>
        ))}
      </div>
      {backend === "openrouter" && (
        <label className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
          color: "var(--t3)", marginTop: 8 }}>
          <Checkbox
            checked={allowPaid}
            onChange={(e) => setAllowPaid(e.target.checked)}
          />
          Allow paid models (off = free-tier models only)
        </label>
      )}
      <Note>
        The key is stored encrypted and never shown again; leave it blank to keep the current one. “Deployment default”
        uses the operator&apos;s configuration.
      </Note>
      <SaveLine saved={saved && !saving} error={error}>
        <Button variant="default" size="sm" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save models & keys"}
        </Button>
        {cfg?.configured && (
          <Button variant="ghost" size="sm" onClick={reset} disabled={saving}>
            Clear (use deployment default)
          </Button>
        )}
      </SaveLine>
    </Card>
  );
}
