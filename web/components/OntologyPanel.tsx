"use client";

import { useEffect, useState } from "react";
import CloseIcon       from "@atlaskit/icon/core/close";
import ChevronDownIcon from "@atlaskit/icon/core/chevron-down";
import NodeIcon        from "@atlaskit/icon/core/node";
import SettingsIcon    from "@atlaskit/icon/core/settings";
import {
  getOntology,
  patchOntologyAction,
  patchOntologyEntity,
  getEntityLifecycleCounts,
  getConnectionSettings,
  updateConnectionSettings,
  rebuildOntology,
  type OntologyGraph,
  type OntologyEntity,
  type OntologyAction,
  type OntologyRelationship,
  type LifecycleCount,
  type ConnectionSettings,
} from "@/lib/api";
import { OntologyCanvas } from "./OntologyCanvas";
import { ProcessMapper } from "./ProcessMapper";
import { cn } from "@/lib/utils";

// ── Small reusable bits ───────────────────────────────────────────────────────

function SqlToggle({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition mt-1"
      >
        <span className={cn("transition-transform", open && "rotate-180")}>
          <ChevronDownIcon label="" size="small" />
        </span>
        SQL
      </button>
      {open && (
        <pre className="mt-1.5 text-[10px] font-mono text-zinc-300 bg-zinc-950 border border-zinc-700/60 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">
          {sql}
        </pre>
      )}
    </div>
  );
}

function ConfidencePill({ c }: { c: string }) {
  const cls =
    c === "verified" ? "text-emerald-400 border-emerald-500/25 bg-emerald-500/8"
    : c === "exact"  ? "text-sky-400 border-sky-500/25 bg-sky-500/8"
    :                  "text-zinc-500 border-zinc-600 bg-zinc-800";
  return (
    <span className={cn("text-[8px] uppercase tracking-wide border rounded px-1.5 py-0.5", cls)}>
      {c}
    </span>
  );
}

// ── Entity detail drawer ──────────────────────────────────────────────────────

type DrawerTab = "overview" | "relationships" | "actions" | "metrics" | "map";

