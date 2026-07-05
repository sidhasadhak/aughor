"use client";

import { useEffect, useState } from "react";

import { API_BASE as BASE } from "@/lib/config";
import { pct, formatTimestamp } from "@/lib/format";
import { getPlaybookVersions, type PlaybookVersion } from "@/lib/api";

interface PlaybookEntry {
  id: string;
  source_kb_id: string | null;
  trigger_metric: string;
  trigger_condition: string;
  trigger_operator: string;
  trigger_value: number;
  recommendation: string;
  expected_impact: string;
  typical_timeline: string;
  owner_role: string;
  tags: string[];
  evidence_sources: string[];
  historical_success_rate: number;
  status: "active" | "draft" | "deprecated";
  version?: number;
  receipt?: string;
  updated_at?: string;
}

const STATUS_CHIP: Record<string, { bg: string; color: string; label: string }> = {
  active:     { bg: "var(--grn1)", color: "var(--grn4)", label: "active" },
  draft:      { bg: "var(--bg-1)", color: "var(--t3)", label: "draft" },
  deprecated: { bg: "var(--red1)", color: "var(--red4)", label: "deprecated" },
};

function fmtRate(r: number): string {
  if (r <= 0) return "—";
  return pct(r, 0);
}

function StatusChip({ status }: { status: string }) {
  const s = STATUS_CHIP[status] ?? STATUS_CHIP.draft;
  return (
    <span className="text-[9.5px] font-mono px-1.5 py-0.5 rounded-[3px]"
      style={{ background: s.bg, color: s.color, border: `0.5px solid color-mix(in srgb, ${s.color} 25%, transparent)` }}>
      {s.label}
    </span>
  );
}

