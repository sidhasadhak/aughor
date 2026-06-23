"use client";

/**
 * InferencePanel — Settings → Inference. Choose & change the LLM provider,
 * models, base URLs and API keys at runtime (no restart). Keys are write-only:
 * the server stores them secretvault-encrypted and only ever reports whether a
 * key is set, so nothing sensitive round-trips back to the browser.
 */
import { useEffect, useState } from "react";
import { getLlmConfig, setLlmConfig, testLlmConfig, type LlmCapability, type LlmConfig } from "@/lib/api";

const BACKEND_LABEL: Record<string, string> = {
  ollama: "Ollama (local)",
  lmstudio: "LM Studio (local)",
  groq: "Groq",
  together: "Together AI",
  anthropic: "Anthropic",
};
const ROLE_LABEL: Record<string, string> = {
  coder: "Coder — SQL & reasoning",
  narrator: "Narrator — report prose",
  fast: "Fast — per-phase interprets",
};

// Where context goes (PLATFORM_ARCHITECTURE.md §5b.4) — the governance-relevant axis.
const PRIVACY_META: Record<string, { label: string; fg: string; bg: string; note: string }> = {
  local:            { label: "On-device", fg: "var(--grn5)", bg: "var(--grn1)", note: "Prompts stay on this machine." },
  private_endpoint: { label: "Private endpoint", fg: "var(--t2)", bg: "var(--bg-2)", note: "Prompts go to your own hosted endpoint." },
  public_api:       { label: "Public API", fg: "var(--amb5)", bg: "var(--amb1)", note: "Prompts are sent to a third-party API." },
};
const CACHE_NOTE: Record<string, string> = {
  explicit_breakpoint: "prefix-cacheable",
  auto_prefix: "auto prefix-cache",
  auto_prefix_unverified: "prefix-cache unverified",
  none: "no prefix cache",
};

function CapChip({ text, title }: { text: string; title?: string }) {
  return (
    <span title={title} style={{
      fontSize: 10, padding: "1px 6px", borderRadius: "var(--r1)", whiteSpace: "nowrap",
      background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t3)",
      fontFamily: "var(--font-mono)",
    }}>{text}</span>
  );
}

function CapabilityRow({ cap }: { cap: LlmCapability }) {
  const p = PRIVACY_META[cap.privacy_class] ?? PRIVACY_META.private_endpoint;
  const ctxK = cap.max_context >= 1000 ? `${Math.round(cap.max_context / 1000)}k ctx` : `${cap.max_context} ctx`;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 4, alignItems: "center" }}>
      <span title={p.note} style={{
        fontSize: 10, padding: "1px 6px", borderRadius: "var(--r1)", whiteSpace: "nowrap",
        background: p.bg, color: p.fg, fontWeight: 500,
      }}>{p.label}</span>
      <CapChip text={ctxK} title="model context window (drives payload caps)" />
      <CapChip text={CACHE_NOTE[cap.cache_mode] ?? cap.cache_mode} title={`cache_mode: ${cap.cache_mode}`} />
      {cap.tooling === "native_tools" && <CapChip text="tools" title="native tool calling" />}
      <CapChip text={cap.cost === "per_token" ? "$/token" : cap.cost} title={`cost: ${cap.cost}`} />
      {cap.token_accounting === "estimated" && <CapChip text="est. tokens" title="usage estimated (provider omits a usage block)" />}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", borderRadius: "var(--r2)", fontSize: 12,
  background: "var(--bg-1)", border: "1px solid var(--b1)", color: "var(--t1)",
  fontFamily: "var(--font-mono)",
};
const labelStyle: React.CSSProperties = { fontSize: 11, color: "var(--t3)", marginBottom: 4, display: "block" };

