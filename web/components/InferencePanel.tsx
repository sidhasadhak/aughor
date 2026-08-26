"use client";

/**
 * InferencePanel — Settings → Inference. Choose & change the LLM provider,
 * models, base URLs and API keys at runtime (no restart). Keys are write-only:
 * the server stores them secretvault-encrypted and only ever reports whether a
 * key is set, so nothing sensitive round-trips back to the browser.
 */
import { useCallback, useEffect, useState } from "react";
import { addLlmModel, cacheProbe, getLlmConfig, getLlmModels, removeLlmModel, setLlmConfig, testLlmConfig, type CacheProbeResult, type LlmCapability, type LlmConfig, type LlmModelCatalog, type LlmTestReport } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { formatCount } from "@/lib/format";
import { BACKEND_LABEL } from "@/lib/llmMeta";

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
      fontSize: 11, padding: "1px 6px", borderRadius: "var(--r1)", whiteSpace: "nowrap",
      background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t3)",
      fontFamily: "var(--font-mono)",
    }}>{text}</span>
  );
}

/** A context window, honestly formatted — 1M reads as "1M", not "1049k". */
function fmtCtx(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_048_576).toFixed(1)}M ctx`;
  return n >= 1000 ? `${Math.round(n / 1000)}k ctx` : `${n} ctx`;
}

/** Chips describing the model in the FIELD — not the one last saved.
 *
 *  `cap` is the server's profile for the SAVED binding (`_active_model`), so typing a new
 *  id left the *previous* model's chips sitting underneath it. That is how a paid,
 *  1M-context model came to display "free · 33k ctx": `free` was the old `:free` binding's
 *  tier and 33k is `_DEFAULT_CONTEXT`, the "model not recognised" fallback. A panel that
 *  labels a metered model free is the one error this screen must never make.
 *
 *  Truth order: the live catalogue first (it carries the real `context_length` and the real
 *  price, and we already fetch it for the datalist), then the server's declared profile for
 *  the axes a catalogue cannot answer — privacy, prefix-cache, tooling. */
function CapabilityRow({ cap, typed = "", saved = "", catalog = null }: {
  cap: LlmCapability;
  typed?: string;
  saved?: string;
  catalog?: LlmModelCatalog | null;
}) {
  const p = PRIVACY_META[cap.privacy_class] ?? PRIVACY_META.private_endpoint;
  const id = typed.trim();
  const entry = id ? (catalog?.models ?? []).find((m) => m.id === id) : undefined;
  const unsaved = !!id && id !== saved;

  const ctx = entry?.context ?? cap.max_context;
  const ctxK = fmtCtx(ctx);
  // `free` means two different things upstream: the catalogue knows the real PRICE, the
  // server marks the `:free` TIER. Prefer the price — that is what actually bills you.
  const cost: string = entry?.free !== undefined
    ? (entry.free ? "free" : "per_token")
    : id
      ? (id.endsWith(":free") ? "free" : "per_token")
      : cap.cost;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 4, alignItems: "center" }}>
      <span title={p.note} style={{
        fontSize: 11, padding: "1px 6px", borderRadius: "var(--r1)", whiteSpace: "nowrap",
        background: p.bg, color: p.fg, fontWeight: 500,
      }}>{p.label}</span>
      <CapChip text={ctxK} title={entry?.context
        ? `${formatCount(ctx)} tokens — from the ${catalog?.backend} catalogue`
        : "model context window (drives payload caps) — declared default, not measured"} />
      <CapChip text={CACHE_NOTE[cap.cache_mode] ?? cap.cache_mode} title={`cache_mode: ${cap.cache_mode}`} />
      {cap.tooling === "native_tools" && <CapChip text="tools" title="native tool calling" />}
      <CapChip text={cost === "per_token" ? "$/token" : cost} title={entry?.free !== undefined
        ? `cost: ${cost} — from the catalogue's own pricing`
        : `cost: ${cost}`} />
      {unsaved && <CapChip text="unsaved" title="these describe the id you typed — press Save to bind it" />}
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
  // Free-by-default: the OpenRouter suggestion list starts at the `:free` tier;
  // paid models stay one toggle away (and a typed id always works regardless).
  const [showPaid, setShowPaid] = useState(false);
  if (!catalog) return null;
  const custom = catalog.custom ?? [];
  const freeOnly = catalog.backend === "openrouter" && !showPaid;
  const listed = freeOnly ? catalog.models.filter(m => m.free) : catalog.models;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <datalist id={`llm-models-${catalog.backend}`}>
        {listed.map((m) => (
          <option key={m.id} value={m.id}>
            {[m.label ?? m.id,
              m.context ? `${Math.round(m.context / 1000)}k ctx` : "",
              m.free ? "free" : "paid"].filter(Boolean).join(" · ")}
          </option>
        ))}
      </datalist>

      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--t4)" }}>
        <span>
          {catalog.live
            ? `${catalog.live_count} models from ${BACKEND_LABEL[catalog.backend] ?? catalog.backend}`
            : custom.length > 0
              ? "no live list"
              : "no models — this list comes from the provider"}
          {custom.length > 0 && ` · ${custom.length} custom`}
        </span>
        {catalog.backend === "openrouter" && (
          <Button variant="ghost" size="sm" onClick={() => setShowPaid(v => !v)}
                  title={showPaid
                    ? "Suggest only :free models (the default posture)"
                    : "Also suggest paid models — binding one still needs an explicit ack"}
                  style={{ fontSize: 11, height: "auto", padding: "1px 6px" }}>
            {showPaid ? `all ${catalog.models.length} — hide paid` : `${listed.length} free — show paid`}
          </Button>
        )}
        <Button variant="ghost" size="sm" disabled={busy} onClick={onRefresh}
                style={{ fontSize: 11, height: "auto", padding: "1px 6px" }}>
          {busy ? "…" : "Refresh"}
        </Button>
      </div>

      {/* A failed live fetch is stated, not hidden. There is no built-in list behind
          it any more (2026-08-15) — the suggestions ARE the provider's own catalogue,
          so a failure means an empty picker, and saying so beats a silent blank. The
          field is free text either way: a known id can still be typed straight in. */}
      {!catalog.live && (error || catalog.error) && (
        <div style={{ fontSize: 11, color: "var(--amb4)" }}>
          Couldn’t reach {BACKEND_LABEL[catalog.backend] ?? catalog.backend} for its model
          list ({error || catalog.error}). Type a model id directly, or Refresh to retry.
        </div>
      )}

      {custom.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {custom.map((m) => (
            <span key={m} style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 11, fontFamily: "var(--font-mono)",
              background: "var(--bg-3)", border: "1px solid var(--b2)",
              borderRadius: "var(--r-chip)", padding: "1px 4px 1px 8px",
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
  const [result, setResult] = useState<LlmTestReport | null>(null);
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<CacheProbeResult | null>(null);
  const [catalog, setCatalog] = useState<LlmModelCatalog | null>(null);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogErr, setCatalogErr] = useState<string | null>(null);
  // Free-by-default: binding a paid OpenRouter model requires this explicit ack —
  // the server refuses without it, this checkbox is how the user grants it.
  const [paidAck, setPaidAck] = useState(false);

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
  // Always {} since 2026-08-15 — no backend ships a default model. Kept because the
  // payload still carries the key; it must never again put a model id in this form.
  const defaults = cfg.default_models[backend] || {};
  // Three states, not two. A key that is stored but cannot be decrypted answered
  // "configured" here while the provider rejected it — which sends a person to rotate a
  // key that was fine. `keys_state` names the real fault; `keys_set` is kept for older
  // payloads and now means USABLE.
  const keyState = cfg.keys_state?.[backend] ?? (cfg.keys_set[backend] ? "set" : "unset");
  const keySet = keyState === "set";
  const keyUnreadable = keyState === "unreadable";

  const onBackend = (b: string) => {
    // Models are backend-specific — a name tuned for the previous provider must never ride
    // along. What DID change: the bindings this operator already chose for `b` are restored
    // rather than cleared. Nothing is invented — an unconfigured backend still fills in
    // nothing, and the field stays free text — but re-selecting a provider no longer asks
    // for a model that was chosen here once already, and the same remembered value is what
    // lets the fallback chain dispatch to that backend at all.
    setBackend(b);
    setModels({ ...(cfg?.models_by_backend?.[b] ?? {}) });
    setResult(null);
    setSaved(false);
  };

  // Paid bindings among the typed role models (openrouter only — the `:free`
  // suffix is that catalog's tier marker; BYO-key backends are paid by design).
  const paidBindings = backend === "openrouter"
    ? Object.values(models).filter(m => m && m.trim() && !m.trim().endsWith(":free"))
    : [];

  const save = async () => {
    setSaving(true); setSaved(false); setResult(null);
    try {
      const next = await setLlmConfig({
        backend,
        models: { coder: models.coder || "", narrator: models.narrator || "", fast: models.fast || "" },
        base_urls: isLocal ? { [backend]: baseUrls[backend] || "" } : {},
        keys: Object.fromEntries(Object.entries(keys).filter(([, v]) => v && v.trim())),
        ...(paidBindings.length > 0 ? { allow_paid: paidAck } : {}),
      });
      setCfg(next);
      setBackend(next.backend);
      setModels({ ...next.models_set });
      setBaseUrls({ ...next.base_urls_set });
      setKeys({});
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setResult({ ok: false, backend, error: e instanceof Error ? e.message : String(e) });
    }
    setSaving(false);
  };

  const test = async () => {
    setTesting(true); setResult(null);
    try {
      setResult(await testLlmConfig(backend, undefined, true));
    } catch (e) {
      setResult({ ok: false, backend, error: e instanceof Error ? e.message : String(e) });
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
            <span style={{ color: keySet ? "var(--grn4)" : keyUnreadable ? "var(--red4)" : "var(--amb4)" }}>
              {keySet ? "· configured" : keyUnreadable ? "· stored, but unreadable" : "· not set"}
            </span>
          </label>
          <input
            type="password"
            autoComplete="off"
            value={keys[backend] ?? ""}
            onChange={(e) => setKeys({ ...keys, [backend]: e.target.value })}
            placeholder={keySet ? "•••••••••• (leave blank to keep)"
              : keyUnreadable ? "re-paste the key, or restore AUGHOR_SECRET_KEY"
              : "paste API key"}
            style={inputStyle}
          />
          <div style={{ fontSize: 11, color: keyUnreadable ? "var(--red4)" : "var(--t4)", marginTop: 4 }}>
            {keyUnreadable
              ? "A key is stored but cannot be decrypted — AUGHOR_SECRET_KEY is missing or has changed since it was saved. The key itself may be perfectly good; the provider will reject it either way."
              : "Stored encrypted on the server (secretvault). Save before testing a new key."}
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
              placeholder={cfg.models[role] || "pick a model"}
              catalog={catalog}
              listId={`llm-models-${backend}`}
              onKeep={keepModel}
              busy={catalogBusy}
            />
            {cfg.capabilities?.[role] && (
              <CapabilityRow
                cap={cfg.capabilities[role]}
                typed={models[role] ?? ""}
                saved={cfg.models[role] ?? ""}
                catalog={catalog}
              />
            )}
          </div>
        ))}

        <CatalogFooter
          catalog={catalog}
          busy={catalogBusy}
          error={catalogErr}
          onRefresh={() => loadCatalog(backend, true)}
          onRemove={removeModel}
        />

        <div style={{ fontSize: 11, color: "var(--t4)" }}>
          Every role needs a model — nothing is assumed, and a blank role fails its calls
          with a message saying so. Any model id works: the list is what this provider
          reports serving, not a restriction.
        </div>
        {paidBindings.length > 0 && (
          <div style={{
            fontSize: 11, lineHeight: 1.5, padding: "8px 10px", borderRadius: "var(--r2)",
            background: "var(--amb1)", color: "var(--amb5)", border: "1px solid var(--amb2)",
            display: "flex", flexDirection: "column", gap: 6,
          }}>
            <span>
              {paidBindings.length === 1
                ? <><code style={{ fontSize: 11 }}>{paidBindings[0]}</code> is a paid model</>
                : `${paidBindings.length} of these are paid models`}
              {" "}— free (<code style={{ fontSize: 11 }}>:free</code>) models are the
              default here, and every paid call bills your OpenRouter credit.
            </span>
            <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer" }}>
              <input type="checkbox" checked={paidAck}
                onChange={e => setPaidAck(e.target.checked)} />
              <span>Bind {paidBindings.length === 1 ? "it" : "them"} anyway — I accept the charges</span>
            </label>
          </div>
        )}
        {(() => {
          // The bound models' privacy classes — a saved-config view (§5b.4 governance).
          const classes = new Set(Object.values(cfg.capabilities ?? {}).map((c) => c.privacy_class));
          if (classes.has("public_api")) {
            return (
              <div style={{
                fontSize: 11, lineHeight: 1.5, padding: "7px 10px", borderRadius: "var(--r2)",
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
          disabled={saving || (paidBindings.length > 0 && !paidAck)}
          title={paidBindings.length > 0 && !paidAck
            ? "A paid model is bound — tick the acknowledgment above to save"
            : undefined}
          style={{
            padding: "7px 16px", borderRadius: "var(--r2)", fontSize: 12, fontWeight: 500,
            background: "var(--blue4)", color: "#fff", border: "none",
            cursor: saving || (paidBindings.length > 0 && !paidAck) ? "default" : "pointer",
            opacity: saving || (paidBindings.length > 0 && !paidAck) ? 0.6 : 1,
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
          {/* Per-model, because the roles can be bound to different models and a
              single headline would hide a narrator or fast binding that is broken. */}
          {result.results?.length ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <div style={{ fontWeight: 600 }}>
                {result.ok
                  ? `✓ ${BACKEND_LABEL[backend] ?? backend} — ${result.tested} model${result.tested === 1 ? "" : "s"} responded`
                  : `✗ ${result.failed} of ${result.tested} failed`}
              </div>
              {result.results.map((r) => (
                <div key={r.model} style={{ color: r.ok ? "inherit" : "var(--red4)" }}>
                  {r.ok ? "✓" : "✗"} {r.model}
                  <span style={{ opacity: 0.7 }}>
                    {" · "}{r.used_by.join(", ")}{r.ok && r.ms ? ` · ${Math.round(r.ms)}ms` : ""}
                  </span>
                  {!r.ok && r.error ? <div style={{ paddingLeft: 14 }}>{r.error}</div> : null}
                </div>
              ))}
            </div>
          ) : result.ok
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
