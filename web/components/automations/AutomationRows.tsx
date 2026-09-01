"use client";

/**
 * VA-12 · the one editor for a trigger and for an action.
 *
 * These rows lived inside `AutomationsPanel` and were reachable only from its form view.
 * The canvas now authors the same objects, and two editors for one model is how a picture
 * and the thing it edits come to disagree — the same argument `AutomationGraph` makes for
 * letting the SERVER own the graph. So the rows move here and both surfaces render these.
 *
 * **The kind lists are narrower than the model's `Literal`, on purpose.** The server
 * accepts seven effect kinds; two of them — `monitor` and `agent_alert` — are adopted
 * objects that the engine writes when an existing monitor or alert rule is migrated onto
 * it, and the model's own docstring says they are "not authored by hand". Offering them
 * here would invite a reader to hand-write one and get a row that duplicates an object
 * they already have. Posting to Slack IS authorable and is offered — VA-13 added the
 * `GET /slack-bots` client and the picker below.
 */
import React from "react";

import { Button } from "@/components/ui/button";
import {
  AUTOMATION_REQUIRED_KEYS, getAutomationVocabulary, getIntegrationConnections,
  getIntegrationOperations,
  type AutoCondition, type AutoEffect, type ConditionKind, type EffectKind,
  type AutomationVocabulary, type GuardClause, type IntegrationConnection,
  type IntegrationOperation, type SlackBotSummary, type UserAgent,
} from "@/lib/api";
import { seedConfig, upstreamKeys } from "@/lib/automationFlow";

export const CONDITION_KINDS: { value: ConditionKind; label: string; desc: string }[] = [
  { value: "schedule",       label: "Schedule",       desc: "Fire on a cron cadence" },
  { value: "metric",         label: "Metric",         desc: "Delegate to an existing monitor by id" },
  { value: "source_change",  label: "Source change",  desc: "A table's rows changed (add / delete / backfill)" },
  { value: "entity_appears", label: "New entity",     desc: "A new key appeared in a table" },
];

export const EFFECT_KINDS: { value: EffectKind; label: string; desc: string }[] = [
  { value: "notify",         label: "Notify",         desc: "Send through a Notifications trigger" },
  { value: "investigate",    label: "Investigate",    desc: "Run the Agent" },
  { value: "brief",          label: "Deliver briefing", desc: "Deliver a briefing subscription" },
  { value: "kinetic_action", label: "Declared action",
    desc: "Run a declared, governed action — through its approval gate" },
  { value: "slack_post", label: "Post to Slack",
    desc: "Post into a channel as one of your bots — mentionable, and repliable in thread" },
  { value: "subchain", label: "Run a chain",
    desc: "Run another automation as one step — share a shape instead of authoring it twice" },
  { value: "integration_call", label: "Use an integration",
    desc: "Act as a connected account — read or post under the grant that account gave, "
        + "capped and audited" },
  { value: "metric_value", label: "Governed metric",
    desc: "Read a metric by its approved definition — the number the registry defines, filters and caveats included" },
  { value: "trusted_query", label: "Trusted query",
    desc: "Run a vetted query and publish its rows — the one output in this plane a step can run once per item of" },
];

export const CRON_PRESETS = [
  { label: "Hourly",  cron: "0 * * * *" },
  { label: "Daily",   cron: "0 9 * * *" },
  { label: "Weekly",  cron: "0 9 * * 1" },
  { label: "Custom",  cron: "" },
];

export const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: "var(--r3)",
  border: "1px solid var(--b1)", background: "var(--bg-1, var(--bg-2))", color: "var(--t1)",
};

export const labelStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: "var(--t3)", marginBottom: 5, display: "block",
  textTransform: "uppercase",
};

export const ghostBtn: React.CSSProperties = {
  background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 11,
};

/**
 * A new trigger / a new action, with the config key its kind REQUIRES already present.
 *
 * Shared because the defaults are part of the contract, not a convenience: the server
 * validates required config keys at CONSTRUCTION, so a default that omits one produces a
 * 422 the moment it is saved. Two call sites inventing their own defaults is two chances
 * to get that wrong, and only one of them would be caught by a test.
 */
export function newConditionOf(kind: ConditionKind): AutoCondition {
  return { kind, config: seedConfig(kind, AUTOMATION_REQUIRED_KEYS) };
}

