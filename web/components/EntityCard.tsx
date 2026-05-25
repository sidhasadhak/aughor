"use client";

import { useState } from "react";
import CheckCircleIcon  from "@atlaskit/icon/core/check-circle";
import CloseIcon        from "@atlaskit/icon/core/close";
import ChevronDownIcon  from "@atlaskit/icon/core/chevron-down";
import EditIcon         from "@atlaskit/icon/core/edit";
import CheckIcon        from "@atlaskit/icon/core/check-circle";
import {
  OntologyEntity,
  OntologyAction,
  OntologyMetric,
  patchOntologyEntity,
} from "@/lib/api";

interface Props {
  entity: OntologyEntity;
  connectionId: string;
  relatedActions: OntologyAction[];
  relatedMetrics: OntologyMetric[];
  onUpdated: (e: OntologyEntity) => void;
}

function GrainBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-400 border border-emerald-500/25 bg-emerald-500/10 rounded-full px-2 py-0.5">
      <CheckCircleIcon label="" size="small" /> grain verified
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium text-zinc-500 border border-zinc-600 bg-zinc-800 rounded-full px-2 py-0.5">
      grain unverified
    </span>
  );
}

function LifecycleViz({ states, terminalStates }: { states: string[]; terminalStates: string[] }) {
  if (!states.length) return null;
  const terminalSet = new Set(terminalStates.map(s => s.toLowerCase()));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {states.map((s, i) => {
        const isTerminal = terminalSet.has(s.toLowerCase());
        return (
          <span key={s} className="flex items-center gap-1">
            <span className={`
              text-[10px] font-mono px-2 py-0.5 rounded border
              ${isTerminal
                ? "text-red-400 border-red-500/25 bg-red-500/10"
                : "text-zinc-300 border-zinc-600/70 bg-zinc-800"}
            `}>
              {s}
            </span>
            {i < states.length - 1 && (
              <span className="text-zinc-600 text-[10px]">→</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

function SqlBlock({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition"
      >
        <span className={`transition-transform ${open ? "rotate-180" : ""}`}>
          <ChevronDownIcon label="" size="small" />
        </span>
        view SQL
      </button>
      {open && (
        <pre className="mt-1.5 text-[10px] font-mono text-zinc-300 bg-zinc-950 border border-zinc-700/60 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">
          {sql}
        </pre>
      )}
    </div>
  );
}

function EditableDescription({
  value,
  onSave,
}: {
  value: string;
  onSave: (v: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (draft === value) { setEditing(false); return; }
    setSaving(true);
    try { await onSave(draft); setEditing(false); } finally { setSaving(false); }
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-1.5">
        <textarea
          value={draft}
          onChange={e => setDraft(e.target.value)}
          rows={2}
          className="text-xs text-zinc-200 bg-zinc-800 border border-violet-500/50 rounded px-2 py-1.5 resize-none focus:outline-none w-full"
          autoFocus
        />
        <div className="flex gap-2">
          <button
            onClick={save}
            disabled={saving}
            className="flex items-center gap-1 text-[10px] text-emerald-400 hover:text-emerald-300 transition"
          >
            <CheckIcon label="" size="small" /> {saving ? "saving…" : "save"}
          </button>
          <button
            onClick={() => { setDraft(value); setEditing(false); }}
            className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition"
          >
            <CloseIcon label="" size="small" /> cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex items-start gap-2">
      <p className="text-xs text-zinc-400 leading-relaxed flex-1">
        {value || <span className="text-zinc-600 italic">No description yet</span>}
      </p>
      <button
        onClick={() => setEditing(true)}
        className="text-zinc-600 hover:text-zinc-400 opacity-0 group-hover:opacity-100 transition shrink-0 mt-0.5"
      >
        <EditIcon label="Edit" size="small" />
      </button>
    </div>
  );
}

export function EntityCard({ entity, connectionId, relatedActions, relatedMetrics, onUpdated }: Props) {
  const saveDescription = async (description: string) => {
    const updated = await patchOntologyEntity(connectionId, entity.id, { description });
    onUpdated(updated);
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-base font-semibold text-zinc-100">{entity.display_name}</h2>
          <GrainBadge verified={entity.grain_verified} />
        </div>
      </div>

      {/* Description */}
      <EditableDescription value={entity.description} onSave={saveDescription} />

      {/* Identity */}
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="bg-zinc-800/60 border border-zinc-700/60 rounded-lg p-3">
          <p className="text-zinc-500 text-[10px] uppercase tracking-wider mb-1">Identity Key</p>
          <code className="text-violet-300 font-mono">{entity.identity_key}</code>
        </div>
        <div className="bg-zinc-800/60 border border-zinc-700/60 rounded-lg p-3">
          <p className="text-zinc-500 text-[10px] uppercase tracking-wider mb-1">Source Tables</p>
          <div className="flex flex-wrap gap-1">
            {entity.source_tables.map(t => (
              <code key={t} className="text-sky-300 font-mono text-[10px]">{t}</code>
            ))}
          </div>
        </div>
      </div>

      {/* Lifecycle */}
      {entity.has_lifecycle && entity.lifecycle_states.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">
            Lifecycle · <code className="text-zinc-400 font-mono">{entity.lifecycle_column}</code>
          </p>
          <LifecycleViz states={entity.lifecycle_states} terminalStates={entity.terminal_states} />
          {entity.active_filter && (
            <div className="mt-2 flex items-start gap-2 text-[10px] text-amber-300 bg-amber-500/8 border border-amber-500/20 rounded-lg px-3 py-2">
              <span className="shrink-0 font-semibold uppercase tracking-wide">Rule</span>
              <code className="font-mono">{entity.active_filter}</code>
            </div>
          )}
        </div>
      )}

      {/* Business rules */}
      {entity.default_filters.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Default Filters</p>
          {entity.default_filters.map((f, i) => (
            <code key={i} className="block text-[10px] font-mono text-zinc-300 bg-zinc-800 border border-zinc-700/60 rounded px-2 py-1">
              {f}
            </code>
          ))}
        </div>
      )}

      {/* Related actions */}
      {relatedActions.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Actions</p>
          {relatedActions.map(a => (
            <div key={a.id} className="bg-zinc-800/50 border border-zinc-700/50 rounded-lg p-3 space-y-1.5">
              <div className="flex items-center gap-2">
                <code className="text-[11px] font-mono text-violet-300">ACTION:{a.id}()</code>
                <span className="text-[9px] uppercase tracking-wider text-zinc-500 border border-zinc-600 rounded px-1.5 py-0.5">{a.action_type}</span>
              </div>
              <p className="text-[11px] text-zinc-400">{a.description}</p>
              {a.business_rules_enforced.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {a.business_rules_enforced.map((r, i) => (
                    <span key={i} className="text-[9px] text-amber-400/80 bg-amber-500/8 border border-amber-500/15 rounded px-1.5 py-0.5">{r}</span>
                  ))}
                </div>
              )}
              <SqlBlock sql={a.sql_template} />
            </div>
          ))}
        </div>
      )}

      {/* Related metrics */}
      {relatedMetrics.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Metrics</p>
          {relatedMetrics.map(m => (
            <div key={m.id} className="bg-zinc-800/50 border border-zinc-700/50 rounded-lg p-3 space-y-1.5">
              <p className="text-[11px] font-semibold text-zinc-200">{m.display_name}</p>
              {m.description && <p className="text-[11px] text-zinc-400">{m.description}</p>}
              <code className="block text-[10px] font-mono text-emerald-300">{m.formula_sql}</code>
              {m.unit && <span className="text-[10px] text-zinc-500">Unit: {m.unit}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
