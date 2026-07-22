"use client";

/**
 * InferencePanel — Settings → Inference. Choose & change the LLM provider,
 * models, base URLs and API keys at runtime (no restart). Keys are write-only:
 * the server stores them secretvault-encrypted and only ever reports whether a
 * key is set, so nothing sensitive round-trips back to the browser.
 */
import { useCallback, useEffect, useState } from "react";
import { addLlmModel, cacheProbe, getLlmConfig, getLlmModels, removeLlmModel, setLlmConfig, testLlmConfig, type CacheProbeResult, type LlmCapability, type LlmConfig, type LlmModelCatalog } from "@/lib/api";
import { Button } from "@/components/ui/button";

const BACKEND_LABEL: Record<string, string> = {
  ollama: "Ollama (local)",
  lmstudio: "LM Studio (local)",
  groq: "Groq",
  together: "Together AI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  openrouter: "OpenRouter",
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

/** A model id field: free text, with the backend's catalogue as suggestions.
 *
 *  Deliberately an input+datalist rather than a select. Model catalogues change
 *  weekly and a closed dropdown that has gone stale means "you cannot use the
 *  model you are paying for" — the list should help, never gate. "Keep" pins a
 *  typed id into the list for next time. */
function ModelField({ value, onChange, placeholder, catalog, listId, onKeep, busy }: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  catalog: LlmModelCatalog | null;
  listId: string;
  onKeep: (model: string) => void;
  busy: boolean;
}) {
  const trimmed = value.trim();
  const known = new Set((catalog?.models ?? []).map((m) => m.id));
  const isCustom = (catalog?.custom ?? []).includes(trimmed);
  const canKeep = !!trimmed && !isCustom && !known.has(trimmed);

  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        list={listId}
        spellCheck={false}
        autoComplete="off"
        style={{ ...inputStyle, flex: 1 }}
      />
      {canKeep && (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => onKeep(trimmed)}
          title="Keep this model in the list for next time"
          style={{ fontSize: 11, whiteSpace: "nowrap" }}
        >
          + Keep
        </Button>
      )}
    </div>
  );
}