export function newEffectOf(kind: EffectKind): AutoEffect {
  return { kind, config: seedConfig(kind, AUTOMATION_REQUIRED_KEYS) };
}

/** The kind a bare "add" reaches for, unchanged from before the palette existed: the two
 *  on-canvas buttons and the rail's rows still add a row and let the reader change its
 *  kind, and only the palette places a chosen one. */
export function newCondition(): AutoCondition {
  return newConditionOf("schedule");
}

export function newEffect(): AutoEffect {
  return newEffectOf("notify");
}

/** What is still missing before the server would accept this row. Empty = valid.
 *
 *  Checked while the row is on screen rather than discovered from a failed save: the
 *  server's error names a config key, and a key says nothing about WHICH of five steps
 *  is carrying it. The requirements themselves live at the wire boundary
 *  (`AUTOMATION_REQUIRED_KEYS`) and are asserted against the Python source. */
export function missingKeys(row: AutoCondition | AutoEffect): string[] {
  return (AUTOMATION_REQUIRED_KEYS[row.kind] ?? [])
    .filter(k => !String(row.config[k] ?? "").trim());
}

/** A `message` is either a sentence or a `{"$from": …}` binding. Rendered as the text a
 *  person typed either way, so the field round-trips: showing `[object Object]` for a
 *  binding would invite someone to overwrite the one thing that makes the chain work. */
