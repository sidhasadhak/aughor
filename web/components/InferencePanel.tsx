"use client";

/**
 * InferencePanel — Settings → Models. Choose & change the LLM provider,
 * models, base URLs and API keys at runtime (no restart). Keys are write-only:
 * the server stores them secretvault-encrypted and only ever reports whether a
 * key is set, so nothing sensitive round-trips back to the browser.
 *
 * Redone to `aughor-v2/CLARITY.md` (2026-10-12): what is in force first, as four figures — the provider, the roles
 * bound, the fallback, the keys — then what needs a person (a provider with no usable key, a role with no model, a
 * fallback that would be skipped, a bound model with no price), then the form: the provider and its roles beside the
 * fallback, and one Save with the tools beside it. The figures and "Needs you" read the SAVED configuration; the form
 * below is the draft.
 */
import { useCallback, useEffect, useState } from "react";
import {
  addLlmModel, cacheProbe, getLlmConfig, getLlmModels, getUsageReport, removeLlmModel, setLlmConfig, testLlmConfig,
  type CacheProbeResult, type LlmCapability, type LlmConfig, type LlmModelCatalog, type LlmTestReport, type UsageReport,
} from "@/lib/api";
import { Card, Chip, Figure, Figures, NeedsRow, NeedsYou, ONE_LINE, ROW, type Tone } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { formatCount } from "@/lib/format";
import { BACKEND_LABEL } from "@/lib/llmMeta";
import { requestTab } from "@/lib/navigate";
import { Loading, ReadFailed } from "@/components/ui/states";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

import { FIELDS, Field, Note, Pair, Stack, ToolsMenu, goTo, plural } from "./settings/parts";

const ROLES = ["coder", "narrator", "fast"] as const;
const ROLE_NAME: Record<string, string> = { coder: "Coder", narrator: "Narrator", fast: "Fast" };
const ROLE_USE: Record<string, string> = {
  coder: "SQL & reasoning",
  narrator: "report prose",
  fast: "per-phase interprets",
};

// Where context goes (PLATFORM_ARCHITECTURE.md §5b.4) — the governance-relevant axis.
const PRIVACY_META: Record<string, { label: string; tone: Tone; note: string }> = {
  local:            { label: "On-device", tone: "up", note: "Prompts stay on this machine." },
  private_endpoint: { label: "Private endpoint", tone: "plain", note: "Prompts go to your own hosted endpoint." },
  public_api:       { label: "Public API", tone: "amber", note: "Prompts are sent to a third-party API." },
};
const CACHE_NOTE: Record<string, string> = {
  explicit_breakpoint: "prefix-cacheable",
  auto_prefix: "auto prefix-cache",
  auto_prefix_unverified: "prefix-cache unverified",
  none: "no prefix cache",
};
/** The caveat a public-API binding carries — said as a chip, the whole of it on hover. */
const LEAVES = "A bound model sends prompts to a third-party API. Schema, sample rows and findings in the prompt leave "
  + "this machine — bind a local or private-endpoint model for data that must stay in-tenant.";

const label = (b: string) => BACKEND_LABEL[b] ?? b;
const MONO = { fontFamily: "var(--font-mono)" } as const;

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
interface ChipSpec { text: string; title: string; tone?: Tone }

function capabilityChips({ cap, typed = "", saved = "", catalog = null }: {
  cap: LlmCapability;
  typed?: string;
  saved?: string;
  catalog?: LlmModelCatalog | null;
}): ChipSpec[] {
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
  return [
    { text: p.label, title: p.note, tone: p.tone },
    { text: ctxK, title: entry?.context
      ? `${formatCount(ctx)} tokens — from the ${catalog?.backend} catalogue`
      : "model context window (drives payload caps) — declared default, not measured" },
    { text: CACHE_NOTE[cap.cache_mode] ?? cap.cache_mode, title: `cache_mode: ${cap.cache_mode}` },
    ...(cap.tooling === "native_tools" ? [{ text: "tools", title: "native tool calling" }] : []),
    { text: cost === "per_token" ? "$/token" : cost, title: entry?.free !== undefined
      ? `cost: ${cost} — from the catalogue's own pricing`
      : `cost: ${cost}` },
    ...(unsaved ? [{ text: "unsaved", title: "these describe the id you typed — press Save to bind it", tone: "accent" as Tone }] : []),
    ...(cap.token_accounting === "estimated" ? [{ text: "est. tokens", title: "usage estimated (provider omits a usage block)" }] : []),
  ];
}