/** The shared <datalist> plus the catalogue's provenance and custom entries. */
function CatalogFooter({ catalog, busy, error, onRefresh, onRemove }: {
  catalog: LlmModelCatalog | null;
  busy: boolean;
  error: string | null;
  onRefresh: () => void;
  onRemove: (model: string) => void;
}) {
  if (!catalog) return null;
  const custom = catalog.custom ?? [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <datalist id={`llm-models-${catalog.backend}`}>
        {catalog.models.map((m) => (
          <option key={m.id} value={m.id}>
            {[m.label ?? m.id,
              m.context ? `${Math.round(m.context / 1000)}k ctx` : "",
              m.free ? "free" : ""].filter(Boolean).join(" · ")}
          </option>
        ))}
      </datalist>

      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, color: "var(--t4)" }}>
        <span>
          {catalog.live
            ? `${catalog.live_count} models from ${BACKEND_LABEL[catalog.backend] ?? catalog.backend}`
            : `${catalog.models.length} built-in suggestions`}
          {custom.length > 0 && ` · ${custom.length} custom`}
        </span>
        <Button variant="ghost" size="sm" disabled={busy} onClick={onRefresh}
                style={{ fontSize: 10, height: "auto", padding: "1px 6px" }}>
          {busy ? "…" : "Refresh"}
        </Button>
      </div>

      {/* A failed live fetch is stated, not hidden — otherwise the built-in
          floor silently poses as the real catalogue. */}
      {!catalog.live && (error || catalog.error) && (
        <div style={{ fontSize: 10, color: "var(--amb4)" }}>
          Live list unavailable ({error || catalog.error}) — showing built-in suggestions.
        </div>
      )}

      {custom.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {custom.map((m) => (
            <span key={m} style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 10, fontFamily: "var(--font-mono)",
              background: "var(--bg-3)", border: "1px solid var(--b2)",
              borderRadius: "var(--r-pill)", padding: "1px 4px 1px 8px",
            }}>
              {m}
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => onRemove(m)}
                title={`Remove ${m} from the list`}
                style={{ fontSize: 11, lineHeight: 1, height: "auto",
                         padding: "0 4px", color: "var(--t3)" }}
              >
                ×
              </Button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

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
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<CacheProbeResult | null>(null);
  const [catalog, setCatalog] = useState<LlmModelCatalog | null>(null);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogErr, setCatalogErr] = useState<string | null>(null);

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

  const loadCatalog = useCallback((b: string, refresh = false) => {
    if (!b) return;
    setCatalogBusy(true);
    setCatalogErr(null);
    getLlmModels(b, refresh)
      .then((c) => setCatalog(c))
      .catch((e) => setCatalogErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setCatalogBusy(false));
  }, []);

  useEffect(() => { load(); }, []);

  // Refetch when the provider changes — a catalogue belongs to its backend, and
  // showing Anthropic's models while OpenRouter is selected would be worse than
  // showing none. State is only touched in the callbacks, and `ignore` drops a
  // late response: switching provider twice quickly could otherwise land the
  // first fetch after the second and show the wrong backend's models.
  useEffect(() => {
    if (!backend) return;
    let ignore = false;
    getLlmModels(backend)
      .then((c) => { if (!ignore) { setCatalog(c); setCatalogErr(null); } })
      .catch((e) => { if (!ignore) setCatalogErr(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!ignore) setCatalogBusy(false); });
    return () => { ignore = true; };
  }, [backend]);

  const keepModel = (model: string) => {
    if (!backend) return;
    setCatalogBusy(true);
    addLlmModel(backend, model)
      .then(() => loadCatalog(backend))
      .catch((e) => { setCatalogErr(e instanceof Error ? e.message : String(e)); setCatalogBusy(false); });
  };

  const removeModel = (model: string) => {
    if (!backend) return;
    setCatalogBusy(true);
    removeLlmModel(backend, model)
      .then(() => loadCatalog(backend))
      .catch((e) => { setCatalogErr(e instanceof Error ? e.message : String(e)); setCatalogBusy(false); });
  };

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

  const runProbe = async () => {
    setProbing(true); setProbe(null);
    try {
      const r = await cacheProbe("coder");
      setProbe(r);
      await load();   // the verdict is persisted → reload so the capability chips update
    } catch (e) {
      setProbe({ ok: false, backend, model: models.coder || "", error: e instanceof Error ? e.message : String(e) });
    }
    setProbing(false);
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
            <ModelField
              value={models[role] ?? ""}
              onChange={(v) => setModels({ ...models, [role]: v })}
              placeholder={defaults[role] || cfg.models[role] || "default"}
              catalog={catalog}
              listId={`llm-models-${backend}`}
              onKeep={keepModel}
              busy={catalogBusy}
            />
            {cfg.capabilities?.[role] && <CapabilityRow cap={cfg.capabilities[role]} />}
          </div>
        ))}

        <CatalogFooter
          catalog={catalog}
          busy={catalogBusy}
          error={catalogErr}
          onRefresh={() => loadCatalog(backend, true)}
          onRemove={removeModel}
        />

        <div style={{ fontSize: 10, color: "var(--t4)" }}>
          Leave a model blank to use the provider&apos;s default (shown as the placeholder).
          Any model id works — the list is a suggestion, not a restriction.
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
        <button
          onClick={runProbe}
          disabled={probing}
          title="Measure whether this backend reuses a shared prompt prefix across requests, and record the verdict"
          style={{
            padding: "7px 14px", borderRadius: "var(--r2)", fontSize: 12,
            background: "var(--bg-2)", color: "var(--t2)", border: "1px solid var(--b1)",
            cursor: probing ? "default" : "pointer", opacity: probing ? 0.6 : 1,
          }}
        >
          {probing ? "Measuring…" : "Measure prefix cache"}
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

      {/* Prefix-cache probe verdict */}
      {probe && (() => {
        const ok = probe.ok && probe.verdict;
        const reuse = probe.verdict === "reuse_active";
        const tone = !ok ? { bg: "var(--red1)", fg: "var(--red4)", bd: "var(--red2)" }
          : reuse ? { bg: "var(--grn1)", fg: "var(--grn5)", bd: "var(--grn2)" }
          : probe.verdict === "no_reuse" ? { bg: "var(--amb1)", fg: "var(--amb5)", bd: "var(--amb2)" }
          : { bg: "var(--bg-2)", fg: "var(--t2)", bd: "var(--b1)" };
        const headline = !ok ? `✗ ${probe.error || "probe failed"}`
          : reuse ? "✓ Prefix cache reused — prefix-aligned prompts pay off here"
          : probe.verdict === "no_reuse" ? "✗ No cross-request prefix reuse — prefix alignment won't help this binding"
          : "~ Inconclusive — measurement was ambiguous; left as declared";
        return (
          <div style={{
            padding: "8px 12px", borderRadius: "var(--r2)", fontSize: 11, lineHeight: 1.55,
            background: tone.bg, color: tone.fg, border: `1px solid ${tone.bd}`,
            fontFamily: "var(--font-mono)", wordBreak: "break-word",
          }}>
            <div>{headline}</div>
            {ok && probe.warm_median_ms != null && (
              <div style={{ opacity: 0.85, marginTop: 3 }}>
                warm {probe.warm_median_ms}ms vs cold {probe.cold_median_ms}ms · ratio {probe.ratio}
                {probe.cache_mode ? ` · recorded cache_mode=${probe.cache_mode}` : ""}
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