function fieldText(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function messageText(e: AutoEffect): string {
  return fieldText(e.config.message);
}

/** Text back to a value. A well-formed binding object becomes one — `$from`, or DS-6's
 *  `$from_any` join — anything else stays the string it is, including half-typed JSON,
 *  which must not be swallowed mid-keystroke. */
function parseMessage(text: string): unknown {
  const t = text.trim();
  if (!t.startsWith("{")) return text;
  try {
    const parsed = JSON.parse(t);
    return parsed && typeof parsed === "object"
      && ("$from" in parsed || "$from_any" in parsed) ? parsed : text;
  } catch {
    return text;
  }
}


/* ── W1 · "Only if" ───────────────────────────────────────────────────────────────
 *
 * The wire calls this `when`; every surface calls it **Only if**. The trigger node on
 * the canvas is already labelled "When", and two Whens in one picture is a collision a
 * reader pays for — so the word is translated here, at the boundary, exactly as the
 * retired-vocabulary rule asks.
 */

/** The operators, FETCHED once per page and shared by every row.
 *
 *  A hook rather than a prop because `EffectRow` renders on two surfaces — the form and
 *  the canvas — and a prop is a thing one of them can forget to pass. The cache is a
 *  module-level promise: N rows on screen make one request, and a failure degrades to
 *  an empty list (no operators offered) rather than an unhandled rejection. */
const EMPTY_VOCAB: AutomationVocabulary = {
  kinds: {}, guardOps: [],
  // A cap of 0 while the fetch is in flight: the "+ item" control stays disabled rather
  // than offering a list the save would refuse. Degrading to a guessed number is how a
  // form and an engine come to disagree about the same rule.
  forEach: { maxItems: 0, itemAlias: "item", itemValueKey: "value", publishes: [] },
};
let vocabCache: Promise<AutomationVocabulary> | null = null;

export function useAutomationVocabulary(): AutomationVocabulary {
  const [vocab, setVocab] = React.useState<AutomationVocabulary>(EMPTY_VOCAB);
  React.useEffect(() => {
    vocabCache ??= getAutomationVocabulary().catch(() => EMPTY_VOCAB);
    let live = true;
    void vocabCache.then(v => { if (live) setVocab(v); });
    return () => { live = false; };
  }, []);
  return vocab;
}

function refOf(value: unknown): string {
  return value && typeof value === "object" && "$from" in (value as object)
    ? String((value as { $from: unknown }).$from) : "";
}

/**
 * The guard editor for one step.
 *
 * The left side is a PICKER over what earlier steps publish, never free text. B1 closed
 * exactly this hole for params — an unknown key passed every save-time check and
 * surfaced at 09:00 as a skipped step — and a guard authored as free text would have
 * re-opened it one field over.
 *
 * Nothing renders when no earlier step publishes anything: the chain context is made of
 * upstream output, so a first step has nothing it could ask about, and an empty picker
 * is a control that cannot be used.
 */
export function GuardRows({ e, siblings, index, onChange }: {
  e: AutoEffect;
  /** The whole step list and this step's place in it — a guard may only read what runs
   *  BEFORE it, which is the same rule `validate_chain` refuses a forward reference by. */
  siblings: AutoEffect[]; index: number;
  onChange: (e: AutoEffect) => void;
}) {
  const { kinds, guardOps: ops } = useAutomationVocabulary();
  const upstream = upstreamKeys(siblings, index, kinds);
  const clauses = e.when ?? [];
  const unary = new Set(ops.filter(o => o.unary).map(o => o.op));
  if (upstream.length === 0 || ops.length === 0) return null;

  const put = (next: GuardClause[]) => onChange({ ...e, when: next });
  const patch = (i: number, p: Partial<GuardClause>) =>
    put(clauses.map((c, n) => (n === i ? { ...c, ...p } : c)));

  return (
    <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px dashed var(--b1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
        <span style={{ ...labelStyle, marginBottom: 0 }}>Only if</span>
        {clauses.length > 1 && (
          <select value={e.when_logic ?? "all"} aria-label="Only if logic"
            onChange={ev => onChange({ ...e, when_logic: ev.target.value as "all" | "any" })}
            style={{ ...inputStyle, width: 74, padding: "3px 6px", fontSize: 11 }}>
            <option value="all">all</option>
            <option value="any">any</option>
          </select>
        )}
        <Button variant="ghost" className="h-auto font-normal" style={{ ...ghostBtn, padding: 0 }}
          onClick={() => put([...clauses, { left: { $from: upstream[0].ref }, op: ops[0].op }])}>
          + condition
        </Button>
      </div>
      {clauses.map((c, i) => (
        <div key={i} style={{ display: "flex", gap: 6, marginBottom: 5, alignItems: "center" }}>
          <select value={refOf(c.left)} aria-label="Only if subject"
            onChange={ev => patch(i, { left: { $from: ev.target.value } })}
            style={{ ...inputStyle, width: 150, fontSize: 12 }}>
            {/* A reference the picker cannot offer — a step renamed or deleted since —
                is kept as an option rather than silently re-pointed at the first entry,
                which would change what the guard tests without anyone touching it. */}
            {!upstream.some(u => u.ref === refOf(c.left)) && refOf(c.left) && (
              <option value={refOf(c.left)}>{refOf(c.left)} (missing)</option>
            )}
            {upstream.map(u => <option key={u.ref} value={u.ref}>{u.ref}</option>)}
          </select>
          <select value={c.op} aria-label="Only if comparison"
            onChange={ev => patch(i, { op: ev.target.value })}
            style={{ ...inputStyle, width: 96, fontSize: 12 }}>
            {ops.map(o => <option key={o.op} value={o.op}>{o.label}</option>)}
          </select>
          {!unary.has(c.op) && (
            <input style={{ ...inputStyle, flex: 1, fontSize: 12 }} value={String(c.right ?? "")}
              aria-label="Only if value" placeholder="value"
              onChange={ev => patch(i, { right: ev.target.value })} />
          )}
          <Button variant="ghost" className="h-auto font-normal" aria-label="Remove condition"
            onClick={() => put(clauses.filter((_, n) => n !== i))}
            style={{ ...ghostBtn, color: "var(--red3)", padding: "2px 4px" }}>✕</Button>
        </div>
      ))}
    </div>
  );
}

/* ── DS-6 · "Otherwise" ───────────────────────────────────────────────────────────
 *
 * The wire calls it `else_of`; every surface calls it **Otherwise**. The route: this
 * step runs exactly when the named step's "Only if" was evaluated and did NOT hold —
 * complementary by construction, where two hand-written opposite guards can drift.
 */

/**
 * The route editor for one step.
 *
 * The target is a PICKER over the steps this one may be the otherwise OF — earlier,
 * guarded, unfanned: the same eligibility `validate_chain` refuses against, offered
 * rather than discovered as a 422. Nothing renders when no earlier step qualifies and
 * no route is set: an empty picker is a control that cannot be used.
 */
export function OtherwiseRows({ e, siblings, index, onChange }: {
  e: AutoEffect; siblings: AutoEffect[]; index: number;
  onChange: (e: AutoEffect) => void;
}) {
  const current = (e.else_of ?? "").trim();
  const eligible = siblings
    .map((s, i) => ({ step: s, alias: s.alias || `step${i + 1}`, i }))
    .filter(({ step, i }) => i < index
      && (step.when ?? []).length > 0 && !step.for_each);
  if (eligible.length === 0 && !current) return null;

  return (
    <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px dashed var(--b1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ ...labelStyle, marginBottom: 0 }}>Otherwise</span>
        <select value={current} aria-label="Otherwise of"
          onChange={ev => onChange({ ...e, else_of: ev.target.value || undefined })}
          style={{ ...inputStyle, flex: 1, fontSize: 12 }}>
          <option value="">— runs regardless —</option>
          {/* A target the picker cannot offer — deleted, renamed, or no longer guarded
              — is kept as an option rather than silently cleared, which would change
              when this step runs without anyone touching it. */}
          {current && !eligible.some(t => t.alias === current) && (
            <option value={current}>{current} (missing)</option>
          )}
          {eligible.map(t => (
            <option key={t.alias} value={t.alias}>
              runs when {t.alias}&apos;s Only if does not hold
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

/* ── W2 · "For each" ──────────────────────────────────────────────────────────────
 *
 * The wire calls it `for_each` and so does every surface — unlike `when`/"Only if",
 * there is no collision to translate away.
 *
 * Only a LITERAL list is authored here, and deliberately: it is the case that always
 * works ("post per region" is three region names someone types), while a bound source
 * needs an upstream that publishes a list, and nothing in this plane does yet except
 * the declared-action kind's open outcome. The wire accepts that binding and the canvas
 * draws it — the model stays more expressive than the form, which is the right way
 * round.
 */
export function ForEachRows({ e, onChange }: {
  e: AutoEffect; onChange: (e: AutoEffect) => void;
}) {
  const { forEach: vocab } = useAutomationVocabulary();
  const source = e.for_each?.source;
  const bound = source !== null && source !== undefined && !Array.isArray(source);
  const items: unknown[] = Array.isArray(source) ? source : [];
  // Items this form can safely EDIT. A dict item is authored on the wire (its fields are
  // read `{"$from": "item.room"}`), and a text input would render it "[object Object]"
  // and replace it with that string on the first keystroke — deleting a working design
  // to make a form work. Shown read-only instead. Found by driving it.
  const editable = items.every(i => i === null || typeof i !== "object");
  const put = (next: unknown[] | null) =>
    onChange({ ...e, for_each: next === null ? null : { source: next } });

  // A bound source is shown, never edited away by a form that cannot express it: an
  // editor that silently replaced `{"$from": "rows.items"}` with an empty list would
  // delete a working design on first render.
  if (bound || !editable) {
    return (
      <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px dashed var(--b1)" }}>
        <div style={{ ...labelStyle, marginBottom: 3 }}>For each</div>
        <div className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)",
          color: "var(--chart-2)" }}>
          {bound ? refOf(source) : `${items.length} items · edited on the canvas`}
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px dashed var(--b1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
        <span style={{ ...labelStyle, marginBottom: 0 }}>For each</span>
        <span style={{ flex: 1 }} />
        {e.for_each ? (
          <>
            <Button variant="ghost" className="h-auto font-normal"
              style={{ ...ghostBtn, padding: 0 }}
              disabled={items.length >= vocab.maxItems}
              title={items.length >= vocab.maxItems
                ? `${vocab.maxItems} items is the cap` : undefined}
              onClick={() => put([...items, ""])}>+ item</Button>
            <Button variant="ghost" className="h-auto font-normal"
              style={{ ...ghostBtn, padding: 0, color: "var(--red3)" }}
              onClick={() => put(null)}>runs once</Button>
          </>
        ) : (
          <Button variant="ghost" className="h-auto font-normal"
            style={{ ...ghostBtn, padding: 0 }}
            onClick={() => put([""])}>+ list</Button>
        )}
      </div>
      {items.map((item, i) => (
        <div key={i} style={{ display: "flex", gap: 6, marginBottom: 5, alignItems: "center" }}>
          <input className="aug-fs-sm" style={{ ...inputStyle, flex: 1 }}
            value={String(item ?? "")}
            aria-label={`For each item ${i + 1}`} placeholder="one item — e.g. EMEA"
            onChange={ev => put(items.map((v, n) => (n === i ? ev.target.value : v)))} />
          <Button variant="ghost" className="h-auto font-normal" aria-label="Remove item"
            onClick={() => put(items.filter((_, n) => n !== i))}
            style={{ ...ghostBtn, color: "var(--red3)", padding: "2px 4px" }}>✕</Button>
        </div>
      ))}
      {items.length > 0 && (
        <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>
          runs once per item · read it as{" "}
          <code style={{ fontFamily: "var(--font-mono)", color: "var(--chart-2)" }}>
            {vocab.itemAlias}.{vocab.itemValueKey}
          </code>
        </div>
      )}
    </div>
  );
}

export function ConditionRow({ c, onChange, onRemove }: {
  c: AutoCondition; onChange: (c: AutoCondition) => void; onRemove?: () => void;
}) {
  const set = (patch: Record<string, unknown>) => onChange({ ...c, config: { ...c.config, ...patch } });
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 8 }}>
      <select value={c.kind} onChange={e => onChange({ kind: e.target.value as ConditionKind, config: {} })}
        aria-label="Trigger kind"
        style={{ ...inputStyle, width: 150 }}>
        {CONDITION_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
      </select>
      <div style={{ flex: 1 }}>
        {c.kind === "schedule" && (
          <div style={{ display: "flex", gap: 6 }}>
            <select value={CRON_PRESETS.find(p => p.cron === c.config.cron)?.cron ?? ""}
              aria-label="Cron preset"
              onChange={e => e.target.value && set({ cron: e.target.value })}
              style={{ ...inputStyle, width: 110 }}>
              {CRON_PRESETS.map(p => <option key={p.label} value={p.cron}>{p.label}</option>)}
            </select>
            <input style={inputStyle} value={String(c.config.cron ?? "")} onChange={e => set({ cron: e.target.value })} placeholder="cron e.g. 0 9 * * *" />
          </div>
        )}
        {c.kind === "metric" && (
          <input style={inputStyle} value={String(c.config.monitor_id ?? "")} onChange={e => set({ monitor_id: e.target.value })} placeholder="monitor id" />
        )}
        {(c.kind === "source_change" || c.kind === "entity_appears") && (
          <input style={inputStyle} value={String(c.config.table ?? "")} onChange={e => set({ table: e.target.value })} placeholder="table (schema.table)" />
        )}
      </div>
      {onRemove && <Button variant="ghost" onClick={onRemove} className="h-auto font-normal" aria-label="Remove trigger" style={{ ...ghostBtn, color: "var(--red3)", padding: "6px 4px" }}>✕</Button>}
    </div>
  );
}

/* ── DS-11 · "Use an integration" ──────────────────────────────────────────────
 *
 * Two pickers and then the operation's own fields — and every one of those three is
 * SERVED. The grants come from `/integrations/connections` (filtered to the caller by
 * the route, so this cannot render somebody else's consent); the operations and their
 * ports come from `/integrations/operations?connection_id=`, per grant, because whether
 * a grant carries the scope an operation needs is a fact about the pair and only the
 * server can answer it. A client that computed that itself would be the mirrored
 * contract this plane keeps paying to avoid.
 */

/** This user's grants — a hook rather than a prop for `useAutomationVocabulary`'s
 *  reason: the row renders on two surfaces and a prop is a thing one of them forgets
 *  to pass.
 *
 *  Deliberately NOT module-cached the way the vocabulary is, and the difference is the
 *  point: a vocabulary is a fact about this VERSION and cannot change while the page is
 *  open, while a grant is mutable state a person edits elsewhere. A page that cached it
 *  once would keep saying "No connected accounts" to someone who had just connected one
 *  in another tab, with no way back but a reload. */
export function useIntegrationGrants(): IntegrationConnection[] {
  const [grants, setGrants] = React.useState<IntegrationConnection[]>([]);
  React.useEffect(() => {
    let live = true;
    void getIntegrationConnections().catch(() => [])
      .then(g => { if (live) setGrants(g); });
    return () => { live = false; };
  }, []);
  return grants;
}

/** The operations ONE grant may run. Keyed by connection because the availability of a
 *  row is a property of the pair — the same Google account may read mail and not send
 *  it — and a roster cached across grants would show one account's answer for another.
 *
 *  Cached, unlike the grants above, because the only thing that moves a grant's roster
 *  is re-consenting to different scopes — and that happens through the provider's own
 *  consent screen, which navigates this page away and back. */
const opsCache = new Map<string, Promise<IntegrationOperation[]>>();

export function useIntegrationOperations(connectionId: string): IntegrationOperation[] {
  // The loaded roster is stored WITH the grant it belongs to, and a mismatch reads as
  // empty. Not a style point: holding a bare list would leave the previous account's
  // operations on screen for the render between switching grants and the fetch landing —
  // and an author who picks in that window picks an operation for the wrong consent.
  const [loaded, setLoaded] =
    React.useState<{ id: string; ops: IntegrationOperation[] }>({ id: "", ops: [] });
  React.useEffect(() => {
    if (!connectionId) return;
    let cached = opsCache.get(connectionId);
    if (!cached) {
      cached = getIntegrationOperations(connectionId).catch(() => []);
      opsCache.set(connectionId, cached);
    }
    let live = true;
    void cached.then(o => { if (live) setLoaded({ id: connectionId, ops: o }); });
    return () => { live = false; };
  }, [connectionId]);
  return loaded.id === connectionId ? loaded.ops : [];
}

export function IntegrationRows({ e, onChange }: {
  e: AutoEffect; onChange: (e: AutoEffect) => void;
}) {
  const grants = useIntegrationGrants();
  const connectionId = String(e.config.connection_id ?? "");
  const ops = useIntegrationOperations(connectionId);
  const operationId = String(e.config.operation ?? "");
  const op = ops.find(o => o.id === operationId);
  const params = (e.config.params ?? {}) as Record<string, unknown>;

  const set = (patch: Record<string, unknown>) =>
    onChange({ ...e, config: { ...e.config, ...patch } });
  const setParam = (name: string, value: unknown) =>
    set({ params: { ...params, [name]: value } });

  // A grant that cannot be spent is not offered: `revoked` is dead and
  // `needs_reconnect` is a refusal the provider already made. The sentence is the
  // palette's own, word for word — two surfaces explaining one absence differently is
  // how a reader learns the product has two opinions about it.
  const usable = grants.filter(g => g.status === "active");
  // A grant this step was AUTHORED against and the picker cannot offer — revoked since,
  // or belonging to someone else. Kept and marked, never silently dropped: a `<select>`
  // whose value matches no option renders as the placeholder, so a step that says "act
  // as sales@…" would read as one nobody had configured yet, and the next save would
  // make that true. The Otherwise picker states the same rule one field over, and this
  // repo has already paid for a client that could not SEE a field dropping it.
  const orphanGrant = !!connectionId && !usable.some(g => g.id === connectionId);
  const orphanOp = !!operationId && ops.length > 0 && !op;
  if (usable.length === 0 && !connectionId) {
    return (
      <div className="aug-fs-xs" style={{ color: "var(--amb4)", padding: "6px 0" }}>
        No connected accounts — connect one under Integrations, then this step can act as it.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <select style={inputStyle} value={connectionId} aria-label="Act as"
        onChange={ev => set({ connection_id: ev.target.value, operation: "", params: {} })}>
        <option value="">Act as…</option>
        {usable.map(g => (
          <option key={g.id} value={g.id}>
            {g.provider}{g.account ? ` · ${g.account}` : ""}
          </option>
        ))}
        {orphanGrant && <option value={connectionId}>{connectionId} (missing)</option>}
      </select>
      {connectionId && (
        <select style={inputStyle} value={operationId} aria-label="Operation"
          onChange={ev => set({ operation: ev.target.value, params: {} })}>
          <option value="">Do what…</option>
          {ops.map(o => (
            <option key={o.id} value={o.id}>
              {o.label}{o.writes ? " (write)" : ""}
            </option>
          ))}
          {orphanOp && <option value={operationId}>{operationId} (missing)</option>}
        </select>
      )}
      {orphanGrant && (
        <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
          This step acts as an account you can no longer pick — reconnect it under
          Integrations, or choose another.
        </div>
      )}
      {/* The server's own sentence about THIS pair. Rendered rather than paraphrased:
          it names the scope that is missing and the door that grants it. */}
      {op && op.availability !== "ready" && op.reason && (
        <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>{op.reason}</div>
      )}
      {op?.writes && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          A write — it passes the approval gate before it runs.
        </div>
      )}
      {op?.params.map(prm => (
        <input key={prm.name} style={inputStyle}
          aria-label={prm.label || prm.name}
          value={fieldText(params[prm.name])}
          onChange={ev => setParam(prm.name,
            // Bindable fields accept a binding object; the rest are plain values. Same
            // reason `slack_post`'s message is free text: a field whose value is
            // `{"$from": "step1.answer"}` is the whole point of the chain, and
            // `String(obj)` renders "[object Object]" — an editor inviting someone to
            // overwrite the wiring that makes it work.
            prm.bindable ? parseMessage(ev.target.value) : ev.target.value)}
          placeholder={`${prm.label || prm.name}${prm.required ? "" : " (optional)"}`
            + (prm.placeholder ? ` — e.g. ${prm.placeholder}` : "")} />
      ))}
    </div>
  );
}

export function EffectRow({ e, agents, bots = [], siblings, index = 0, onChange, onRemove }: {
  e: AutoEffect; agents: UserAgent[];
  /** W1 — the step list this row belongs to, so its "Only if" picker can offer what the
   *  steps BEFORE it publish. Defaults to the row alone, which offers nothing: a surface
   *  that has not been taught about order shows no guard rather than a wrong one. */
  siblings?: AutoEffect[]; index?: number;
  /** The bots a "Post to Slack" step may post AS. Empty ⇒ the row says so rather than
   *  offering an empty picker, because "no bots configured" and "pick a bot" call for
   *  different actions and only one of them is something the reader can do here. */
  bots?: SlackBotSummary[];
  onChange: (e: AutoEffect) => void; onRemove?: () => void;
}) {
  const set = (patch: Record<string, unknown>) => onChange({ ...e, config: { ...e.config, ...patch } });
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 8 }}>
      <select value={e.kind} onChange={ev => onChange({ kind: ev.target.value as EffectKind, config: {} })}
        aria-label="Action kind"
        style={{ ...inputStyle, width: 150 }}>
        {EFFECT_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
      </select>
      <div style={{ flex: 1 }}>
        {e.kind === "notify" && (
          <input style={inputStyle} value={String(e.config.trigger_id ?? "")} onChange={ev => set({ trigger_id: ev.target.value })} placeholder="Notifications trigger id" />
        )}
        {e.kind === "investigate" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input style={inputStyle} value={String(e.config.question ?? "")} onChange={ev => set({ question: ev.target.value })} placeholder="Agent question" />
            {agents.length > 0 && (
              <select style={inputStyle} value={String(e.config.agent_id ?? "")}
                aria-label="Run as agent"
                onChange={ev => set({ agent_id: ev.target.value })}>
                <option value="">Run unbound (no agent)</option>
                {agents.filter(a => a.enabled).map(a => (
                  <option key={a.id} value={a.id}>Run as {a.name}</option>
                ))}
              </select>
            )}
          </div>
        )}
        {e.kind === "brief" && (
          <input style={inputStyle} value={String(e.config.subscription_id ?? "")} onChange={ev => set({ subscription_id: ev.target.value })} placeholder="briefing subscription id" />
        )}
        {e.kind === "slack_post" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {bots.length === 0 ? (
              <div className="aug-fs-xs" style={{ color: "var(--amb4)", padding: "6px 0" }}>
                No Slack bots configured — create one first, then this step can post as it.
              </div>
            ) : (
              <select style={inputStyle} value={String(e.config.bot_id ?? "")}
                aria-label="Post as bot"
                onChange={ev => set({ bot_id: ev.target.value })}>
                <option value="">Post as…</option>
                {bots.filter(b => b.enabled).map(b => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            )}
            {/* Bound like the message below it, and for the same reason: B1 made
                `channel` bindable, and `String({$from: …})` renders "[object Object]" —
                an editor inviting someone to overwrite the binding that makes the chain
                work. Found by driving a step whose channel reads `item.room`. */}
            <input style={inputStyle} value={fieldText(e.config.channel)}
              onChange={ev => set({ channel: parseMessage(ev.target.value) })}
              placeholder="channel — e.g. #aughor-canvas or C0…" />
            {/* Left as free text on purpose: a step whose message is
                `{"$from": "step1.answer"}` is the whole reason the chain exists, and a
                plain input is the only editor that can hold either that or a sentence. */}
            <input style={inputStyle} value={messageText(e)}
              onChange={ev => set({ message: parseMessage(ev.target.value) })}
              placeholder={'message, or {"$from": "step1.answer"} to post an earlier step'} />
          </div>
        )}
        {e.kind === "integration_call" && <IntegrationRows e={e} onChange={onChange} />}
        {e.kind === "kinetic_action" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input style={inputStyle} value={String(e.config.action_id ?? "")} onChange={ev => set({ action_id: ev.target.value })} placeholder="declared action id" />
            <input style={inputStyle} value={paramsTextOf(e)} onChange={ev => set({ paramsText: ev.target.value })} placeholder='params JSON e.g. {"amount": 500}' />
          </div>
        )}
        {/* DS-12 — one field each, and it is a NAME, not SQL. The governed object is
            chosen from the registry (`/components?family=metric`), the same way the
            declared-action picker reads the ontology route rather than making the
            author remember an id. */}
        {e.kind === "metric_value" && (
          <input style={inputStyle} value={String(e.config.metric ?? "")}
            onChange={ev => set({ metric: ev.target.value })}
            placeholder="metric name, e.g. revenue" />
        )}
        {e.kind === "trusted_query" && (
          <input style={inputStyle} value={String(e.config.query_id ?? "")}
            onChange={ev => set({ query_id: ev.target.value })}
            placeholder="trusted query id" />
        )}
        <GuardRows e={e} siblings={siblings ?? [e]} index={siblings ? index : 0}
          onChange={onChange} />
        <OtherwiseRows e={e} siblings={siblings ?? [e]} index={siblings ? index : 0}
          onChange={onChange} />
        <ForEachRows e={e} onChange={onChange} />
      </div>
      {onRemove && <Button variant="ghost" onClick={onRemove} className="h-auto font-normal" aria-label="Remove action" style={{ ...ghostBtn, color: "var(--red3)", padding: "6px 4px" }}>✕</Button>}
    </div>
  );
}

