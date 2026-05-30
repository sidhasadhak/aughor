"use client";

import { useEffect, useState } from "react";
import { createCanvas, getSchemaRich, type Connection, type Canvas } from "@/lib/api";

// ── Icon helper ───────────────────────────────────────────────────────────────

function Icon({ d, size = 14, color = "currentColor" }: { d: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0 }}>
      <path d={d} />
    </svg>
  );
}

const CLOSE_ICON  = "M18 6L6 18M6 6l12 12";
const CHECK_ICON  = "M20 6L9 17l-5-5";
const CHEVR_ICON  = "M9 6l6 6-6 6";
const CHEVL_ICON  = "M15 6l-6 6 6 6";
const DB_ICON     = "M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2zm6 12c0 .5-2.13 2-6 2s-6-1.5-6-2v-2.23C7.61 15.51 9.72 16 12 16s4.39-.49 6-1.23V16zm0-5c0 .5-2.13 2-6 2s-6-1.5-6-2V8.77C7.61 10.51 9.72 11 12 11s4.39-.49 6-1.23V11z";
const TABLE_ICON  = "M4 6h16M4 10h16M4 14h16M4 18h16";
const SEARCH_ICON = "M11 19a8 8 0 100-16 8 8 0 000 16zm10 2l-4.35-4.35";

// ── Step indicator ────────────────────────────────────────────────────────────

function StepDot({ n, active, done }: { n: number; active: boolean; done: boolean }) {
  return (
    <div style={{
      width: 24, height: 24, borderRadius: "50%",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 11, fontWeight: 600,
      background: done ? "var(--blue4)" : active ? "color-mix(in srgb, var(--blue4) 20%, transparent)" : "var(--bg-3)",
      border: `1.5px solid ${done || active ? "var(--blue4)" : "var(--b2)"}`,
      color: done ? "var(--bg-0)" : active ? "var(--blue4)" : "var(--t4)",
      transition: "all .15s",
      flexShrink: 0,
    }}>
      {done ? <Icon d={CHECK_ICON} size={11} color="var(--bg-0)" /> : n}
    </div>
  );
}

// ── CanvasCreator ─────────────────────────────────────────────────────────────

interface Props {
  connections: Connection[];
  onCreated: (canvas: Canvas) => void;
  onCancel: () => void;
}