function CapabilityRow({ chips, lead }: { chips: ChipSpec[]; lead?: string }) {
  return (
    <div style={{ ...ROW, gap: 5, marginTop: 5 }}>
      {lead && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{lead}</span>}
      {chips.map(c => <Chip key={c.text} tone={c.tone} title={c.title}>{c.text}</Chip>)}
    </div>
  );
}

/** A model id field: free text, with the backend's catalogue as suggestions.
 *
 *  Deliberately an input+datalist rather than a select. Model catalogues change
 *  weekly and a closed dropdown that has gone stale means "you cannot use the
 *  model you are paying for" — the list should help, never gate. "Keep" pins a
 *  typed id into the list for next time. */
function ModelField({ value, onChange, placeholder, catalog, listId, onKeep, busy, id }: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  catalog: LlmModelCatalog | null;
  listId: string;
  onKeep: (model: string) => void;
  busy: boolean;
  id?: string;
}) {
  const trimmed = value.trim();
  const known = new Set((catalog?.models ?? []).map((m) => m.id));
  const isCustom = (catalog?.custom ?? []).includes(trimmed);
  const canKeep = !!trimmed && !isCustom && !known.has(trimmed);

  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        list={listId}
        spellCheck={false}
        autoComplete="off"
        style={{ ...MONO, flex: 1 }}
      />
      {canKeep && (
        <Button
          variant="ghost"
          size="xs"
          disabled={busy}
          onClick={() => onKeep(trimmed)}
          title="Keep this model in the list for next time"
          style={{ whiteSpace: "nowrap" }}
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

      <div className="aug-fs-xs" style={{ ...ROW, color: "var(--t3)" }}>
        <span>
          {catalog.live
            ? `${catalog.live_count} models from ${label(catalog.backend)}`
            : custom.length > 0
              ? "no live list"
              : "no models — this list comes from the provider"}
          {custom.length > 0 && ` · ${custom.length} custom`}
        </span>
        {catalog.backend === "openrouter" && (
          <Button variant="ghost" size="xs" onClick={() => setShowPaid(v => !v)}
                  title={showPaid
                    ? "Suggest only :free models (the default posture)"
                    : "Also suggest paid models — binding one still needs an explicit ack"}>
            {showPaid ? `all ${catalog.models.length} — hide paid` : `${listed.length} free — show paid`}
          </Button>
        )}
        <Button variant="ghost" size="xs" disabled={busy} onClick={onRefresh}>
          {busy ? "…" : "Refresh"}
        </Button>
      </div>

      {/* A failed live fetch is stated, not hidden. There is no built-in list behind
          it any more (2026-08-15) — the suggestions ARE the provider's own catalogue,
          so a failure means an empty picker, and saying so beats a silent blank. The
          field is free text either way: a known id can still be typed straight in. */}
      {!catalog.live && (error || catalog.error) && (
        <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
          Couldn’t reach {label(catalog.backend)} for its model
          list ({error || catalog.error}). Type a model id directly, or Refresh to retry.
        </div>
      )}

      {custom.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {custom.map((m) => (
            <Chip key={m}>
              <span style={MONO}>{m}</span>
              <Button
                variant="ghost"
                size="xs"
                disabled={busy}
                onClick={() => onRemove(m)}
                title={`Remove ${m} from the list`}
                aria-label={`Remove ${m} from the list`}
                style={{ height: "auto", padding: "0 2px", margin: 0 }}
              >
                ×
              </Button>
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

/** A bound model the ledger saw calls for that no rate covered — its spend is unknown, not zero. */
function unpricedBound(report: UsageReport | null, bound: Array<{ backend: string; model: string }>) {
  if (!report) return [];
  return bound.flatMap(({ backend, model }) => {
    const rows = report.rows.filter(r => String(r.model ?? "") === model
      && (r.provider === undefined || String(r.provider) === backend) && r.unpriced_calls > 0);
    const calls = rows.reduce((n, r) => n + r.unpriced_calls, 0);
    return calls > 0 ? [{ model, calls }] : [];
  });
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
  // Models pinned to JSON structured output on the CURRENT backend. A model that
  // advertises tool calling and does not do it makes the binding fail by name
  // (`tools_unsupported`); this is how an operator who knows that says "use it anyway".
  const [jsonPins, setJsonPins] = useState<string[]>([]);
  // The fallback binding — where calls go when the primary refuses. "" = the built-in
  // order, "none" = no fallback, else the one chosen backend.
  const [fallbackBackend, setFallbackBackend] = useState("");
  const [fallbackModel, setFallbackModel] = useState("");
  const [fallbackCatalog, setFallbackCatalog] = useState<LlmModelCatalog | null>(null);
  // What the ledger says each model cost — read only to name a bound model with no price. A failed read is said
  // ("prices not checked"), never taken as "every model is priced".
  const [usage, setUsage] = useState<UsageReport | null>(null);
  const [usageFailed, setUsageFailed] = useState(false);

  const load = useCallback(() =>
    getLlmConfig()
      .then((c) => {
        setLoadErr(null);
        setCfg(c);
        setBackend(c.backend);
        setModels({ ...c.models_set });
        setBaseUrls({ ...c.base_urls_set });
        setKeys({});
        setFallbackBackend(c.fallback?.backend ?? "");
        setFallbackModel(c.fallback?.model ?? "");
        setJsonPins([...(c.json_mode?.[c.backend] ?? [])]);
      })
      .catch((e) => setLoadErr(e instanceof Error ? e.message : String(e))), []);

  const loadCatalog = useCallback((b: string, refresh = false) => {
    if (!b) return;
    setCatalogBusy(true);
    setCatalogErr(null);
    getLlmModels(b, refresh)
      .then((c) => setCatalog(c))
      .catch((e) => setCatalogErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setCatalogBusy(false));
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    getUsageReport("provider,model").then(r => { setUsage(r); setUsageFailed(false); })
      .catch(() => setUsageFailed(true));
  }, []);

  // The fallback's catalogue is a SECOND provider's list — never the primary's. Showing
  // OpenRouter ids while the fallback is Gemini would suggest models that 404 on the one
  // backend they would actually be dispatched to.
  useEffect(() => {
    if (!fallbackBackend || fallbackBackend === "none") { setFallbackCatalog(null); return; }
    let ignore = false;
    getLlmModels(fallbackBackend)
      .then((c) => { if (!ignore) setFallbackCatalog(c); })
      .catch(() => { if (!ignore) setFallbackCatalog(null); });
    return () => { ignore = true; };
  }, [fallbackBackend]);

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

  if (loadErr && !cfg) return <ReadFailed what="the model settings" error={loadErr} onRetry={() => void load()} />;
  if (!cfg) return <Loading what="the model settings" />;

  const isLocal = cfg.local_backends.includes(backend);
  const needsKey = cfg.needs_key.includes(backend);
  // Always {} since 2026-08-15 — no backend ships a default model. Kept because the
  // payload still carries the key; it must never again put a model id in this form.
  const defaults = cfg.default_models[backend] || {};
  // Does this backend honour a JSON-mode pin? The server says so; the UI does not guess,
  // because offering a control that silently does nothing is worse than omitting it.
  const jsonPinnable = (cfg.json_mode_backends ?? []).includes(backend);
  // The distinct models currently bound across the roles — what a pin can apply to.
  const boundModels = Array.from(new Set(
    Object.values(models).map(m => (m ?? "").trim()).filter(Boolean)));

  // Three states, not two. A key that is stored but cannot be decrypted answered
  // "configured" here while the provider rejected it — which sends a person to rotate a
  // key that was fine. `keys_state` names the real fault; `keys_set` is kept for older
  // payloads and now means USABLE.
  const stateOf = (b: string) => cfg.keys_state?.[b] ?? (cfg.keys_set[b] ? "set" : "unset");
  const keyState = stateOf(backend);
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
    // Pins are per backend too — carrying the previous provider's over would silently
    // apply a decision made about a different model.
    setJsonPins([...(cfg?.json_mode?.[b] ?? [])]);
    setResult(null);
    setSaved(false);
  };

  // Paid bindings among the typed role models (openrouter only — the `:free`
  // suffix is that catalog's tier marker; BYO-key backends are paid by design).
  const paidBindings = [
    ...(backend === "openrouter"
      ? Object.values(models).filter(m => m && m.trim() && !m.trim().endsWith(":free"))
      : []),
    // The fallback is where calls land when the primary refuses — the moment least likely
    // to be watched, and so the one that must not be able to start billing unnoticed.
    ...(fallbackBackend === "openrouter" && fallbackModel.trim()
      && !fallbackModel.trim().endsWith(":free") ? [fallbackModel.trim()] : []),
  ];

  const save = async () => {
    setSaving(true); setSaved(false); setResult(null);
    try {
      const next = await setLlmConfig({
        backend,
        models: { coder: models.coder || "", narrator: models.narrator || "", fast: models.fast || "" },
        base_urls: isLocal ? { [backend]: baseUrls[backend] || "" } : {},
        keys: Object.fromEntries(Object.entries(keys).filter(([, v]) => v && v.trim())),
        fallback: { backend: fallbackBackend, model: fallbackModel.trim() },
        ...(paidBindings.length > 0 ? { allow_paid: paidAck } : {}),
        // Only for a backend that honours the pin — sending it elsewhere would store a
        // setting nothing reads.
        ...(jsonPinnable ? { json_mode: { [backend]: jsonPins } } : {}),
      });
      setCfg(next);
      setBackend(next.backend);
      setModels({ ...next.models_set });
      setBaseUrls({ ...next.base_urls_set });
      setKeys({});
      setFallbackBackend(next.fallback?.backend ?? "");
      setFallbackModel(next.fallback?.model ?? "");
      setJsonPins([...(next.json_mode?.[next.backend] ?? [])]);
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

  // What each role's model is, as chips — said once when all three say the same thing.
  const chipsByRole: Record<string, ChipSpec[] | null> = Object.fromEntries(ROLES.map(role => [role,
    cfg.capabilities?.[role]
      ? capabilityChips({ cap: cfg.capabilities[role], typed: models[role] ?? "", saved: cfg.models[role] ?? "", catalog })
      : null]));
  const chipsShared = ROLES.every(r => chipsByRole[r])
    && ROLES.every(r => JSON.stringify(chipsByRole[r]) === JSON.stringify(chipsByRole.coder));

  // ── What is in force (the SAVED binding), and what needs a person ──────────────────────────────────────────
  const live = cfg.backend;
  const liveNeedsKey = cfg.needs_key.includes(live);
  const liveKey = stateOf(live);
  const savedModel = (role: string) => (cfg.models[role] ?? "").trim();
  const boundRoles = ROLES.filter(r => savedModel(r));
  const emptyRoles = ROLES.filter(r => !savedModel(r));
  const distinct = Array.from(new Set(boundRoles.map(savedModel)));
  const classes = new Set(Object.values(cfg.capabilities ?? {}).map((c) => c.privacy_class));
  const privacy = classes.has("public_api") ? "public_api" : classes.has("private_endpoint") ? "private_endpoint"
    : classes.has("local") ? "local" : null;
  const fb = cfg.fallback;
  const chain = fb?.chain ?? [];
  const fbChosen = !!fb?.backend && fb.backend !== "none";
  const keyed = cfg.needs_key;
  const keysUsable = keyed.filter(b => stateOf(b) === "set").length;
  const keysUnreadable = keyed.filter(b => stateOf(b) === "unreadable");
  const chainNoKey = chain.filter(b => keyed.includes(b) && stateOf(b) !== "set");
  const noPrice = unpricedBound(usage, [
    ...boundRoles.map(r => ({ backend: live, model: savedModel(r) })),
    ...(fbChosen && fb?.model ? [{ backend: fb.backend, model: fb.model }] : []),
  ].filter((b, i, all) => all.findIndex(x => x.model === b.model && x.backend === b.backend) === i));

  const needs = [
    liveNeedsKey && liveKey === "unset" && (
      <NeedsRow key="key" testId="needs-key" title={`${label(live)} has no API key`}
        detail="Every call to it fails until a key is pasted."
        actions={<Button size="xs" variant="secondary" onClick={() => goTo("models-provider", "#llm-key")}>Paste a key</Button>} />
    ),
    liveNeedsKey && liveKey === "unreadable" && (
      <NeedsRow key="key" testId="needs-key" title={`${label(live)}'s stored key cannot be decrypted`}
        detail="AUGHOR_SECRET_KEY is missing or has changed since it was saved; the key itself may be fine."
        actions={<Button size="xs" variant="secondary" onClick={() => goTo("models-provider", "#llm-key")}>Re-paste</Button>} />
    ),
    emptyRoles.length > 0 && (
      <NeedsRow key="roles" testId="needs-roles"
        title={`${plural(emptyRoles.length, "role")} ${emptyRoles.length === 1 ? "has" : "have"} no model · ${emptyRoles.map(r => ROLE_NAME[r]).join(", ")}`}
        detail="Nothing is assumed: a blank role fails its calls, saying so."
        actions={<Button size="xs" variant="secondary" onClick={() => goTo("models-provider", `#llm-model-${emptyRoles[0]}`)}>Choose</Button>} />
    ),
    fbChosen && !fb?.model && (
      <NeedsRow key="fb-model" testId="needs-fallback-model" title={`The fallback, ${label(fb!.backend)}, has no model`}
        detail="Without one this link is skipped, so the fallback does nothing."
        actions={<Button size="xs" variant="secondary" onClick={() => goTo("models-fallback", "#llm-fallback-model")}>Choose</Button>} />
    ),
    chainNoKey.length > 0 && (
      <NeedsRow key="fb-key" testId="needs-fallback-key"
        title={`The fallback ${chainNoKey.length === 1 ? "provider has" : "providers have"} no usable key · ${chainNoKey.map(label).join(", ")}`}
        detail="Choose it as the provider above to paste its key." />
    ),
    fb?.active && (
      <NeedsRow key="fb-active" testId="needs-fallback-active" title="The primary is spent — calls are landing on the fallback"
        detail={chain.length ? `Answering on ${chain.map(label).join(" → ")}.` : undefined} />
    ),
    noPrice.length > 0 && (
      <NeedsRow key="price" testId="needs-price"
        title={noPrice.length === 1 ? `${noPrice[0].model} has no price` : `${noPrice.length} bound models have no price`}
        detail={`${noPrice.map(p => `${p.model} · ${plural(p.calls, "call")} unpriced`).join("  ·  ")} — its spend is unknown, not zero`}
        actions={<Button size="xs" variant="ghost" onClick={() => requestTab("spend")}>Open Spend</Button>} />
    ),
  ].filter(Boolean);

  const testResult = result && (
    <div className="aug-fs-xs" data-testid="llm-test-result" style={{
      padding: "8px 12px", borderRadius: "var(--r2)", lineHeight: 1.5,
      background: result.ok ? "var(--grn1)" : "var(--red1)",
      border: `1px solid ${result.ok ? "var(--grn2)" : "var(--red2)"}`,
      color: result.ok ? "var(--grn5)" : "var(--red4)",
      ...MONO, wordBreak: "break-word",
    }}>
      {/* Per-model, because the roles can be bound to different models and a
          single headline would hide a narrator or fast binding that is broken. */}
      {result.results?.length ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={{ fontWeight: 600 }}>
            {result.ok
              ? `✓ ${label(backend)} — ${result.tested} model${result.tested === 1 ? "" : "s"} responded`
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
        ? `✓ ${label(backend)} responded${result.model ? ` (${result.model})` : ""}`
        : `✗ ${result.error || "test failed"}`}
    </div>
  );

  // Prefix-cache probe verdict
  const probeResult = probe && (() => {
    const ok = probe.ok && probe.verdict;
    const reuse = probe.verdict === "reuse_active";
    const tone = !ok ? { bg: "var(--red1)", fg: "var(--red4)", bd: "var(--red2)" }
      : reuse ? { bg: "var(--grn1)", fg: "var(--grn5)", bd: "var(--grn2)" }
      : probe.verdict === "no_reuse" ? { bg: "var(--amb1)", fg: "var(--amb5)", bd: "var(--amb2)" }
      : { bg: "var(--bg-3)", fg: "var(--t2)", bd: "var(--b1)" };
    const headline = !ok ? `✗ ${probe.error || "probe failed"}`
      : reuse ? "✓ Prefix cache reused — prefix-aligned prompts pay off here"
      : probe.verdict === "no_reuse" ? "✗ No cross-request prefix reuse — prefix alignment won't help this binding"
      : "~ Inconclusive — measurement was ambiguous; left as declared";
    return (
      <div className="aug-fs-xs" data-testid="llm-probe-result" style={{
        padding: "8px 12px", borderRadius: "var(--r2)", lineHeight: 1.55,
        background: tone.bg, color: tone.fg, border: `1px solid ${tone.bd}`,
        ...MONO, wordBreak: "break-word",
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
  })();

  return (
    <Stack testId="models-panel">
      <Figures testId="models-figures">
        <Figure label="Provider" value={label(live)} testId="fig-provider"
          sub={<>
            {!liveNeedsKey ? <span>runs on this machine</span>
              : liveKey !== "set" && <Chip tone="amber">{liveKey === "unreadable" ? "key unreadable" : "no key"}</Chip>}
            {privacy && <Chip tone={PRIVACY_META[privacy].tone} title={privacy === "public_api" ? LEAVES : PRIVACY_META[privacy].note}>
              {privacy === "public_api" ? "prompts leave this machine" : PRIVACY_META[privacy].label}</Chip>}
          </>} />
        <Figure label="Roles bound" value={`${boundRoles.length} of ${ROLES.length}`} testId="fig-roles"
          tone={emptyRoles.length ? "amber" : undefined}
          sub={distinct.length ? <span style={{ ...ONE_LINE, ...MONO }} title={distinct.join(", ")}>{distinct.join(" · ")}</span> : "no model bound"} />
        <Figure label="Fallback" testId="fig-fallback" title={chain.length ? `Tried in order: ${chain.map(label).join(" → ")}` : undefined}
          value={chain.length ? `${label(chain[0])}${chain.length > 1 ? ` +${chain.length - 1}` : ""}` : "None"}
          sub={<>
            <span style={ONE_LINE}>
              {fb?.model && <span style={MONO}>{fb.model}</span>}
              {fb?.model && chain.length > 1 && " · "}
              {chain.length > 1 && `then ${chain.slice(1).map(label).join(" → ")}`}
              {!fb?.model && chain.length <= 1 && (chain.length ? "the built-in order" : "a failing primary fails the call")}
            </span>
            {fb?.env_pinned && <Chip title="AUGHOR_FALLBACK_BACKENDS is set in the environment and overrides the choice below.">set by the environment</Chip>}
          </>} />
        <Figure label="Keys" value={`${keysUsable} of ${keyed.length}`} testId="fig-keys"
          sub={keysUnreadable.length
            ? <Chip tone="amber">{plural(keysUnreadable.length, "key")} unreadable</Chip>
            : "providers with a usable key"} />
      </Figures>

      <NeedsYou testId="models-needs"
        empty={usageFailed ? "Nothing needs you · prices not checked (the usage ledger could not be read)"
          : "Nothing needs you · every role has a model and the provider a key"}>
        {needs}
      </NeedsYou>

      <Pair min={380}>
        <div id="models-provider" style={{ minWidth: 0 }}>
          <Card label="Provider">
            <div style={FIELDS}>
              <Field label="Provider">
                <SelectField value={backend} onChange={(e) => onBackend(e.target.value)} aria-label="Provider">
                  {cfg.backends.map((b) => (
                    <option key={b} value={b}>{label(b)}</option>
                  ))}
                </SelectField>
              </Field>

              {/* API key (hosted backends only) */}
              {needsKey && (
                <Field label="API key" htmlFor="llm-key"
                  meta={<Chip tone={keySet ? "up" : keyUnreadable ? "down" : "amber"}>
                    {keySet ? "configured" : keyUnreadable ? "stored, but unreadable" : "not set"}</Chip>}>
                  <Input
                    id="llm-key"
                    type="password"
                    autoComplete="off"
                    value={keys[backend] ?? ""}
                    onChange={(e) => setKeys({ ...keys, [backend]: e.target.value })}
                    placeholder={keySet ? "•••••••••• (leave blank to keep)"
                      : keyUnreadable ? "re-paste the key, or restore AUGHOR_SECRET_KEY"
                      : "paste API key"}
                  />
                </Field>
              )}

              {/* Base URL (local backends only) */}
              {isLocal && (
                <Field label="Base URL" htmlFor="llm-base-url">
                  <Input
                    id="llm-base-url"
                    value={baseUrls[backend] ?? ""}
                    onChange={(e) => setBaseUrls({ ...baseUrls, [backend]: e.target.value })}
                    placeholder={cfg.base_urls[backend] || ""}
                    style={MONO}
                  />
                </Field>
              )}
            </div>
            {needsKey && (
              <Note tone={keyUnreadable ? "red" : undefined}>
                {keyUnreadable
                  ? "A key is stored but cannot be decrypted — AUGHOR_SECRET_KEY is missing or has changed since it was saved. The key itself may be perfectly good; the provider will reject it either way."
                  : "Stored encrypted on the server (secretvault). Save before testing a new key."}
              </Note>
            )}

            {/* Models */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 14 }}>
              {ROLES.map((role) => (
                <Field key={role} htmlFor={`llm-model-${role}`}
                  label={<><span style={{ color: "var(--t2)" }}>{ROLE_NAME[role]}</span><span>· {ROLE_USE[role]}</span></>}>
                  <ModelField
                    id={`llm-model-${role}`}
                    value={models[role] ?? ""}
                    onChange={(v) => setModels({ ...models, [role]: v })}
                    placeholder={cfg.models[role] || "pick a model"}
                    catalog={catalog}
                    listId={`llm-models-${backend}`}
                    onKeep={keepModel}
                    busy={catalogBusy}
                  />
                  {!chipsShared && chipsByRole[role] && <CapabilityRow chips={chipsByRole[role]!} />}
                </Field>
              ))}
              {chipsShared && <CapabilityRow lead="Every role:" chips={chipsByRole.coder!} />}

              <CatalogFooter
                catalog={catalog}
                busy={catalogBusy}
                error={catalogErr}
                onRefresh={() => loadCatalog(backend, true)}
                onRemove={removeModel}
              />
            </div>
            <Note>Any model id works — the list is what this provider serves. A blank role fails its calls, saying so.</Note>

            {jsonPinnable && boundModels.length > 0 && (
              <div className="aug-fs-xs" style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12,
                color: "var(--t2)" }}>
                <span>
                  <strong>Structured output</strong> — a model that advertises tool calling and does not do it fails
                  as <code className="aug-fs-xs">tools_unsupported</code>. Tick it to run in JSON mode.
                </span>
                {boundModels.map(m => (
                  <label key={m} style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer" }}>
                    <Checkbox
                      checked={jsonPins.includes(m)}
                      onChange={e => setJsonPins(prev =>
                        e.target.checked ? Array.from(new Set([...prev, m])) : prev.filter(x => x !== m))}
                    />
                    <span>Use JSON structured output for <code className="aug-fs-xs">{m}</code></span>
                  </label>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Fallback — where calls go when the primary refuses.
            This used to be reachable only through AUGHOR_FALLBACK_BACKENDS /
            AUGHOR_FALLBACK_MODEL_<BACKEND>: invisible from the product, so a deployment
            nobody had set them on ran with a chain that had no model to dispatch with and
            silently skipped every link. An env pin still wins, and says so below. */}
        <div id="models-fallback" style={{ minWidth: 0 }}>
          <Card label="Fallback">
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Provider">
                <SelectField
                  value={fallbackBackend}
                  onChange={(e) => { setFallbackBackend(e.target.value); setFallbackModel(""); }}
                  aria-label="Fallback provider"
                >
                  <option value="">Built-in order (try each configured provider)</option>
                  <option value="none">No fallback — fail on the primary</option>
                  {cfg.backends.filter((b) => b !== backend).map((b) => (
                    <option key={b} value={b}>
                      {label(b)}
                      {cfg.needs_key.includes(b) && !cfg.keys_set[b] ? " — no key set" : ""}
                    </option>
                  ))}
                </SelectField>
              </Field>

              {fallbackBackend && fallbackBackend !== "none" && (
                <Field label="Model" htmlFor="llm-fallback-model">
                  <ModelField
                    id="llm-fallback-model"
                    value={fallbackModel}
                    onChange={setFallbackModel}
                    placeholder={`paste a model id from ${label(fallbackBackend)}`}
                    catalog={fallbackCatalog}
                    listId={`llm-fallback-models-${fallbackBackend}`}
                    onKeep={() => {}}
                    busy={false}
                  />
                </Field>
              )}
            </div>
            {fallbackBackend && fallbackBackend !== "none" && (
              <Note>One model for every role; without one this link is skipped.</Note>
            )}
            <Note>
              {chain.length ? null : <>No fallback — a failing primary fails the call. </>}
              Agents in Agent Ops inherit this: an unpinned agent whose call fails over answers on it.
            </Note>
            {fb?.env_pinned && (
              <Note tone="amber" testId="fallback-env-pinned">
                <code style={MONO}>AUGHOR_FALLBACK_BACKENDS</code> is set in the environment and overrides the choice
                above — the chain shown is the one used. Unset it to steer the fallback from here.
              </Note>
            )}
          </Card>
        </div>
      </Pair>

      {/* Save, the tools, and what they answered */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {paidBindings.length > 0 && (
          <div className="aug-fs-xs" data-testid="llm-paid-ack" style={{
            lineHeight: 1.5, padding: "8px 12px", borderRadius: "var(--r3)",
            background: "var(--amb1)", color: "var(--amb4)", display: "flex", flexWrap: "wrap", gap: "4px 14px",
            alignItems: "center",
          }}>
            <span>
              {paidBindings.length === 1
                ? <><code>{paidBindings[0]}</code> is a paid model</>
                : `${paidBindings.length} of these are paid models`}
              {" "}— every paid call bills your OpenRouter credit (<code>:free</code> models are the default).
            </span>
            <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer" }}>
              <Checkbox checked={paidAck}
                onChange={e => setPaidAck(e.target.checked)} />
              <span>Bind {paidBindings.length === 1 ? "it" : "them"} anyway — I accept the charges</span>
            </label>
          </div>
        )}
        <div style={{ ...ROW, gap: 10 }}>
          <Button variant="default" size="sm"
            onClick={save}
            disabled={saving || (paidBindings.length > 0 && !paidAck)}
            title={paidBindings.length > 0 && !paidAck
              ? "A paid model is bound — tick the acknowledgment above to save"
              : undefined}>
            {saving ? "Saving…" : "Save"}
          </Button>
          <ToolsMenu testId="models-tools" tools={[
            { label: testing ? "Testing…" : "Test connection", onSelect: () => void test(), disabled: testing,
              testId: "llm-test" },
            { label: probing ? "Measuring…" : "Measure prefix cache", onSelect: () => void runProbe(), disabled: probing,
              title: "Measure whether this backend reuses a shared prompt prefix across requests, and record the verdict",
              testId: "llm-probe" },
          ]} />
          {(testing || probing) && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{testing ? "Testing…" : "Measuring…"}</span>}
          {saved && <span className="aug-fs-xs" style={{ color: "var(--grn4)" }}>✓ Saved</span>}
          {loadErr && <span className="aug-fs-xs" style={{ color: "var(--red4)" }}>Could not re-read the settings: {loadErr}</span>}
        </div>
        {testResult}
        {probeResult}
      </div>
    </Stack>
  );
}