/**
 * The wire shape of an effect list, with the one field the editor keeps out of band.
 *
 * Declared-action params are edited as TEXT (`paramsText`) because a half-typed JSON
 * object is not a JSON object, and parsing on every keystroke would fight the typist.
 * The parse therefore happens once, here, at save — and both surfaces call this rather
 * than each remembering to strip the field. Throws with a readable message; the caller
 * decides how to show it.
 */
/**
 * What the params editor shows: the text being typed, else the params already stored.
 *
 * Without the second half the field opens BLANK on an automation that has params, and
 * `effectsForWire` then reads "untouched" as "{}" — so editing an automation's name
 * through this form erased the params of every declared-action step in it. Fifth of the
 * PUT-erase family in this subsystem, and the first one INSIDE an effect rather than
 * around the record.
 */
function paramsTextOf(e: AutoEffect): string {
  const cfg = e.config as Record<string, unknown> & { paramsText?: string };
  if (typeof cfg.paramsText === "string") return cfg.paramsText;
  const params = cfg.params;
  return params && typeof params === "object" ? JSON.stringify(params) : "";
}

/** The kinds whose params are authored as free TEXT, and what to say when the text is
 *  not JSON. Keyed rather than `if/else`d so a second one is a row here, and so each
 *  kind's refusal names ITSELF rather than borrowing another kind's noun.
 *
 *  `integration_call` is deliberately ABSENT: DS-11 gives it a generated form built from
 *  the operation's declared params, so its `params` is already a real object and running
 *  it through the text path would stringify a structure that was never a string. */