export function CanvasCreator({ connections, onCreated, onCancel }: Props) {
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Step 1 — name + description
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  // Step 2 — connection
  const [connId, setConnId] = useState(connections[0]?.id ?? "");

  // Step 3 — tables
  const [allTables, setAllTables] = useState<string[]>([]);
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());
  const [tableSearch, setTableSearch] = useState("");
  const [loadingTables, setLoadingTables] = useState(false);
  const [useAllTables, setUseAllTables] = useState(true);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Load table list when entering step 3
  useEffect(() => {
    if (step !== 3 || !connId) return;
    setLoadingTables(true);
    setAllTables([]);
    getSchemaRich(connId)
      .then(s => setAllTables(s.tables.map(t => t.name)))
      .catch(() => setAllTables([]))
      .finally(() => setLoadingTables(false));
  }, [step, connId]);

  const filteredTables = allTables.filter(t =>
    t.toLowerCase().includes(tableSearch.toLowerCase()),
  );

  const toggleTable = (t: string) => {
    setSelectedTables(prev => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  const handleCreate = async () => {
    setError("");
    setSaving(true);
    try {
      const tables = useAllTables ? [] : [...selectedTables];
      const canvas = await createCanvas(name.trim(), description.trim(), [
        { connection_id: connId, schema_name: null, tables },
      ]);
      onCreated(canvas);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create canvas");
    } finally {
      setSaving(false);
    }
  };

  const selectedConn = connections.find(c => c.id === connId);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 70,
      background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center", justifyContent: "center",
    }}
      onClick={onCancel}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--bg-2)", border: "1px solid var(--b2)",
          borderRadius: "var(--r3)", width: 480,
          display: "flex", flexDirection: "column",
          boxShadow: "0 20px 60px rgba(0,0,0,.4)",
          maxHeight: "90vh",
        }}
      >
        {/* Modal header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "0 20px", borderBottom: "1px solid var(--b1)", height: 52, flexShrink: 0,
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>New Canvas</span>
          <button onClick={onCancel} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", padding: 4 }}>
            <Icon d={CLOSE_ICON} size={14} />
          </button>
        </div>

        {/* Step indicator */}
        <div style={{ display: "flex", alignItems: "center", padding: "16px 24px 0", gap: 0, flexShrink: 0 }}>
          {([1, 2, 3] as const).map((n, i) => (
            <div key={n} style={{ display: "flex", alignItems: "center", flex: n < 3 ? 1 : 0 }}>
              <StepDot n={n} active={step === n} done={step > n} />
              {n < 3 && (
                <div style={{
                  flex: 1, height: 1.5, margin: "0 6px",
                  background: step > n ? "var(--blue4)" : "var(--b2)",
                  transition: "background .15s",
                }} />
              )}
            </div>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", gap: 16, paddingLeft: 16 }}>
            {(["Name", "Connection", "Tables"] as const).map((label, i) => (
              <span key={label} style={{
                fontSize: 10, color: step === i + 1 ? "var(--t1)" : "var(--t4)",
                fontWeight: step === i + 1 ? 600 : 400,
                transition: "color .15s",
              }}>
                {label}
              </span>
            ))}
          </div>
        </div>

        {/* Step content */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>

          {/* ── Step 1: Name ── */}
          {step === 1 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div>
                <label className="aug-label" style={{ display: "block", marginBottom: 6 }}>Canvas name *</label>
                <input
                  className="aug-input"
                  autoFocus
                  placeholder="e.g. Revenue Analysis, APAC Customers…"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && name.trim()) setStep(2); }}
                  style={{ width: "100%" }}
                />
              </div>
              <div>
                <label className="aug-label" style={{ display: "block", marginBottom: 6 }}>Description <span style={{ color: "var(--t4)", fontWeight: 400 }}>(optional)</span></label>
                <textarea
                  className="aug-input"
                  placeholder="What is this canvas for?"
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  rows={3}
                  style={{ width: "100%", resize: "vertical", fontFamily: "var(--font-ui)", fontSize: 12 }}
                />
              </div>
            </div>
          )}

          {/* ── Step 2: Connection ── */}
          {step === 2 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <label className="aug-label" style={{ display: "block", marginBottom: 4 }}>Select a connection</label>
              {connections.map(conn => {
                const active = connId === conn.id;
                const label = conn.conn_type === "duckdb" ? "DuckDB" : conn.conn_type === "postgres" ? "PostgreSQL" : conn.conn_type;
                return (
                  <button
                    key={conn.id}
                    onClick={() => setConnId(conn.id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 12,
                      padding: "12px 14px", borderRadius: "var(--r2)", textAlign: "left",
                      background: active ? "color-mix(in srgb, var(--blue4) 10%, var(--bg-3))" : "var(--bg-3)",
                      border: `1px solid ${active ? "var(--blue4)" : "var(--b1)"}`,
                      cursor: "pointer", transition: "all .1s",
                    }}
                  >
                    <div style={{
                      width: 30, height: 30, borderRadius: "var(--r2)", flexShrink: 0,
                      background: active ? "color-mix(in srgb, var(--blue4) 15%, transparent)" : "var(--bg-2)",
                      border: `1px solid ${active ? "var(--blue4)" : "var(--b2)"}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      color: active ? "var(--blue4)" : "var(--t3)",
                    }}>
                      <Icon d={DB_ICON} size={14} color={active ? "var(--blue4)" : "var(--t3)"} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>{conn.name}</div>
                      <div style={{ fontSize: 11, color: "var(--t3)" }}>{label}</div>
                    </div>
                    {active && <Icon d={CHECK_ICON} size={14} color="var(--blue4)" />}
                  </button>
                );
              })}
            </div>
          )}

          {/* ── Step 3: Tables ── */}
          {step === 3 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)", marginBottom: 2 }}>
                  Which tables should this canvas include?
                </div>
                <div style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.5 }}>
                  Scoping to specific tables keeps investigations focused and reduces noise.
                </div>
              </div>

              {/* All tables toggle */}
              <button
                onClick={() => { setUseAllTables(true); setSelectedTables(new Set()); }}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 14px", borderRadius: "var(--r2)", textAlign: "left",
                  background: useAllTables ? "color-mix(in srgb, var(--grn3) 8%, var(--bg-3))" : "var(--bg-3)",
                  border: `1px solid ${useAllTables ? "color-mix(in srgb, var(--grn3) 30%, transparent)" : "var(--b1)"}`,
                  cursor: "pointer", transition: "all .1s",
                }}
              >
                <div style={{
                  width: 16, height: 16, borderRadius: 4, flexShrink: 0,
                  background: useAllTables ? "var(--grn4)" : "var(--bg-2)",
                  border: `1.5px solid ${useAllTables ? "var(--grn4)" : "var(--b2)"}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {useAllTables && <Icon d={CHECK_ICON} size={9} color="var(--bg-0)" />}
                </div>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)" }}>All tables</div>
                  <div style={{ fontSize: 10, color: "var(--t3)" }}>Always includes new tables as your schema evolves</div>
                </div>
              </button>

              {/* Specific tables toggle */}
              <button
                onClick={() => setUseAllTables(false)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 14px", borderRadius: "var(--r2)", textAlign: "left",
                  background: !useAllTables ? "color-mix(in srgb, var(--blue4) 8%, var(--bg-3))" : "var(--bg-3)",
                  border: `1px solid ${!useAllTables ? "var(--blue4)" : "var(--b1)"}`,
                  cursor: "pointer", transition: "all .1s",
                }}
              >
                <div style={{
                  width: 16, height: 16, borderRadius: 4, flexShrink: 0,
                  background: !useAllTables ? "var(--blue4)" : "var(--bg-2)",
                  border: `1.5px solid ${!useAllTables ? "var(--blue4)" : "var(--b2)"}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {!useAllTables && <Icon d={CHECK_ICON} size={9} color="var(--bg-0)" />}
                </div>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)" }}>Specific tables</div>
                  <div style={{ fontSize: 10, color: "var(--t3)" }}>Limit to only the tables relevant to this canvas</div>
                </div>
              </button>

              {/* Table picker */}
              {!useAllTables && (
                <div style={{
                  border: "1px solid var(--b1)", borderRadius: "var(--r2)",
                  overflow: "hidden",
                }}>
                  {/* Search */}
                  <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", gap: 6 }}>
                    <Icon d={SEARCH_ICON} size={12} color="var(--t4)" />
                    <input
                      placeholder="Filter tables…"
                      value={tableSearch}
                      onChange={e => setTableSearch(e.target.value)}
                      style={{
                        flex: 1, background: "none", border: "none", outline: "none",
                        fontSize: 12, color: "var(--t1)",
                        fontFamily: "var(--font-ui)",
                      }}
                    />
                    {selectedTables.size > 0 && (
                      <span style={{ fontSize: 10, color: "var(--blue4)", fontWeight: 500 }}>
                        {selectedTables.size} selected
                      </span>
                    )}
                  </div>

                  {/* Table list */}
                  <div style={{ maxHeight: 220, overflowY: "auto" }}>
                    {loadingTables ? (
                      <div style={{ padding: "16px", textAlign: "center", fontSize: 11, color: "var(--t4)" }}>
                        Loading tables…
                      </div>
                    ) : filteredTables.length === 0 ? (
                      <div style={{ padding: "16px", textAlign: "center", fontSize: 11, color: "var(--t4)" }}>
                        {tableSearch ? "No matching tables" : "No tables found"}
                      </div>
                    ) : (
                      filteredTables.map(t => {
                        const checked = selectedTables.has(t);
                        return (
                          <button
                            key={t}
                            onClick={() => toggleTable(t)}
                            style={{
                              width: "100%", display: "flex", alignItems: "center", gap: 10,
                              padding: "8px 12px", background: checked ? "color-mix(in srgb, var(--blue4) 6%, transparent)" : "transparent",
                              border: "none", borderBottom: "1px solid var(--b0)",
                              cursor: "pointer", textAlign: "left", transition: "background .08s",
                            }}
                            onMouseEnter={e => { if (!checked) e.currentTarget.style.background = "var(--bg-hover)"; }}
                            onMouseLeave={e => { if (!checked) e.currentTarget.style.background = "transparent"; }}
                          >
                            <div style={{
                              width: 14, height: 14, borderRadius: 3, flexShrink: 0,
                              background: checked ? "var(--blue4)" : "var(--bg-2)",
                              border: `1.5px solid ${checked ? "var(--blue4)" : "var(--b2)"}`,
                              display: "flex", alignItems: "center", justifyContent: "center",
                            }}>
                              {checked && <Icon d={CHECK_ICON} size={8} color="var(--bg-0)" />}
                            </div>
                            <Icon d={TABLE_ICON} size={11} color="var(--t4)" />
                            <span style={{ fontSize: 12, color: "var(--t1)", fontFamily: "var(--font-mono)" }}>{t}</span>
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "14px 20px", borderTop: "1px solid var(--b1)", flexShrink: 0,
        }}>
          {/* Back */}
          <div>
            {step > 1 && (
              <button
                onClick={() => setStep(s => (s - 1) as 1 | 2 | 3)}
                className="aug-btn aug-btn-ghost aug-btn-sm"
                style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
              >
                <Icon d={CHEVL_ICON} size={11} /> Back
              </button>
            )}
          </div>

          {/* Error */}
          {error && <span style={{ fontSize: 11, color: "var(--red4)" }}>{error}</span>}

          {/* Next / Create */}
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onCancel} className="aug-btn aug-btn-ghost">Cancel</button>

            {step < 3 ? (
              <button
                onClick={() => setStep(s => (s + 1) as 2 | 3)}
                disabled={step === 1 && !name.trim() || step === 2 && !connId}
                className="aug-btn aug-btn-primary"
                style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
              >
                Next <Icon d={CHEVR_ICON} size={11} color="currentColor" />
              </button>
            ) : (
              <button
                onClick={handleCreate}
                disabled={saving || (!useAllTables && selectedTables.size === 0)}
                className="aug-btn aug-btn-primary"
                style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
              >
                {saving ? "Creating…" : "Create Canvas"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