export function InferencePanel() {
  const [cfg, setCfg] = useState<LlmConfig | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [backend, setBackend] = useState("");
  const [models, setModels] = useState<Record<string, string>>({});
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({});
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; error?: string; model?: string } | null>(null);

  const load = () =>
    getLlmConfig()
      .then((c) => {
        setCfg(c);
        setBackend(c.backend);
        setModels({ ...c.models_set });
        setBaseUrls({ ...c.base_urls_set });
        setKeys({});
      })
      .catch((e) => setLoadErr(e instanceof Error ? e.message : String(e)));

  useEffect(() => { load(); }, []);

  if (loadErr) return <div style={{ fontSize: 12, color: "var(--red4)" }}>Inference config unavailable: {loadErr}</div>;
  if (!cfg) return <div style={{ fontSize: 12, color: "var(--t3)" }}>Loading…</div>;

  const isLocal = cfg.local_backends.includes(backend);
  const needsKey = cfg.needs_key.includes(backend);
  const defaults = cfg.default_models[backend] || {};
  const keySet = cfg.keys_set[backend];

  const onBackend = (b: string) => {
    // Models are backend-specific — reset overrides so the new backend uses its
    // own defaults (the user can re-enter a specific model below).
    setBackend(b);
    setModels({});
    setResult(null);
    setSaved(false);
  };

  const save = async () => {
    setSaving(true); setSaved(false); setResult(null);
    try {
      const next = await setLlmConfig({
        backend,
        models: { coder: models.coder || "", narrator: models.narrator || "", fast: models.fast || "" },
        base_urls: isLocal ? { [backend]: baseUrls[backend] || "" } : {},
        keys: Object.fromEntries(Object.entries(keys).filter(([, v]) => v && v.trim())),
      });
      setCfg(next);
      setBackend(next.backend);
      setModels({ ...next.models_set });
      setBaseUrls({ ...next.base_urls_set });
      setKeys({});
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) });
    }
    setSaving(false);
  };

  const test = async () => {
    setTesting(true); setResult(null);
    try {
      setResult(await testLlmConfig(backend, models.coder || undefined));
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) });
    }
    setTesting(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 520 }}>
      {/* Backend */}
      <div>
        <label style={labelStyle}>Provider</label>
        <select value={backend} onChange={(e) => onBackend(e.target.value)} style={{ ...inputStyle, fontFamily: "inherit" }}>
          {cfg.backends.map((b) => (
            <option key={b} value={b}>{BACKEND_LABEL[b] ?? b}</option>
          ))}
        </select>
      </div>

      {/* API key (hosted backends only) */}
      {needsKey && (
        <div>
          <label style={labelStyle}>
            API key{" "}
            <span style={{ color: keySet ? "var(--grn4)" : "var(--amb4)" }}>
              {keySet ? "· configured" : "· not set"}
            </span>
          </label>
          <input
            type="password"
            autoComplete="off"
            value={keys[backend] ?? ""}
            onChange={(e) => setKeys({ ...keys, [backend]: e.target.value })}
            placeholder={keySet ? "•••••••••• (leave blank to keep)" : "paste API key"}
            style={inputStyle}
          />
          <div style={{ fontSize: 10, color: "var(--t4)", marginTop: 4 }}>
            Stored encrypted on the server (secretvault). Save before testing a new key.
          </div>
        </div>
      )}

      {/* Base URL (local backends only) */}
      {isLocal && (
        <div>
          <label style={labelStyle}>Base URL</label>
          <input
            value={baseUrls[backend] ?? ""}
            onChange={(e) => setBaseUrls({ ...baseUrls, [backend]: e.target.value })}
            placeholder={cfg.base_urls[backend] || ""}
            style={inputStyle}
          />
        </div>
      )}

      {/* Models */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {(["coder", "narrator", "fast"] as const).map((role) => (
          <div key={role}>
            <label style={labelStyle}>{ROLE_LABEL[role]}</label>
            <input
              value={models[role] ?? ""}
              onChange={(e) => setModels({ ...models, [role]: e.target.value })}
              placeholder={defaults[role] || cfg.models[role] || "default"}
              style={inputStyle}
            />
            {cfg.capabilities?.[role] && <CapabilityRow cap={cfg.capabilities[role]} />}
          </div>
        ))}
        <div style={{ fontSize: 10, color: "var(--t4)" }}>
          Leave a model blank to use the provider's default (shown as the placeholder).
        </div>
        {(() => {
          // The bound models' privacy classes — a saved-config view (§5b.4 governance).
          const classes = new Set(Object.values(cfg.capabilities ?? {}).map((c) => c.privacy_class));
          if (classes.has("public_api")) {
            return (
              <div style={{
                fontSize: 10.5, lineHeight: 1.5, padding: "7px 10px", borderRadius: "var(--r2)",
                background: "var(--amb1)", color: "var(--amb5)", border: "1px solid var(--amb2)",
              }}>
                A bound model sends prompts to a third-party API. Schema, sample rows and findings
                in the prompt leave this machine — bind a local or private-endpoint model for
                data that must stay in-tenant.
              </div>
            );
          }
          return null;
        })()}
      </div>

      {/* Actions */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 2 }}>
        <button
          onClick={save}
          disabled={saving}
          style={{
            padding: "7px 16px", borderRadius: "var(--r2)", fontSize: 12, fontWeight: 500,
            background: "var(--blue4)", color: "#fff", border: "none",
            cursor: saving ? "default" : "pointer", opacity: saving ? 0.6 : 1,
          }}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={test}
          disabled={testing}
          style={{
            padding: "7px 14px", borderRadius: "var(--r2)", fontSize: 12,
            background: "var(--bg-2)", color: "var(--t2)", border: "1px solid var(--b1)",
            cursor: testing ? "default" : "pointer", opacity: testing ? 0.6 : 1,
          }}
        >
          {testing ? "Testing…" : "Test connection"}
        </button>
        {saved && <span style={{ fontSize: 11, color: "var(--grn4)" }}>✓ Saved</span>}
      </div>

      {/* Test / error result */}
      {result && (
        <div style={{
          padding: "8px 12px", borderRadius: "var(--r2)", fontSize: 11, lineHeight: 1.5,
          background: result.ok ? "var(--grn1)" : "var(--red1)",
          border: `1px solid ${result.ok ? "var(--grn2)" : "var(--red2)"}`,
          color: result.ok ? "var(--grn5)" : "var(--red4)",
          fontFamily: "var(--font-mono)", wordBreak: "break-word",
        }}>
          {result.ok
            ? `✓ ${BACKEND_LABEL[backend] ?? backend} responded${result.model ? ` (${result.model})` : ""}`
            : `✗ ${result.error || "test failed"}`}
        </div>
      )}
    </div>
  );
}
