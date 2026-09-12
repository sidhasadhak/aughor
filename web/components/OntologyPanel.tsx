"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { EntityTypeMap } from "@/components/ontology/EntityTypeMap";
import { MetricProvenancePanel } from "@/components/ontology/MetricProvenance";
import { OverridesDrawer } from "@/components/ontology/OverridesDrawer";
import { Button }      from "@/components/ui/button";
import {
  getOntology,
  patchQueryTemplate,
  patchOntologyEntity,
  getEntityLifecycleCounts,
  getConnectionSettings,
  updateConnectionSettings,
  rebuildOntology,
  getDuplicateEntities,
  mergeOntologyEntities,
  getLearnedSkills,
  activateLearnedSkill,
  deleteLearnedSkill,
  getAutonomy,
  type OntologyGraph,
  type OntologyEntity,
  type QueryTemplate,
  type OntologyRelationship,
  type LifecycleCount,
  type ConnectionSettings,
  type DuplicateCluster,
  type AutonomyLevel,
  getOntologyProposals, acceptOntologyProposal, dismissOntologyProposal,
  OntologyNotBuilt,
  type OntologyProposal,
} from "@/lib/api";
import { OntologyOrgCanvas } from "./OntologyOrgCanvas";
import { ProcessMapper } from "./ProcessMapper";
import { cn } from "@/lib/utils";
import { verbLabel, formatCount, formatTimestamp, countNoun } from "@/lib/format";
import { Icon } from "@/components/ui/icon";

// ── Small reusable bits ───────────────────────────────────────────────────────

// ── Resizable side drawer ─────────────────────────────────────────────────────


/**
 * Drawer width that persists across mounts, with a draggable left-edge handle.
 * Returns the current width plus a handle element to drop at the panel's leading
 * edge.  Dragging left widens the panel (it grows into the canvas); dragging
 * right shrinks it.  Width is clamped to [DRAWER_MIN, DRAWER_MAX] and saved to
 * localStorage so the choice sticks.
 */
// ── Entity detail drawer ──────────────────────────────────────────────────────


// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  onInvestigate?: (q: string) => void;
  /** Schema scope from the workspace's shared selector. The ontology store is
   *  keyed per {connection, schema}; without this the backend falls back to an
   *  ARBITRARY cached schema on multi-schema connections. */
  schema?: string;
}

const REFRESH_OPTIONS: { label: string; value: number | null }[] = [
  { label: "Off",      value: null },
  { label: "Daily",    value: 24   },
  { label: "Every 2d", value: 48   },
  { label: "Weekly",   value: 168  },
];

