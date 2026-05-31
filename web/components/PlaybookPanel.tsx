"use client";

import { useEffect, useState } from "react";

import { API_BASE as BASE } from "@/lib/config";

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
}

const STATUS_CHIP: Record<string, { bg: string; color: string; label: string }> = {
  active:     { bg: "#0a1a10", color: "#4ade80", label: "active" },
  draft:      { bg: "#13141a", color: "#5a5b62", label: "draft" },
  deprecated: { bg: "#1a0a0a", color: "#f87171", label: "deprecated" },
};

function fmtRate(r: number): string {
  if (r <= 0) return "—";
  return `${(r * 100).toFixed(0)}%`;
}

function StatusChip({ status }: { status: string }) {
  const s = STATUS_CHIP[status] ?? STATUS_CHIP.draft;
  return (
    <span className="text-[9.5px] font-mono px-1.5 py-0.5 rounded-[3px]"
      style={{ background: s.bg, color: s.color, border: `0.5px solid ${s.color}33` }}>
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
    <div className="flex h-full gap-0" style={{ background: "#11171d" }}>

      {/* ── Left list ── */}
      <div className="flex flex-col border-r" style={{ width: "340px", flexShrink: 0, borderColor: "#1e1f24" }}>

        {/* Header */}
        <div className="px-4 pt-4 pb-3 shrink-0" style={{ borderBottom: "0.5px solid #1e1f24" }}>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-[13.5px] font-medium" style={{ color: "#e8e6e1" }}>Playbook</h2>
            <button
              onClick={handleReseed}
              disabled={seeding}
              className="text-[11px] px-2 py-1 rounded-[4px] transition-all"
              style={{ border: "0.5px solid #2a2b30", background: "#13141a", color: "#5a5b62" }}
              onMouseEnter={e => e.currentTarget.style.color = "#9a9ba4"}
              onMouseLeave={e => e.currentTarget.style.color = "#5a5b62"}
            >
              {seeding ? "Seeding…" : "Re-seed from KB"}
            </button>
          </div>
          <div className="flex items-center gap-3 text-[11px] font-mono mb-3" style={{ color: "var(--t4)" }}>
            <span><span style={{ color: "#4ade80" }}>{activeCount}</span> active</span>
            <span><span style={{ color: "#5a5b62" }}>{draftCount}</span> draft</span>
            {provenCount > 0 && <span><span style={{ color: "#7ba8f7" }}>{provenCount}</span> proven</span>}
          </div>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Search recommendations…"
            className="w-full text-[11px] rounded-md px-2.5 py-1.5 focus:outline-none mb-2"
            style={{ background: "#13141a", border: "0.5px solid #1e1f24", color: "#6e6f78" }}
          />
          <div className="flex gap-1">
            {(["all", "active", "draft", "deprecated"] as const).map(s => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className="text-[9.5px] px-2 py-0.5 rounded-full font-mono transition-all"
                style={{
                  background: statusFilter === s ? "#1e2040" : "transparent",
                  border: `0.5px solid ${statusFilter === s ? "#3d6bff55" : "#2a2b30"}`,
                  color: statusFilter === s ? "#7ba8f7" : "var(--t4)",
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
                <div key={i} className="h-14 rounded-lg animate-pulse" style={{ background: "#13141a" }} />
              ))}
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <p className="text-[11px] text-center py-8" style={{ color: "var(--t4)" }}>
              {entries.length === 0 ? "No playbook entries yet. Click \"Re-seed from KB\" to generate." : "No entries match."}
            </p>
          )}
          {filtered.map(e => (
            <button
              key={e.id}
              onClick={() => setSelected(selected === e.id ? null : e.id)}
              className="w-full text-left px-4 py-2.5 transition-colors"
              style={{
                background: selected === e.id ? "#13141a" : "transparent",
                borderLeft: selected === e.id ? "2px solid #3d6bff" : "2px solid transparent",
              }}
              onMouseEnter={ev => { if (selected !== e.id) ev.currentTarget.style.background = "#0f1014"; }}
              onMouseLeave={ev => { if (selected !== e.id) ev.currentTarget.style.background = "transparent"; }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[11px] font-mono truncate" style={{ color: "#5a5b62" }}>{e.trigger_metric}</p>
                  <p className="text-[12px] mt-0.5 leading-snug" style={{ color: "#c8c7c3" }}
                    title={e.recommendation}>
                    {e.recommendation.length > 80 ? e.recommendation.slice(0, 78) + "…" : e.recommendation}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0 mt-0.5">
                  <StatusChip status={e.status} />
                  {e.historical_success_rate > 0 && (
                    <span className="text-[11px] font-mono" style={{ color: "var(--blue3)" }}>
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
            <p className="text-[12px]" style={{ color: "var(--t4)" }}>Select an entry to view and edit</p>
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
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-[3px]"
            style={{ background: "#13141a", border: "0.5px solid #2a2b30", color: "#5a5b62" }}>
            {entry.trigger_metric}
          </span>
          <StatusChip status={entry.status} />
          {entry.source_kb_id && (
            <span className="text-[9.5px] font-mono" style={{ color: "var(--b0)" }}>
              from KB: {entry.source_kb_id}
            </span>
          )}
        </div>
        <p className="text-[11.5px] italic" style={{ color: "#5a5b62" }}>{entry.trigger_condition}</p>
      </div>

      {/* Recommendation */}
      <div>
        <p className="text-[11px] uppercase tracking-wider mb-1.5" style={{ color: "var(--t4)" }}>Recommendation</p>
        <p className="text-[13px] leading-relaxed" style={{ color: "#e8e6e1" }}>{entry.recommendation}</p>
      </div>

      {/* Impact + timeline + owner */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Expected impact", value: entry.expected_impact },
          { label: "Timeline",        value: entry.typical_timeline },
          { label: "Owner",           value: entry.owner_role },
        ].map(({ label, value }) => value ? (
          <div key={label}>
            <p className="text-[11px] uppercase tracking-wider mb-1" style={{ color: "var(--t4)" }}>{label}</p>
            <p className="text-[12px]" style={{ color: "#9a9ba4" }}>{value}</p>
          </div>
        ) : null)}
      </div>

      {/* Success rate */}
      <div className="flex items-center gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-wider mb-1" style={{ color: "var(--t4)" }}>Historical success rate</p>
          <p className="text-[18px] font-semibold font-mono"
            style={{ color: entry.historical_success_rate > 0 ? "#4ade80" : "var(--t4)" }}>
            {entry.historical_success_rate > 0 ? fmtRate(entry.historical_success_rate) : "No data yet"}
          </p>
          {entry.evidence_sources.length > 0 && (
            <p className="text-[11px] mt-0.5" style={{ color: "var(--t4)" }}>
              {entry.evidence_sources.length} investigation{entry.evidence_sources.length > 1 ? "s" : ""} as evidence
            </p>
          )}
        </div>
      </div>

      {/* Tags */}
      {entry.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {entry.tags.map(t => (
            <span key={t} className="text-[11px] px-2 py-0.5 rounded-full font-mono"
              style={{ background: "#13141a", border: "0.5px solid #2a2b30", color: "var(--t4)" }}>
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Promote / deprecate */}
      <div className="flex gap-2 pt-2" style={{ borderTop: "0.5px solid #1e1f24" }}>
        {entry.status !== "active" && (
          <button
            onClick={() => onStatusChange("active")}
            className="text-[11px] px-3 py-1.5 rounded-[5px] transition-all"
            style={{ background: "#0a1a10", border: "0.5px solid #1a3a20", color: "#4ade80" }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "#4ade80"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "#1a3a20"}
          >
            Promote to active
          </button>
        )}
        {entry.status !== "deprecated" && (
          <button
            onClick={() => onStatusChange("deprecated")}
            className="text-[11px] px-3 py-1.5 rounded-[5px] transition-all"
            style={{ background: "#13141a", border: "0.5px solid #2a2b30", color: "#5a5b62" }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "#f87171"; e.currentTarget.style.color = "#f87171"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = "#2a2b30"; e.currentTarget.style.color = "#5a5b62"; }}
          >
            Deprecate
          </button>
        )}
        {entry.status === "deprecated" && (
          <button
            onClick={() => onStatusChange("draft")}
            className="text-[11px] px-3 py-1.5 rounded-[5px] transition-all"
            style={{ background: "#13141a", border: "0.5px solid #2a2b30", color: "#5a5b62" }}
          >
            Restore to draft
          </button>
        )}
      </div>
    </div>
  );
}