const PARAMS_AS_TEXT: Record<string, string> = {
  kinetic_action: "Declared-action params must be valid JSON",
};

export function effectsForWire(effects: AutoEffect[]): AutoEffect[] {
  return effects.map(e => {
    const complaint = PARAMS_AS_TEXT[e.kind];
    if (!complaint) return e;
    const cfg = e.config as Record<string, unknown> & { paramsText?: string };
    // No `paramsText` at all means the editor was never opened on this step — carry its
    // stored `params` through untouched. Reading absence as "{}" is what erased them.
    if (typeof cfg.paramsText !== "string") return e;
    const raw = cfg.paramsText.trim() || "{}";
    const { paramsText: _omit, ...rest } = cfg;
    void _omit;
    let params: unknown;
    try {
      params = JSON.parse(raw);
    } catch {
      throw new Error(complaint);
    }
    // SPREAD, not a fresh literal. The version of this that lived in the form rebuilt
    // the effect as `{kind, config}` — which silently dropped `alias`, the key VA-4a's
    // `{"$from": "step1.ts"}` bindings point at. Saving a chained automation through the
    // form would have quietly unwired its own dataflow. Spreading keeps every field the
    // server sent, including ones this client has no opinion about.
    return { ...e, config: { ...rest, params } };
  });
}