function OntologySettings({
  connectionId,
  schema,
  graph,
  onClose,
  onRebuilt,
}: {
  connectionId: string;
  schema?: string;
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
      const result = await rebuildOntology(connectionId, schema);
      setRebuildMsg(`Rebuilt — ${result.entities} entities`);
      const fresh = await import("@/lib/api").then(m => m.getOntology(connectionId, schema));
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
          <Icon name="close" size={16} label="Close" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Refresh schedule */}
        <div>
          <p className="aug-fs-xs text-zinc-500 uppercase tracking-wider mb-2 font-semibold">
            Auto-refresh interval
          </p>
          <p className="aug-fs-xs text-zinc-500 mb-3 leading-relaxed">
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
                  "py-2 aug-fs-xs rounded-[var(--r3)] border transition font-medium",
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
            <p className="aug-fs-xs text-violet-400/70 mt-2">
              Refreshes every {currentHours}h
            </p>
          )}
        </div>

        {/* Last built */}
        {graph && (
          <div>
            <p className="aug-fs-xs text-zinc-500 uppercase tracking-wider mb-1.5 font-semibold">
              Last built
            </p>
            <p className="aug-fs-xs text-zinc-400 font-mono">
              {formatTimestamp(graph.generated_at)}
            </p>
          </div>
        )}

        {/* Manual rebuild */}
        <div>
          <p className="aug-fs-xs text-zinc-500 uppercase tracking-wider mb-2 font-semibold">
            Manual rebuild
          </p>
          <button
            onClick={handleRebuild}
            disabled={rebuilding}
            className={cn(
              "w-full py-2 aug-fs-xs rounded-[var(--r3)] border transition",
              rebuilding
                ? "border-zinc-700 text-zinc-500 cursor-not-allowed"
                : "border-violet-500/30 text-violet-400 hover:bg-violet-500/10 hover:border-violet-400/50",
            )}
          >
            {rebuilding ? "Rebuilding…" : "Rebuild ontology now"}
          </button>
          {rebuildMsg && (
            <p className={cn(
              "aug-fs-xs mt-2",
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

// ── Duplicate-entity suggestions drawer (Borrow 5) ────────────────────────────
// Shows embedding-detected near-duplicate entity clusters; the user picks which entity each cluster
// merges INTO (the survivor). The merge is the explicit, gated POST — never automatic.
function DuplicatesDrawer({ connId, schema, onClose, onMerged }: {
  connId: string; schema?: string; onClose: () => void; onMerged: () => void;
}) {
  const [clusters, setClusters] = useState<DuplicateCluster[] | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [merging,  setMerging]  = useState<string | null>(null);
  const [error,    setError]    = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    getDuplicateEntities(connId, schema)
      .then(setClusters)
      .catch(() => setError("Couldn't load duplicate suggestions."))
      .finally(() => setLoading(false));
  }, [connId, schema]);
  useEffect(() => { load(); }, [load]);

  const doMerge = async (cluster: DuplicateCluster, canonicalId: string) => {
    setMerging(canonicalId); setError(null);
    try {
      await mergeOntologyEntities(connId, cluster.entities.map(e => e.id), canonicalId, schema);
      onMerged();   // parent re-fetches the graph
      load();       // refresh suggestions
    } catch (e) {
      setError((e as Error).message || "Merge failed");
    } finally {
      setMerging(null);
    }
  };

  return (
    <div className="w-[340px] shrink-0 border-l border-zinc-700/70 bg-zinc-900/40 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-zinc-700/70">
        <p className="text-xs font-semibold text-zinc-300">Possible duplicate entities</p>
        <button onClick={onClose} className="ml-auto text-zinc-500 hover:text-zinc-300 transition">
          <Icon name="close" size={16} label="Close" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {loading && <p className="aug-fs-xs text-zinc-500">Scanning for duplicates…</p>}
        {error && <p className="aug-fs-xs text-red-400">{error}</p>}
        {!loading && !error && clusters?.length === 0 && (
          <p className="aug-fs-xs text-zinc-500">
            No likely duplicates found. (Detection uses embeddings; if none are configured it returns nothing.)
          </p>
        )}
        {clusters?.map((c, i) => (
          <div key={i} className="rounded border border-violet-500/25 bg-violet-500/[0.04] p-2.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="aug-fs-xs text-violet-300">{countNoun(c.entities.length, "entity", "entities")}</span>
              <span className="aug-fs-xs text-zinc-500">similarity {Math.round(c.similarity * 100)}%</span>
            </div>
            <ul className="space-y-0.5">
              {c.entities.map(e => (
                <li key={e.id} className="aug-fs-xs text-zinc-300">
                  {e.display_name} <span className="text-zinc-500">({e.source_tables.join(", ") || "—"})</span>
                </li>
              ))}
            </ul>
            <div className="flex flex-col gap-1 pt-0.5">
              <span className="aug-fs-xs text-zinc-500">Merge all into:</span>
              <div className="flex flex-wrap gap-1">
                {c.entities.map(e => (
                  <button key={e.id} onClick={() => doMerge(c, e.id)} disabled={merging !== null}
                    className="aug-fs-xs px-2 py-0.5 rounded border border-violet-500/40 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25 transition disabled:opacity-40">
                    {merging === e.id ? "Merging…" : e.display_name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


// ── Learned-skills drawer (R8 Agent-Skills) ───────────────────────────────────
// Lists the skills crystallized from finished investigations (origin='learned'
// QueryTemplates that the planner already reuses via the ontology overlay). A human can
// see each skill's reusable SQL + reuse count, "Use" it (records a use → feeds autonomy),
// or delete it. The connection's EARNED autonomy level is shown at the top.
const _AUTONOMY_TONE = ["text-zinc-400", "text-sky-300", "text-violet-300", "text-emerald-300"];

const _PROPOSAL_KIND: Record<string, { label: string; tone: string }> = {
  metric:      { label: "metric gap",  tone: "text-amber-300 border-amber-500/30 bg-amber-500/10" },
  column_note: { label: "column note", tone: "text-sky-300 border-sky-500/30 bg-sky-500/10" },
  table_note:  { label: "table note",  tone: "text-violet-300 border-violet-500/30 bg-violet-500/10" },
};

/** The review inbox for what the engine and the conversation PROPOSE about this connection's
 *  context — a metric gap the self-improving loop noticed, or a column/table note an agent
 *  staged with evidence (blast-radius rule: a table-level claim always waits here; a column
 *  note waits when confidence was not high or a human note already exists). Nothing changes
 *  the ontology until a person accepts it here. */
function ProposalsDrawer({ connId, schema, onClose }: { connId: string; schema?: string; onClose: () => void }) {
  const [items,   setItems]   = useState<OntologyProposal[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy,    setBusy]    = useState<string | null>(null);
  const [error,   setError]   = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    getOntologyProposals(connId, schema)
      .then(setItems)
      .catch(() => setError("Couldn't load proposals."))
      .finally(() => setLoading(false));
  }, [connId, schema]);
  useEffect(() => { load(); }, [load]);

  const doAccept = async (id: string) => {
    setBusy(id); setError(null);
    try { await acceptOntologyProposal(id, connId, schema); }
    catch (e) { setError((e as Error).message || "Accept failed"); }
    finally { setBusy(null); load(); }
  };
  const doDismiss = async (id: string) => {
    setBusy(id); setError(null);
    try { await dismissOntologyProposal(id, connId, schema); }
    catch (e) { setError((e as Error).message || "Dismiss failed"); }
    finally { setBusy(null); load(); }
  };

  const pending = (items ?? []).filter(p => p.status === "pending");

  return (
    <div className="w-[340px] shrink-0 border-l border-zinc-700/70 bg-zinc-900/40 flex flex-col overflow-hidden" data-testid="ontology-proposals-drawer">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-zinc-700/70">
        <p className="text-xs font-semibold text-zinc-300">Proposals</p>
        {pending.length > 0 && (
          <span className="aug-fs-xs text-zinc-500">{pending.length} awaiting review</span>
        )}
        <Button variant="ghost" size="icon-xs" onClick={onClose} className="ml-auto text-zinc-500 hover:text-zinc-300" aria-label="Close">
          <Icon name="close" size={16} label="Close" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {loading && <p className="aug-fs-xs text-zinc-500">Loading proposals…</p>}
        {error && <p className="aug-fs-xs text-red-400">{error}</p>}
        {!loading && !error && pending.length === 0 && (
          <p className="aug-fs-xs text-zinc-500">
            Nothing awaiting review. Proposals appear here when the engine notices a
            recurring metric gap, or when the conversation stages a note about a column
            or table that needs a person to accept it.
          </p>
        )}
        {pending.map(pr => {
          const kind = _PROPOSAL_KIND[pr.kind] ?? { label: pr.kind, tone: "text-zinc-300 border-zinc-600 bg-zinc-800/50" };
          const note = typeof pr.proposed_fields?.note === "string" ? (pr.proposed_fields.note as string) : "";
          const column = typeof pr.proposed_fields?.column === "string" ? (pr.proposed_fields.column as string) : "";
          const confidence = typeof pr.proposed_fields?.confidence === "string" ? (pr.proposed_fields.confidence as string) : "";
          const lastEvidence = pr.evidence?.length ? pr.evidence[pr.evidence.length - 1] : null;
          const evidenceText = lastEvidence && typeof lastEvidence.evidence === "string" ? (lastEvidence.evidence as string) : "";
          return (
            <div key={pr.id} className="rounded border border-zinc-700/70 bg-zinc-900/60 p-2.5 space-y-1.5" data-testid="ontology-proposal">
              <div className="flex items-center gap-2">
                <span className={cn("aug-fs-xs border rounded-[var(--r-chip)] px-1.5 py-0.5", kind.tone)}>{kind.label}</span>
                <span className="aug-fs-xs font-mono text-zinc-300 truncate" title={pr.target_id}>
                  {pr.entity}{column ? `.${column}` : ""}
                </span>
                {pr.support > 1 && <span className="aug-fs-xs text-zinc-500 ml-auto">seen ×{pr.support}</span>}
              </div>
              {note && <p className="aug-fs-xs text-zinc-200">{note}</p>}
              {!note && pr.reason && <p className="aug-fs-xs text-zinc-300">{pr.reason}</p>}
              {evidenceText && (
                <p className="aug-fs-xs text-zinc-500">
                  <span className="text-zinc-600">evidence · </span>{evidenceText}
                  {confidence && <span className="text-zinc-600"> · confidence {confidence}</span>}
                </p>
              )}
              <div className="flex items-center gap-2 pt-0.5">
                <Button
                  variant="outline" size="xs"
                  onClick={() => doAccept(pr.id)}
                  disabled={busy === pr.id}
                  className="aug-fs-xs border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                  data-testid="ontology-proposal-accept"
                >
                  Accept
                </Button>
                <Button
                  variant="ghost" size="xs"
                  onClick={() => doDismiss(pr.id)}
                  disabled={busy === pr.id}
                  className="aug-fs-xs text-zinc-400 hover:text-zinc-200"
                  data-testid="ontology-proposal-dismiss"
                >
                  Dismiss
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function SkillsDrawer({ connId, schema, onClose }: { connId: string; schema?: string; onClose: () => void }) {
  const [skills,   setSkills]   = useState<QueryTemplate[] | null>(null);
  const [autonomy, setAutonomy] = useState<AutonomyLevel | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [busy,     setBusy]     = useState<string | null>(null);
  const [error,    setError]    = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    Promise.all([getLearnedSkills(connId, schema), getAutonomy(connId)])
      .then(([s, a]) => { setSkills(s); setAutonomy(a); })
      .catch(() => setError("Couldn't load learned skills."))
      .finally(() => setLoading(false));
  }, [connId, schema]);
  useEffect(() => { load(); }, [load]);

  const doUse = async (id: string) => {
    setBusy(id); setError(null);
    try { await activateLearnedSkill(id, connId, schema); }
    catch (e) { setError((e as Error).message || "Use failed"); }
    finally { setBusy(null); load(); }   // always clear busy (else later actions stay disabled)
  };
  const doDelete = async (id: string) => {
    setBusy(id); setError(null);
    try { await deleteLearnedSkill(id, connId, schema); }
    catch (e) { setError((e as Error).message || "Delete failed"); }
    finally { setBusy(null); load(); }
  };

  return (
    <div className="w-[340px] shrink-0 border-l border-zinc-700/70 bg-zinc-900/40 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-zinc-700/70">
        <p className="text-xs font-semibold text-zinc-300">Learned skills</p>
        <button onClick={onClose} className="ml-auto text-zinc-500 hover:text-zinc-300 transition">
          <Icon name="close" size={16} label="Close" />
        </button>
      </div>
      {autonomy && (
        <div className="px-3 py-2 border-b border-zinc-800/70 aug-fs-xs text-zinc-500">
          autonomy{" "}
          <span className={cn("font-medium", _AUTONOMY_TONE[autonomy.level] ?? "text-zinc-400")}>
            L{autonomy.level} · {autonomy.label}
          </span>
          {autonomy.reason && <span className="text-zinc-600"> — {autonomy.reason}</span>}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {loading && <p className="aug-fs-xs text-zinc-500">Loading skills…</p>}
        {error && <p className="aug-fs-xs text-red-400">{error}</p>}
        {!loading && !error && skills?.length === 0 && (
          <p className="aug-fs-xs text-zinc-500">
            No learned skills yet. A skill is crystallized from a finished deep analysis
            (its grounded, read-only query) — run a deep analysis, then “Save as skill”.
          </p>
        )}
        {skills?.map(sk => (
          <div key={sk.id} className="rounded border border-violet-500/25 bg-violet-500/[0.04] p-2.5 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="aug-fs-xs text-violet-200 truncate" title={sk.display_name}>{sk.display_name}</span>
              <span className="aug-fs-xs text-zinc-500 shrink-0">{sk.action_type} · used {sk.usage_count ?? 0}×</span>
            </div>
            {sk.description && <p className="aug-fs-xs text-zinc-500 line-clamp-2">{sk.description}</p>}
            <pre className="aug-fs-xs text-zinc-400 bg-zinc-900/60 rounded p-1.5 overflow-x-auto whitespace-pre-wrap break-words max-h-24">{sk.sql_template}</pre>
            {sk.parameters?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {sk.parameters.map(p => (
                  <span key={p.name} className="aug-fs-xs px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">{`{${p.name}}`}</span>
                ))}
              </div>
            )}
            <div className="flex gap-1 pt-0.5">
              <button onClick={() => doUse(sk.id)} disabled={busy !== null}
                className="aug-fs-xs px-2 py-0.5 rounded border border-violet-500/40 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25 transition disabled:opacity-40">
                {busy === sk.id ? "…" : "Use"}
              </button>
              <button onClick={() => doDelete(sk.id)} disabled={busy !== null}
                className="aug-fs-xs px-2 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:text-red-300 hover:border-red-500/40 transition disabled:opacity-40">
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


export function OntologyPanel({ connectionId, onInvestigate, schema }: Props) {
  const [graph,             setGraph]            = useState<OntologyGraph | null>(null);
  const [loading,           setLoading]          = useState(false);
  const [error,             setError]            = useState<string | null>(null);
  const [selectedConnId,    setSelectedConnId]   = useState(connectionId);
  const [showSettings,      setShowSettings]     = useState(false);
  const [showDuplicates,    setShowDuplicates]   = useState(false);
  const [showSkills,        setShowSkills]        = useState(false);
  const [showProposals,     setShowProposals]     = useState(false);
  // PX-6 — the human-edit ledger: overrides list/revert, routing proposals, export/import.
  const [showOverrides,     setShowOverrides]     = useState(false);
  const [orgMode,           setOrgMode]          = useState(false);
  // ON-3b — the entity-type map IS this layer (re-laid 2026-09-12, the user: "we need only map in ontology..
  // overview doesnt matter if it is not being used as context.. remove it in that case"). The whole-graph ERD it
  // used to sit beside was a second drawing of the same facts that nothing downstream read; the Org board keeps
  // its own canvas.
  /** Which schemas DO have an ontology, per the 404. Drives the empty state's offer. */
  const [builtSchemas,      setBuiltSchemas]      = useState<string[]>([]);

  useEffect(() => { setSelectedConnId(connectionId); }, [connectionId]);

  useEffect(() => {
    if (!selectedConnId) return;
    setLoading(true);
    setError(null);
    setGraph(null);
    setShowSettings(false);
    setShowDuplicates(false);
    getOntology(selectedConnId, schema)
      .then(setGraph)
      .catch((e: unknown) => {
        // The server says WHICH schemas are built. It used to say "it builds
        // automatically on the next query", which stopped being true when the read
        // path stopped building — a sentence that tells the user to wait for
        // something that will never happen is worse than no sentence.
        const built = e instanceof OntologyNotBuilt ? e.builtSchemas : [];
        setBuiltSchemas(built);
        setError(e instanceof Error && e.message
          ? e.message
          : "No ontology has been built for this connection yet.");
      })
      .finally(() => setLoading(false));
  }, [selectedConnId, schema]);


  // ── Header bar ──────────────────────────────────────────────────────────────
  const headerBar = (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-700/70 shrink-0 bg-zinc-900/40">
      <p className="text-xs font-semibold text-zinc-300">Business Ontology</p>

      {/* The scope, stated. Everything on this screen — entities, relationships,
          duplicates, proposals, skills, and every edit made here — belongs to this
          schema and no other. It used to be possible to be looking at a neighbour's
          graph with nothing on screen saying so. */}
      {!orgMode && schema && (
        <span
          className="aug-fs-xs text-zinc-400 border border-zinc-700 rounded-[var(--r-chip)] px-2 py-0.5 font-code"
          title="This ontology is scoped to one schema. Switch schemas with the workspace scope picker above."
          data-testid="ontology-schema-scope"
        >
          {schema}
        </span>
      )}

      {/* Org ⟷ Connection view toggle */}
      <div className="flex shrink-0 items-center rounded-md border border-zinc-700 overflow-hidden aug-fs-xs">
        <button
          onClick={() => setOrgMode(true)}
          className={cn(
            "px-2.5 py-1 transition",
            orgMode ? "bg-violet-500/15 text-violet-300" : "text-zinc-400 hover:text-zinc-200",
          )}
        >Org</button>
        <button
          onClick={() => setOrgMode(false)}
          className={cn(
            "px-2.5 py-1 transition border-l border-zinc-700",
            !orgMode ? "bg-violet-500/15 text-violet-300" : "text-zinc-400 hover:text-zinc-200",
          )}
        >Connection</button>
      </div>

      {!orgMode && graph && (
        <div className="flex items-center gap-2 ml-auto">
          {graph.enriched ? (
            <span className="aug-fs-xs text-emerald-400 border border-emerald-500/20 bg-emerald-500/8 rounded-[var(--r-chip)] px-2 py-0.5">
              semantically enriched
            </span>
          ) : (
            <span className="aug-fs-xs text-zinc-500 border border-zinc-700 rounded-[var(--r-chip)] px-2 py-0.5">
              structural only
            </span>
          )}
          <span className="aug-fs-xs text-zinc-500">
            {countNoun(Object.keys(graph.entities).length, "entity", "entities")}
            {" · "}{countNoun(Object.keys(graph.relationships).length, "relationship")}
          </span>
          <button
            onClick={() => { setShowDuplicates(v => !v); setShowSettings(false); setShowSkills(false); setShowProposals(false); }}
            className={cn(
              "aug-fs-xs px-2 py-0.5 rounded border transition",
              showDuplicates
                ? "border-violet-500/40 bg-violet-500/15 text-violet-300"
                : "border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500",
            )}
            title="Find near-duplicate entities to merge"
          >
            Find duplicates
          </button>
          <Button
            variant="outline" size="xs"
            onClick={() => { setShowOverrides(v => !v); setShowSettings(false); setShowDuplicates(false); setShowSkills(false); setShowProposals(false); }}
            className={cn(
              "aug-fs-xs",
              showOverrides
                ? "border-violet-500/40 bg-violet-500/15 text-violet-300"
                : "border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500",
            )}
            title="Human overrides on this scope — list them, revert them; routing proposals; export/import"
            data-testid="ontology-overrides-toggle"
          >
            Human edits
          </Button>
          <Button
            variant="outline" size="xs"
            onClick={() => { setShowProposals(v => !v); setShowSettings(false); setShowDuplicates(false); setShowSkills(false); setShowOverrides(false); }}
            className={cn(
              "aug-fs-xs",
              showProposals
                ? "border-violet-500/40 bg-violet-500/15 text-violet-300"
                : "border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500",
            )}
            title="Proposed context awaiting your review — metric gaps and notes the conversation staged"
            data-testid="ontology-proposals-toggle"
          >
            Proposals
          </Button>
          <button
            onClick={() => { setShowSkills(v => !v); setShowSettings(false); setShowDuplicates(false); setShowProposals(false); }}
            className={cn(
              "aug-fs-xs px-2 py-0.5 rounded border transition",
              showSkills
                ? "border-violet-500/40 bg-violet-500/15 text-violet-300"
                : "border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500",
            )}
            title="Learned skills crystallized from deep analyses"
          >
            Learned skills
          </button>
          <button
            onClick={() => { setShowSettings(v => !v); setShowDuplicates(false); setShowSkills(false); setShowProposals(false); }}
            className={cn(
              "text-zinc-500 hover:text-zinc-300 transition ml-1",
              showSettings && "text-violet-400",
            )}
            title="Ontology settings"
          >
            <Icon name="settings" size={16} label="Settings" />
          </button>
        </div>
      )}
    </div>
  );

  // ── Org-level board — bypasses the single-graph loading/error gates ──────────
  if (orgMode) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        {headerBar}
        <div className="flex-1 relative overflow-hidden">
          <OntologyOrgCanvas
            onOpenConnection={(connId) => { setSelectedConnId(connId); setOrgMode(false); }}
          />
        </div>
      </div>
    );
  }

  // ── Loading / error states ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        {headerBar}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3">
            <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-[var(--r-pill)] animate-spin mx-auto" />
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
        {/* The settings drawer lives here too, not only on the populated screen: the
            build door this state offers is IN it, and a door that opens nothing is
            the failure mode this codebase keeps re-learning. */}
        {showSettings && (
          <div className="flex-1 flex overflow-hidden">
            <div className="flex-1" />
            <OntologySettings
              connectionId={selectedConnId}
              schema={schema}
              graph={null}
              onClose={() => setShowSettings(false)}
              onRebuilt={(g) => { setGraph(g); setError(null); setShowSettings(false); }}
            />
          </div>
        )}
        <div className={showSettings ? "hidden" : "flex-1 flex items-center justify-center p-8"}>
          <div className="text-center space-y-3 max-w-sm">
            <div className="w-10 h-10 rounded-[var(--r-pill)] bg-zinc-800 text-zinc-400 flex items-center justify-center mx-auto">
              <Icon name="node" size={24} />
            </div>
            <p className="text-sm text-zinc-400">
              {error ?? "No ontology data available."}
            </p>
            {/* PX rule — the empty state names the door rather than describing the
                absence. Two doors, because there are two reasons to be here: the
                ontology exists under ANOTHER schema (switch the scope picker above),
                or it exists nowhere (build it). The read path no longer builds on
                demand, so without these the screen is a dead end. */}
            {builtSchemas.length > 0 && (
              <p className="aug-fs-xs text-zinc-500">
                Built for{" "}
                <span className="font-code text-zinc-300">{builtSchemas.join(", ")}</span>
                {" — switch the schema scope above to see one of those."}
              </p>
            )}
            {selectedConnId && (
              <Button
                variant="outline" size="xs"
                onClick={() => { setShowSettings(true); setError(null); }}
                className="aug-fs-xs border-zinc-700 text-zinc-300"
                data-testid="ontology-build-door"
              >
                {schema ? `Build the ontology for ${schema}` : "Build the ontology"}
              </Button>
            )}
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
        {/* ON-3b — the entity-type map brings its own rail and entity-type panel. */}
        <EntityTypeMap connectionId={selectedConnId} schema={schema} />

        {/* Settings panel */}
        {showSettings && (
          <OntologySettings
            connectionId={selectedConnId}
            schema={schema}
            graph={graph}
            onClose={() => setShowSettings(false)}
            onRebuilt={(g) => setGraph(g)}
          />
        )}

        {/* Duplicate-entity suggestions */}
        {showDuplicates && (
          <DuplicatesDrawer
            connId={selectedConnId}
            schema={schema}
            onClose={() => setShowDuplicates(false)}
            onMerged={() => { getOntology(selectedConnId, schema).then(setGraph).catch(() => {}); }}
          />
        )}

        {/* Learned skills (agent procedural memory) */}
        {showSkills && (
          <SkillsDrawer connId={selectedConnId} schema={schema} onClose={() => setShowSkills(false)} />
        )}
        {showProposals && (
          <ProposalsDrawer connId={selectedConnId} schema={schema} onClose={() => setShowProposals(false)} />
        )}
        {showOverrides && (
          <OverridesDrawer connId={selectedConnId} schema={schema}
            onClose={() => setShowOverrides(false)}
            onChanged={() => { getOntology(selectedConnId, schema).then(setGraph).catch(() => {}); }} />
        )}
      </div>
    </div>
  );
}