function EntityDetailDrawer({
  entity,
  graph,
  connectionId,
  onClose,
  onEntityUpdated,
  onActionUpdated,
  onInvestigate,
}: {
  entity: OntologyEntity;
  graph: OntologyGraph;
  connectionId: string;
  onClose: () => void;
  onEntityUpdated: (e: OntologyEntity) => void;
  onActionUpdated: (a: OntologyAction) => void;
  onInvestigate?: (q: string) => void;
}) {
  const [tab, setTab] = useState<DrawerTab>("overview");
  const [editingDesc, setEditingDesc] = useState(false);
  const [draft, setDraft] = useState(entity.description);
  const [saving, setSaving] = useState(false);
  const [lifecycleCounts, setLifecycleCounts] = useState<LifecycleCount[] | null>(null);

  useEffect(() => {
    if (!entity.has_lifecycle || !entity.lifecycle_column) return;
    getEntityLifecycleCounts(connectionId, entity.id)
      .then(setLifecycleCounts)
      .catch(() => {});
  }, [connectionId, entity.id, entity.has_lifecycle, entity.lifecycle_column]);

  const countMap = Object.fromEntries(
    (lifecycleCounts ?? []).map(c => [c.state, c.count]),
  );
  const totalActive = (lifecycleCounts ?? [])
    .filter(c => !entity.terminal_states.includes(c.state))
    .reduce((s, c) => s + c.count, 0);

  const incomingRels = Object.values(graph.relationships).filter(
    r => r.to_entity === entity.id,
  );
  const outgoingRels = Object.values(graph.relationships).filter(
    r => r.from_entity === entity.id,
  );
  const actions = Object.values(graph.actions).filter(
    a => a.entity === entity.id,
  );
  const metrics = Object.values(graph.metrics).filter(
    m => m.entity === entity.id,
  );

  const saveDesc = async () => {
    if (draft === entity.description) { setEditingDesc(false); return; }
    setSaving(true);
    try {
      const updated = await patchOntologyEntity(connectionId, entity.id, {
        description: draft,
      });
      onEntityUpdated(updated);
      setEditingDesc(false);
    } finally { setSaving(false); }
  };

  const tabs: { id: DrawerTab; label: string; count?: number }[] = [
    { id: "overview",      label: "Overview" },
    { id: "relationships", label: "Relations",  count: incomingRels.length + outgoingRels.length },
    { id: "actions",       label: "Actions",    count: actions.length },
    { id: "metrics",       label: "Metrics",    count: metrics.length },
    ...(entity.has_lifecycle ? [{ id: "map" as DrawerTab, label: "Map" }] : []),
  ];

  return (
    <div className="w-80 shrink-0 border-l border-zinc-700/70 flex flex-col bg-zinc-900 overflow-hidden">
      {/* Drawer header */}
      <div className="px-4 pt-4 pb-3 border-b border-zinc-700/60 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <p className="text-sm font-semibold text-zinc-100 truncate">{entity.display_name}</p>
            {entity.domain && (
              <span className="text-[8px] uppercase tracking-wide border border-violet-500/25 bg-violet-500/8 text-violet-400 rounded px-1.5 py-0.5 shrink-0">
                {entity.domain}
              </span>
            )}
          </div>
          <p className="text-[10px] font-mono text-zinc-600 truncate">{entity.source_tables[0]}</p>
          {lifecycleCounts && totalActive > 0 && (
            <p className="text-[9px] text-emerald-400/70 mt-0.5">
              {totalActive.toLocaleString()} active records
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {onInvestigate && (
            <button
              onClick={() => {
                const q = entity.active_filter
                  ? `Investigate ${entity.display_name}: what is driving recent changes? Focus on active records (${entity.active_filter}).`
                  : `Investigate ${entity.display_name}: what is driving recent changes in this entity?`;
                onInvestigate(q);
              }}
              className="text-[9px] text-violet-400 hover:text-violet-300 border border-violet-500/30 hover:border-violet-400/50 rounded px-2 py-1 transition"
            >
              Investigate →
            </button>
          )}
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-300 transition mt-0.5"
          >
            <CloseIcon label="Close" size="small" />
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-zinc-700/60 px-1 shrink-0">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-3 py-2.5 text-[10px] font-medium transition border-b-2 -mb-px capitalize",
              tab === t.id
                ? "border-violet-500 text-violet-400"
                : "border-transparent text-zinc-500 hover:text-zinc-300",
            )}
          >
            {t.label ?? t.id}
            {typeof t.count === "number" && t.count > 0 && (
              <span className="ml-1 text-[9px] text-zinc-600">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Drawer body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">

        {/* ── Overview ─────────────────────────────────────────────────────── */}
        {tab === "overview" && (
          <>
            {/* Description */}
            <div>
              <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5 font-semibold">
                Description
              </p>
              {editingDesc ? (
                <div className="space-y-1.5">
                  <textarea
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    rows={3}
                    className="w-full text-xs bg-zinc-800 border border-violet-500/40 rounded px-2 py-1.5 text-zinc-200 focus:outline-none resize-none"
                    autoFocus
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={saveDesc}
                      disabled={saving}
                      className="text-[10px] text-emerald-400 hover:text-emerald-300 disabled:opacity-40"
                    >
                      {saving ? "saving…" : "save"}
                    </button>
                    <button
                      onClick={() => { setDraft(entity.description); setEditingDesc(false); }}
                      className="text-[10px] text-zinc-500 hover:text-zinc-300"
                    >
                      cancel
                    </button>
                  </div>
                </div>
              ) : (
                <p
                  className="text-zinc-400 cursor-pointer hover:text-zinc-300 transition leading-relaxed"
                  onClick={() => setEditingDesc(true)}
                  title="Click to edit"
                >
                  {entity.description || (
                    <span className="text-zinc-700 italic">Click to add description…</span>
                  )}
                </p>
              )}
            </div>

            {/* Grain */}
            <div>
              <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5 font-semibold">
                Identity key
              </p>
              <code className="text-zinc-400 font-mono">{entity.identity_key}</code>
              <span className={cn(
                "ml-2 text-[9px] border rounded px-1.5 py-0.5",
                entity.grain_verified
                  ? "text-emerald-400 border-emerald-500/25"
                  : "text-zinc-500 border-zinc-600",
              )}>
                {entity.grain_verified ? "grain verified" : "grain unverified"}
              </span>
            </div>

            {/* Lifecycle */}
            {entity.has_lifecycle && (
              <div>
                <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5 font-semibold">
                  Lifecycle — <span className="font-mono normal-case">{entity.lifecycle_column}</span>
                </p>
                <div className="flex flex-wrap gap-1 mb-2">
                  {entity.lifecycle_states.map(s => {
                    const isTerm = entity.terminal_states.includes(s);
                    const cnt = countMap[s];
                    return (
                      <span
                        key={s}
                        className={cn(
                          "text-[9px] font-mono rounded px-1.5 py-0.5 border flex items-center gap-1",
                          isTerm
                            ? "text-zinc-500 border-zinc-600/60 bg-zinc-800/50"
                            : "text-violet-300 border-violet-500/20 bg-violet-500/10",
                        )}
                      >
                        {s}
                        {cnt !== undefined && (
                          <span className={cn(
                            "text-[8px] font-sans tabular-nums",
                            isTerm ? "text-zinc-600" : "text-violet-400/70",
                          )}>
                            {cnt.toLocaleString()}
                          </span>
                        )}
                      </span>
                    );
                  })}
                </div>
                {entity.active_filter && (
                  <div>
                    <p className="text-[9px] text-zinc-600 mb-1">Active filter</p>
                    <code className="text-[10px] text-emerald-300 font-mono bg-zinc-800 border border-zinc-700/60 rounded px-2 py-1 block">
                      {entity.active_filter}
                    </code>
                  </div>
                )}
              </div>
            )}

            {/* Business rules */}
            {entity.default_filters.length > 0 && (
              <div>
                <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5 font-semibold">
                  Default filters
                </p>
                <div className="space-y-1">
                  {entity.default_filters.map((f, i) => (
                    <code key={i} className="block text-[10px] font-mono text-amber-300/80 bg-zinc-800 border border-zinc-700/40 rounded px-2 py-1">
                      {f}
                    </code>
                  ))}
                </div>
              </div>
            )}

            {/* Computed properties */}
            {entity.computed_properties && entity.computed_properties.length > 0 && (
              <div>
                <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5 font-semibold">
                  Computed properties
                </p>
                <div className="space-y-1.5">
                  {entity.computed_properties.map(cp => (
                    <div key={cp.id} className="bg-zinc-800/50 border border-zinc-700/40 rounded-lg px-2.5 py-2 space-y-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] text-zinc-300 font-medium">{cp.label}</span>
                        {cp.unit && (
                          <span className="text-[9px] text-zinc-600 border border-zinc-700 rounded px-1 py-0.5">
                            {cp.unit}
                          </span>
                        )}
                      </div>
                      <code className="block text-[9px] font-mono text-emerald-300/80 leading-snug">
                        {cp.formula_sql}
                      </code>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* ── Relationships ─────────────────────────────────────────────────── */}
        {tab === "relationships" && (
          <div className="space-y-3">
            {[
              { label: "Outgoing", rels: outgoingRels },
              { label: "Incoming", rels: incomingRels },
            ].map(({ label, rels }) =>
              rels.length > 0 ? (
                <div key={label}>
                  <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-2 font-semibold">
                    {label}
                  </p>
                  <div className="space-y-2">
                    {rels.map(r => (
                      <RelationshipRow key={r.id} rel={r} fromPov={entity.id} />
                    ))}
                  </div>
                </div>
              ) : null,
            )}
            {incomingRels.length === 0 && outgoingRels.length === 0 && (
              <p className="text-zinc-600 text-center py-6">No relationships.</p>
            )}
          </div>
        )}

        {/* ── Actions ──────────────────────────────────────────────────────── */}
        {tab === "actions" && (
          <div className="space-y-3">
            {actions.length === 0 ? (
              <p className="text-zinc-600 text-center py-6">No actions defined.</p>
            ) : (
              actions.map(a => (
                <ActionRow
                  key={a.id}
                  action={a}
                  connectionId={connectionId}
                  onUpdated={onActionUpdated}
                />
              ))
            )}
          </div>
        )}

        {/* ── Metrics ──────────────────────────────────────────────────────── */}
        {tab === "metrics" && (
          <div className="space-y-3">
            {metrics.length === 0 ? (
              <p className="text-zinc-600 text-center py-6">No metrics defined.</p>
            ) : (
              metrics.map(m => (
                <div key={m.id} className="bg-zinc-800/50 border border-zinc-700/50 rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <p className="text-xs font-semibold text-zinc-200">{m.display_name}</p>
                    {m.unit && <span className="text-[10px] text-zinc-500">{m.unit}</span>}
                  </div>
                  {m.description && <p className="text-zinc-500">{m.description}</p>}
                  <code className="block text-[10px] font-mono text-emerald-300 bg-zinc-950 border border-zinc-700/40 rounded px-2 py-1.5">
                    {m.formula_sql}
                  </code>
                </div>
              ))
            )}
          </div>
        )}

        {tab === "map" && (
          <ProcessMapper
            connId={connectionId}
            entityId={entity.id}
            onInvestigate={onInvestigate}
          />
        )}
      </div>
    </div>
  );
}

function RelationshipRow({
  rel,
  fromPov,
}: {
  rel: OntologyRelationship;
  fromPov: string;
}) {
  const isFrom = rel.from_entity === fromPov;
  return (
    <div className="bg-zinc-800/50 border border-zinc-700/40 rounded-lg px-3 py-2.5 space-y-1.5">
      <div className="flex items-center gap-1.5 flex-wrap">
        {isFrom ? (
          <>
            <span className="text-[10px] text-zinc-400 font-semibold">→</span>
            <span className="text-xs text-zinc-200">{rel.to_entity}</span>
          </>
        ) : (
          <>
            <span className="text-xs text-zinc-200">{rel.from_entity}</span>
            <span className="text-[10px] text-zinc-400 font-semibold">→</span>
          </>
        )}
        <span className="text-[10px] text-violet-400 font-mono">
          {rel.verb.toLowerCase().replace(/_/g, " ")}
        </span>
        <span className="text-[9px] font-mono text-zinc-500 border border-zinc-600 rounded px-1 py-0.5">
          {rel.cardinality}
        </span>
        <ConfidencePill c={rel.join_confidence} />
      </div>
      <code className="text-[9px] font-mono text-zinc-600 block truncate">{rel.join_sql}</code>
    </div>
  );
}

function ActionRow({
  action,
  connectionId,
  onUpdated,
}: {
  action: OntologyAction;
  connectionId: string;
  onUpdated: (a: OntologyAction) => void;
}) {
  const [editDesc, setEditDesc] = useState(false);
  const [draft, setDraft] = useState(action.description);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (draft === action.description) { setEditDesc(false); return; }
    setSaving(true);
    try {
      const updated = await patchOntologyAction(connectionId, action.id, { description: draft });
      onUpdated(updated);
      setEditDesc(false);
    } finally { setSaving(false); }
  };

  const typeColors: Record<string, string> = {
    filter:    "text-amber-400 border-amber-500/20 bg-amber-500/8",
    compute:   "text-violet-400 border-violet-500/20 bg-violet-500/8",
    traverse:  "text-sky-400 border-sky-500/20 bg-sky-500/8",
    aggregate: "text-emerald-400 border-emerald-500/20 bg-emerald-500/8",
    validate:  "text-rose-400 border-rose-500/20 bg-rose-500/8",
  };

  return (
    <div className="bg-zinc-800/50 border border-zinc-700/40 rounded-lg p-3 space-y-2">
      <div className="flex items-center gap-1.5 flex-wrap">
        <code className="text-[10px] font-mono text-violet-300 font-semibold truncate">
          {action.id}()
        </code>
        <span className={cn(
          "text-[8px] uppercase tracking-wider border rounded px-1.5 py-0.5",
          typeColors[action.action_type] ?? "text-zinc-500 border-zinc-600",
        )}>
          {action.action_type}
        </span>
      </div>

      {editDesc ? (
        <div className="space-y-1.5">
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            className="w-full text-xs bg-zinc-900 border border-violet-500/40 rounded px-2 py-1 text-zinc-200 focus:outline-none"
            autoFocus
          />
          <div className="flex gap-2">
            <button onClick={save} disabled={saving} className="text-[10px] text-emerald-400 hover:text-emerald-300 disabled:opacity-40">
              {saving ? "saving…" : "save"}
            </button>
            <button onClick={() => { setDraft(action.description); setEditDesc(false); }} className="text-[10px] text-zinc-500 hover:text-zinc-300">
              cancel
            </button>
          </div>
        </div>
      ) : (
        <p
          className="text-[10px] text-zinc-500 cursor-pointer hover:text-zinc-300 transition leading-relaxed"
          onClick={() => setEditDesc(true)}
          title="Click to edit"
        >
          {action.description || <span className="text-zinc-700 italic">No description</span>}
        </p>
      )}

      {action.business_rules_enforced.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {action.business_rules_enforced.map((r, i) => (
            <span key={i} className="text-[8px] text-amber-400/70 border border-amber-500/15 bg-amber-500/8 rounded px-1.5 py-0.5">
              {r}
            </span>
          ))}
        </div>
      )}

      <SqlToggle sql={action.sql_template} />
    </div>
  );
}

// ── Edge SQL template popup ───────────────────────────────────────────────────

function EdgeSqlPanel({
  rel,
  graph,
  onClose,
  onInvestigate,
}: {
  rel: OntologyRelationship;
  graph: OntologyGraph;
  onClose: () => void;
  onInvestigate?: (q: string) => void;
}) {
  const fromEntity = graph.entities[rel.from_entity];
  const toEntity   = graph.entities[rel.to_entity];

  const fromFilter = fromEntity?.active_filter ? `  -- active filter: ${fromEntity.active_filter}` : "";
  const toFilter   = toEntity?.active_filter   ? `  -- active filter: ${toEntity.active_filter}` : "";

  const sql = [
    `SELECT`,
    `  f.*, t.*`,
    `FROM ${rel.from_table} f`,
    `  ${rel.join_sql}`,
    ...(fromFilter ? [fromFilter] : []),
    ...(toFilter   ? [toFilter]   : []),
    `LIMIT 1000;`,
  ].join("\n");

  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(sql).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };

  const investigateQ = `Analyse the join between ${fromEntity?.display_name ?? rel.from_entity} and ${toEntity?.display_name ?? rel.to_entity}: what does this ${rel.verb.toLowerCase().replace(/_/g, " ")} relationship reveal?`;

  return (
    <div className="absolute bottom-16 left-1/2 -translate-x-1/2 z-30 w-[480px] max-w-[90vw] bg-zinc-900 border border-zinc-700/70 rounded-xl shadow-2xl shadow-black/60 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-zinc-700/60">
        <span className="text-[10px] text-violet-400 font-mono font-semibold flex-1 truncate">
          {fromEntity?.display_name ?? rel.from_entity}
          <span className="text-zinc-600 mx-1.5">→</span>
          {toEntity?.display_name ?? rel.to_entity}
          <span className="text-zinc-600 ml-2 font-sans font-normal">{rel.verb.toLowerCase().replace(/_/g, " ")}</span>
        </span>
        <span className="text-[8px] font-mono text-zinc-500 border border-zinc-700 rounded px-1.5 py-0.5">{rel.cardinality}</span>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 transition ml-1">
          <CloseIcon label="Close" size="small" />
        </button>
      </div>
      <pre className="text-[11px] font-mono text-zinc-300 bg-zinc-950 px-4 py-3 overflow-x-auto whitespace-pre leading-relaxed">
        {sql}
      </pre>
      <div className="flex items-center gap-2 px-4 py-2.5 border-t border-zinc-700/60">
        <button
          onClick={copy}
          className="text-[10px] text-zinc-400 hover:text-zinc-200 border border-zinc-700 hover:border-zinc-500 rounded px-2.5 py-1 transition"
        >
          {copied ? "Copied ✓" : "Copy SQL"}
        </button>
        {onInvestigate && (
          <button
            onClick={() => onInvestigate(investigateQ)}
            className="text-[10px] text-violet-400 hover:text-violet-300 border border-violet-500/30 hover:border-violet-400/50 rounded px-2.5 py-1 transition"
          >
            Send to Chat →
          </button>
        )}
        <span className="ml-auto text-[9px] text-zinc-700">click edge to inspect joins</span>
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  onInvestigate?: (q: string) => void;
}

const REFRESH_OPTIONS: { label: string; value: number | null }[] = [
  { label: "Off",      value: null },
  { label: "Daily",    value: 24   },
  { label: "Every 2d", value: 48   },
  { label: "Weekly",   value: 168  },
];

function OntologySettings({
  connectionId,
  graph,
  onClose,
  onRebuilt,
}: {
  connectionId: string;
  graph: OntologyGraph | null;
  onClose: () => void;
  onRebuilt: (g: OntologyGraph) => void;
}) {
  const [settings,    setSettings]    = useState<ConnectionSettings | null>(null);
  const [saving,      setSaving]      = useState(false);
  const [rebuilding,  setRebuilding]  = useState(false);
  const [rebuildMsg,  setRebuildMsg]  = useState<string | null>(null);

  useEffect(() => {
    getConnectionSettings(connectionId).then(setSettings).catch(() => {});
  }, [connectionId]);

  const saveRefresh = async (hours: number | null) => {
    setSaving(true);
    try {
      const updated = await updateConnectionSettings(connectionId, { ontology_refresh_hours: hours });
      setSettings(updated);
    } finally { setSaving(false); }
  };

  const handleRebuild = async () => {
    setRebuilding(true);
    setRebuildMsg(null);
    try {
      const result = await rebuildOntology(connectionId);
      setRebuildMsg(`Rebuilt — ${result.entities} entities`);
      const fresh = await import("@/lib/api").then(m => m.getOntology(connectionId));
      onRebuilt(fresh);
    } catch (e: unknown) {
      setRebuildMsg((e as Error).message ?? "Rebuild failed");
    } finally { setRebuilding(false); }
  };

  const currentHours = settings?.ontology_refresh_hours ?? null;

  return (
    <div className="w-72 shrink-0 border-l border-zinc-700/70 flex flex-col bg-zinc-900 overflow-hidden">
      <div className="px-4 pt-4 pb-3 border-b border-zinc-700/60 flex items-center justify-between">
        <p className="text-xs font-semibold text-zinc-200">Ontology Settings</p>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 transition">
          <CloseIcon label="Close" size="small" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Refresh schedule */}
        <div>
          <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-2 font-semibold">
            Auto-refresh interval
          </p>
          <p className="text-[10px] text-zinc-500 mb-3 leading-relaxed">
            Automatically invalidate and rebuild the ontology on a schedule.
            The rebuild runs in the background when the interval elapses.
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {REFRESH_OPTIONS.map(opt => (
              <button
                key={String(opt.value)}
                onClick={() => saveRefresh(opt.value)}
                disabled={saving}
                className={cn(
                  "py-2 text-[11px] rounded-lg border transition font-medium",
                  currentHours === opt.value
                    ? "bg-violet-500/15 border-violet-500/40 text-violet-300"
                    : "bg-zinc-800/60 border-zinc-700/50 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {currentHours && (
            <p className="text-[9px] text-violet-400/70 mt-2">
              Refreshes every {currentHours}h
            </p>
          )}
        </div>

        {/* Last built */}
        {graph && (
          <div>
            <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5 font-semibold">
              Last built
            </p>
            <p className="text-[10px] text-zinc-400 font-mono">
              {new Date(graph.generated_at).toLocaleString()}
            </p>
          </div>
        )}

        {/* Manual rebuild */}
        <div>
          <p className="text-[9px] text-zinc-600 uppercase tracking-wider mb-2 font-semibold">
            Manual rebuild
          </p>
          <button
            onClick={handleRebuild}
            disabled={rebuilding}
            className={cn(
              "w-full py-2 text-[11px] rounded-lg border transition",
              rebuilding
                ? "border-zinc-700 text-zinc-600 cursor-not-allowed"
                : "border-violet-500/30 text-violet-400 hover:bg-violet-500/10 hover:border-violet-400/50",
            )}
          >
            {rebuilding ? "Rebuilding…" : "Rebuild ontology now"}
          </button>
          {rebuildMsg && (
            <p className={cn(
              "text-[9px] mt-2",
              rebuildMsg.startsWith("Rebuilt") ? "text-emerald-400" : "text-red-400",
            )}>
              {rebuildMsg}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function OntologyPanel({ connectionId, onInvestigate }: Props) {
  const [graph,             setGraph]            = useState<OntologyGraph | null>(null);
  const [loading,           setLoading]          = useState(false);
  const [error,             setError]            = useState<string | null>(null);
  const [selectedEntityId,  setSelectedEntityId] = useState<string | null>(null);
  const [selectedEdge,      setSelectedEdge]     = useState<OntologyRelationship | null>(null);
  const [selectedConnId,    setSelectedConnId]   = useState(connectionId);
  const [showSettings,      setShowSettings]     = useState(false);

  useEffect(() => { setSelectedConnId(connectionId); }, [connectionId]);

  useEffect(() => {
    if (!selectedConnId) return;
    setLoading(true);
    setError(null);
    setGraph(null);
    setSelectedEntityId(null);
    setShowSettings(false);
    getOntology(selectedConnId)
      .then(setGraph)
      .catch(() =>
        setError(
          "Ontology not yet available for this connection. It builds automatically on the next query.",
        ),
      )
      .finally(() => setLoading(false));
  }, [selectedConnId]);

  const handleEntityUpdated = (updated: OntologyEntity) => {
    if (!graph) return;
    setGraph({ ...graph, entities: { ...graph.entities, [updated.id]: updated } });
  };

  const handleActionUpdated = (updated: OntologyAction) => {
    if (!graph) return;
    setGraph({ ...graph, actions: { ...graph.actions, [updated.id]: updated } });
  };

  const selectedEntity = selectedEntityId ? graph?.entities[selectedEntityId] ?? null : null;

  // ── Header bar ──────────────────────────────────────────────────────────────
  const headerBar = (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-700/70 shrink-0 bg-zinc-900/40">
      <p className="text-xs font-semibold text-zinc-300">Business Ontology</p>

      {graph && (
        <div className="flex items-center gap-2 ml-auto">
          {graph.enriched ? (
            <span className="text-[9px] text-emerald-400 border border-emerald-500/20 bg-emerald-500/8 rounded-full px-2 py-0.5">
              semantically enriched
            </span>
          ) : (
            <span className="text-[9px] text-zinc-500 border border-zinc-700 rounded-full px-2 py-0.5">
              structural only
            </span>
          )}
          <span className="text-[9px] text-zinc-600">
            {Object.keys(graph.entities).length} entities
            · {Object.keys(graph.relationships).length} relationships
          </span>
          <button
            onClick={() => { setShowSettings(v => !v); setSelectedEntityId(null); setSelectedEdge(null); }}
            className={cn(
              "text-zinc-500 hover:text-zinc-300 transition ml-1",
              showSettings && "text-violet-400",
            )}
            title="Ontology settings"
          >
            <SettingsIcon label="Settings" size="small" />
          </button>
        </div>
      )}
    </div>
  );

  // ── Loading / error states ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        {headerBar}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3">
            <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-zinc-500">Building ontology…</p>
          </div>
        </div>
      </div>
    );
  }

  if (error || !graph) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        {headerBar}
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center space-y-3 max-w-sm">
            <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center mx-auto">
              <NodeIcon label="" size="medium" color="var(--ds-icon-subtle)" />
            </div>
            <p className="text-sm text-zinc-400">
              {error ?? "No ontology data available."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Main: canvas + optional detail drawer ──────────────────────────────────
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {headerBar}

      <div className="flex-1 flex overflow-hidden">
        {/* Canvas — takes remaining width; relative so EdgeSqlPanel anchors correctly */}
        <div className="flex-1 overflow-hidden relative">
          <OntologyCanvas
            graph={graph}
            connId={connectionId}
            selectedEntityId={selectedEntityId}
            onSelectEntity={(id) => { setSelectedEntityId(id); setSelectedEdge(null); setShowSettings(false); }}
            onInvestigate={onInvestigate}
            onClickEdge={(rel) => setSelectedEdge(prev => prev?.id === rel.id ? null : rel)}
          />

          {/* Edge SQL template popup */}
          {selectedEdge && (
            <EdgeSqlPanel
              rel={selectedEdge}
              graph={graph}
              onClose={() => setSelectedEdge(null)}
              onInvestigate={onInvestigate}
            />
          )}
        </div>

        {/* Detail drawer — slides in when an entity is selected */}
        {selectedEntity && !showSettings && (
          <EntityDetailDrawer
            entity={selectedEntity}
            graph={graph}
            connectionId={selectedConnId}
            onClose={() => setSelectedEntityId(null)}
            onEntityUpdated={handleEntityUpdated}
            onActionUpdated={handleActionUpdated}
            onInvestigate={onInvestigate}
          />
        )}

        {/* Settings panel */}
        {showSettings && (
          <OntologySettings
            connectionId={selectedConnId}
            graph={graph}
            onClose={() => setShowSettings(false)}
            onRebuilt={(g) => setGraph(g)}
          />
        )}
      </div>
    </div>
  );
}