export function PlaybookPanel() {
  const [entries, setEntries] = useState<PlaybookEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [seeding, setSeeding] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/playbook`);
      if (res.ok) setEntries(await res.json());
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const selectedEntry = entries.find(e => e.id === selected) ?? null;

  const handleStatusChange = async (id: string, status: string) => {
    const entry = entries.find(e => e.id === id);
    if (!entry) return;
    const updated = { ...entry, status };
    try {
      const res = await fetch(`${BASE}/playbook/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
      if (res.ok) {
        const data = await res.json();
        setEntries(prev => prev.map(e => e.id === id ? data : e));
      }
    } catch {}
  };

  const handleReseed = async () => {
    setSeeding(true);
    try {
      const res = await fetch(`${BASE}/playbook/seed`, { method: "POST" });
      if (res.ok) { await load(); }
    } catch {}
    finally { setSeeding(false); }
  };

  const q = filter.toLowerCase().trim();
  const filtered = entries.filter(e => {
    const matchStatus = statusFilter === "all" || e.status === statusFilter;
    const matchQ = !q
      || e.trigger_metric.toLowerCase().includes(q)
      || e.recommendation.toLowerCase().includes(q)
      || e.trigger_condition.toLowerCase().includes(q)
      || e.tags.some(t => t.toLowerCase().includes(q));
    return matchStatus && matchQ;
  });

  const activeCount  = entries.filter(e => e.status === "active").length;
  const draftCount   = entries.filter(e => e.status === "draft").length;
  const provenCount  = entries.filter(e => e.historical_success_rate > 0).length;

  return (
    <div className="flex h-full gap-0" style={{ background: "var(--bg-0)" }}>

      {/* ── Left list ── */}
      <div className="flex flex-col border-r" style={{ width: "340px", flexShrink: 0, borderColor: "var(--b2)" }}>

        {/* Header */}
        <div className="px-4 pt-4 pb-3 shrink-0" style={{ borderBottom: "0.5px solid var(--b2)" }}>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-[13.5px] font-medium" style={{ color: "var(--t1)" }}>Playbook</h2>
            <button
              onClick={handleReseed}
              disabled={seeding}
              className="aug-fs-xs px-2 py-1 rounded-[4px] transition-all"
              style={{ border: "0.5px solid var(--b2)", background: "var(--bg-1)", color: "var(--t3)" }}
              onMouseEnter={e => e.currentTarget.style.color = "var(--t2)"}
              onMouseLeave={e => e.currentTarget.style.color = "var(--t3)"}
            >
              {seeding ? "Seeding…" : "Re-seed from KB"}
            </button>
          </div>
          <div className="flex items-center gap-3 aug-fs-xs font-mono mb-3" style={{ color: "var(--t4)" }}>
            <span><span style={{ color: "var(--grn4)" }}>{activeCount}</span> active</span>
            <span><span style={{ color: "var(--t3)" }}>{draftCount}</span> draft</span>
            {provenCount > 0 && <span><span style={{ color: "var(--blue4)" }}>{provenCount}</span> proven</span>}
          </div>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Search recommendations…"
            className="w-full aug-fs-xs rounded-md px-2.5 py-1.5 focus:outline-none mb-2"
            style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t3)" }}
          />
          <div className="flex gap-1">
            {(["all", "active", "draft", "deprecated"] as const).map(s => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className="text-[9.5px] px-2 py-0.5 rounded-[var(--r-pill)] font-mono transition-all"
                style={{
                  background: statusFilter === s ? "var(--blue1)" : "transparent",
                  border: `0.5px solid ${statusFilter === s ? "#3d6bff55" : "var(--b2)"}`,
                  color: statusFilter === s ? "var(--blue4)" : "var(--t4)",
                }}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto min-h-0 py-2">
          {loading && (
            <div className="space-y-1.5 px-3">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="h-14 rounded-[var(--r3)] animate-pulse" style={{ background: "var(--bg-1)" }} />
              ))}
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <p className="aug-fs-xs text-center py-8" style={{ color: "var(--t4)" }}>
              {entries.length === 0 ? "No playbook entries yet. Click \"Re-seed from KB\" to generate." : "No entries match."}
            </p>
          )}
          {filtered.map(e => (
            <button
              key={e.id}
              onClick={() => setSelected(selected === e.id ? null : e.id)}
              className="w-full text-left px-4 py-2.5 transition-colors"
              style={{
                background: selected === e.id ? "var(--bg-1)" : "transparent",
                borderLeft: selected === e.id ? "2px solid #3d6bff" : "2px solid transparent",
              }}
              onMouseEnter={ev => { if (selected !== e.id) ev.currentTarget.style.background = "var(--bg-2)"; }}
              onMouseLeave={ev => { if (selected !== e.id) ev.currentTarget.style.background = "transparent"; }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="aug-fs-xs font-mono truncate" style={{ color: "var(--t3)" }}>{e.trigger_metric}</p>
                  <p className="aug-fs-sm mt-0.5 leading-snug" style={{ color: "var(--t1)" }}
                    title={e.recommendation}>
                    {e.recommendation.length > 80 ? e.recommendation.slice(0, 78) + "…" : e.recommendation}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0 mt-0.5">
                  <StatusChip status={e.status} />
                  {e.historical_success_rate > 0 && (
                    <span className="aug-fs-xs font-mono" style={{ color: "var(--blue3)" }}>
                      {fmtRate(e.historical_success_rate)}
                    </span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ── Right detail ── */}
      <div className="flex-1 overflow-y-auto min-h-0 p-6">
        {!selectedEntry ? (
          <div className="h-full flex items-center justify-center">
            <p className="aug-fs-sm" style={{ color: "var(--t4)" }}>Select an entry to view and edit</p>
          </div>
        ) : (
          <PlaybookDetail
            entry={selectedEntry}
            onStatusChange={(s) => handleStatusChange(selectedEntry.id, s)}
          />
        )}
      </div>
    </div>
  );
}

function PlaybookDetail({
  entry,
  onStatusChange,
}: {
  entry: PlaybookEntry;
  onStatusChange: (status: string) => void;
}) {
  return (
    <div className="max-w-2xl space-y-5">
      {/* Metric + condition */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="aug-fs-xs font-mono px-2 py-0.5 rounded-[3px]"
            style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t3)" }}>
            {entry.trigger_metric}
          </span>
          <StatusChip status={entry.status} />
          {entry.source_kb_id && (
            <span className="text-[9.5px] font-mono" style={{ color: "var(--t4)" }}>
              from KB: {entry.source_kb_id}
            </span>
          )}
        </div>
        <p className="text-[11.5px] italic" style={{ color: "var(--t3)" }}>{entry.trigger_condition}</p>
      </div>

      {/* Recommendation */}
      <div>
        <p className="aug-fs-xs uppercase tracking-wider mb-1.5" style={{ color: "var(--t4)" }}>Recommendation</p>
        <p className="aug-fs-ui leading-relaxed" style={{ color: "var(--t1)" }}>{entry.recommendation}</p>
      </div>

      {/* Impact + timeline + owner */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Expected impact", value: entry.expected_impact },
          { label: "Timeline",        value: entry.typical_timeline },
          { label: "Owner",           value: entry.owner_role },
        ].map(({ label, value }) => value ? (
          <div key={label}>
            <p className="aug-fs-xs uppercase tracking-wider mb-1" style={{ color: "var(--t4)" }}>{label}</p>
            <p className="aug-fs-sm" style={{ color: "var(--t2)" }}>{value}</p>
          </div>
        ) : null)}
      </div>

      {/* Success rate */}
      <div className="flex items-center gap-4">
        <div>
          <p className="aug-fs-xs uppercase tracking-wider mb-1" style={{ color: "var(--t4)" }}>Historical success rate</p>
          <p className="aug-fs-h1 font-semibold font-mono"
            style={{ color: entry.historical_success_rate > 0 ? "var(--grn4)" : "var(--t4)" }}>
            {entry.historical_success_rate > 0 ? fmtRate(entry.historical_success_rate) : "No data yet"}
          </p>
          {entry.evidence_sources.length > 0 && (
            <p className="aug-fs-xs mt-0.5" style={{ color: "var(--t4)" }}>
              {entry.evidence_sources.length} investigation{entry.evidence_sources.length > 1 ? "s" : ""} as evidence
            </p>
          )}
        </div>
      </div>

      {/* Tags */}
      {entry.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {entry.tags.map(t => (
            <span key={t} className="aug-fs-xs px-2 py-0.5 rounded-[var(--r-pill)] font-mono"
              style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t4)" }}>
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Version history (Governed Dives — immutable, receipt-pinned versions) */}
      <VersionHistory entryId={entry.id} currentVersion={entry.version} />

      {/* Promote / deprecate */}
      <div className="flex gap-2 pt-2" style={{ borderTop: "0.5px solid var(--b2)" }}>
        {entry.status !== "active" && (
          <button
            onClick={() => onStatusChange("active")}
            className="aug-fs-xs px-3 py-1.5 rounded-[5px] transition-all"
            style={{ background: "var(--grn1)", border: "0.5px solid var(--grn2)", color: "var(--grn4)" }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "var(--grn4)"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "var(--grn2)"}
          >
            Promote to active
          </button>
        )}
        {entry.status !== "deprecated" && (
          <button
            onClick={() => onStatusChange("deprecated")}
            className="aug-fs-xs px-3 py-1.5 rounded-[5px] transition-all"
            style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t3)" }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--red4)"; e.currentTarget.style.color = "var(--red4)"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.color = "var(--t3)"; }}
          >
            Deprecate
          </button>
        )}
        {entry.status === "deprecated" && (
          <button
            onClick={() => onStatusChange("draft")}
            className="aug-fs-xs px-3 py-1.5 rounded-[5px] transition-all"
            style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t3)" }}
          >
            Restore to draft
          </button>
        )}
      </div>
    </div>
  );
}

function VersionHistory({ entryId, currentVersion }: { entryId: string; currentVersion?: number }) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<PlaybookVersion[] | null>(null);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && versions === null) getPlaybookVersions(entryId).then(setVersions).catch(() => setVersions([]));
  };

  return (
    <div style={{ borderTop: "0.5px solid var(--b1)", paddingTop: 12 }}>
      <button onClick={toggle} className="flex items-center gap-2 aug-fs-xs" style={{ color: "var(--t3)" }}>
        <span style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .12s" }}>▸</span>
        Version history
        {currentVersion != null && (
          <span className="aug-fs-xs px-1.5 py-0.5 rounded-[3px] font-mono"
            style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t4)" }}>v{currentVersion}</span>
        )}
      </button>
      {open && (
        <div className="mt-2 space-y-1.5">
          {versions === null && <p className="aug-fs-xs" style={{ color: "var(--t4)" }}>Loading…</p>}
          {versions?.length === 0 && <p className="aug-fs-xs" style={{ color: "var(--t4)" }}>No frozen versions yet.</p>}
          {versions?.slice().reverse().map(v => (
            <div key={v.version} className="flex items-center gap-3 aug-fs-xs" style={{ color: "var(--t3)" }}>
              <span className="font-mono px-1.5 py-0.5 rounded-[3px]"
                style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t2)" }}>v{v.version}</span>
              <span style={{ color: "var(--t4)" }}>{v.saved_at ? formatTimestamp(v.saved_at) : ""}</span>
              <span className="font-mono truncate" style={{ color: "var(--t4)" }} title={v.receipt}>{v.receipt ? v.receipt.slice(0, 16) + "…" : ""}</span>
            </div>
          ))}
          <p className="aug-fs-xs mt-1" style={{ color: "var(--t4)" }}>
            Immutable, receipt-pinned versions — a finding that cited an older version resolves against the exact content it relied on.
          </p>
        </div>
      )}
    </div>
  );
}
