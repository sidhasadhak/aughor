"use client";

import { useEffect, useState } from "react";
import DeleteIcon from "@atlaskit/icon/core/delete";
import { Badge } from "@/components/ui/badge";
import {
  addConnection,
  deleteConnection,
  getConnections,
  testConnection,
  type Connection,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { ExplorationBadge } from "@/components/ExplorationBadge";

interface Props {
  selectedId: string;
  onSelect: (id: string) => void;
  activeSchemaId: string | null;
  onSchemaSelect: (id: string | null) => void;
}

const TYPE_LABELS: Record<string, string> = {
  duckdb: "DuckDB",
  postgres: "Postgres",
};

const TYPE_COLORS: Record<string, string> = {
  duckdb: "border-yellow-500/30 bg-yellow-500/10 text-yellow-400",
  postgres: "border-blue-500/30 bg-blue-500/10 text-blue-400",
};

export function ConnectionsPanel({ selectedId, onSelect, activeSchemaId, onSchemaSelect }: Props) {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [adding, setAdding] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; msg: string }>>({});

  const [formName, setFormName] = useState("");
  const [formType, setFormType] = useState("postgres");
  const [formDsn, setFormDsn] = useState("");
  const [formSchema, setFormSchema] = useState("");
  const [formError, setFormError] = useState("");
  const [formLoading, setFormLoading] = useState(false);
  // id of connection pending delete confirmation; null = none
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const load = async () => {
    try { setConnections(await getConnections()); } catch {}
  };

  useEffect(() => { load(); }, []);

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const result = await testConnection(id);
      setTestResults(prev => ({ ...prev, [id]: { ok: result.ok, msg: result.message } }));
    } catch {
      setTestResults(prev => ({ ...prev, [id]: { ok: false, msg: "Request failed" } }));
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (pendingDelete !== id) {
      // First click: arm the confirm state; auto-clear after 3 s
      setPendingDelete(id);
      setTimeout(() => setPendingDelete(prev => prev === id ? null : prev), 3000);
      return;
    }
    // Second click: confirmed — delete
    setPendingDelete(null);
    await deleteConnection(id);
    if (selectedId === id) onSelect("fixture");
    if (activeSchemaId === id) onSchemaSelect(null);
    await load();
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    setFormLoading(true);
    try {
      await addConnection(formName, formType, formDsn, formSchema || undefined);
      setFormName(""); setFormDsn(""); setFormSchema(""); setAdding(false);
      await load();
    } catch (err: any) {
      setFormError(err.message);
    } finally {
      setFormLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full w-72 shrink-0 border-r border-zinc-600">
      <div className="p-4 border-b border-zinc-600 flex items-center justify-between">
        <p className="text-xs font-semibold text-zinc-300 uppercase tracking-wide">Connections</p>
        <button
          onClick={() => setAdding(!adding)}
          className="text-xs text-zinc-400 hover:text-zinc-200 border border-zinc-600 hover:border-zinc-500 rounded px-2 py-1 transition"
        >
          {adding ? "Cancel" : "+ Add"}
        </button>
      </div>

      {adding && (
        <form onSubmit={handleAdd} className="p-4 border-b border-zinc-600 space-y-3 bg-zinc-800/40">
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">Name</label>
            <input
              className="w-full rounded bg-zinc-800 border border-zinc-600 text-sm text-zinc-100 px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              placeholder="Production DB"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">Type</label>
            <select
              className="w-full rounded bg-zinc-800 border border-zinc-600 text-sm text-zinc-100 px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              value={formType}
              onChange={e => setFormType(e.target.value)}
            >
              <option value="postgres">PostgreSQL</option>
              <option value="duckdb">DuckDB file</option>
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">
              {formType === "postgres" ? "Connection string" : "File path"}
            </label>
            <input
              className="w-full rounded bg-zinc-800 border border-zinc-600 text-sm text-zinc-300 font-mono px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              placeholder={formType === "postgres" ? "postgresql://user:pass@host:5432/db" : "/path/to/file.duckdb"}
              value={formDsn}
              onChange={e => setFormDsn(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">
              Schema <span className="text-zinc-500">(optional)</span>
            </label>
            <input
              className="w-full rounded bg-zinc-800 border border-zinc-600 text-sm text-zinc-300 font-mono px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              placeholder={formType === "postgres" ? "public" : "main"}
              value={formSchema}
              onChange={e => setFormSchema(e.target.value)}
            />
            <p className="text-[10px] text-zinc-500 leading-relaxed">
              Restricts table discovery and queries to this schema only.
              Leave blank to use the default.
            </p>
          </div>
          {formError && <p className="text-xs text-red-400">{formError}</p>}
          <button
            type="submit"
            disabled={formLoading}
            className="w-full rounded bg-zinc-100 text-zinc-900 text-sm font-medium py-1.5 hover:bg-white disabled:opacity-40 transition"
          >
            {formLoading ? "Testing & saving…" : "Save connection"}
          </button>
        </form>
      )}

      <div className="flex-1 overflow-y-auto">
        {connections.map(conn => {
          const isSelected = conn.id === selectedId;
          const isSchemaActive = conn.id === activeSchemaId;
          const result = testResults[conn.id];
          const dotColor = result
            ? result.ok ? "bg-emerald-500" : "bg-red-500"
            : isSelected ? "bg-emerald-500" : "bg-zinc-700";
          return (
            <div
              key={conn.id}
              className={cn(
                "border-b border-zinc-600/60 transition-colors",
                isSelected ? "bg-zinc-800/60 border-l-2 border-l-violet-500" : "border-l-2 border-l-transparent"
              )}
            >
              <button
                onClick={() => onSelect(conn.id)}
                className="w-full text-left px-4 py-3 hover:bg-zinc-700/40 transition"
              >
                <div className="flex items-center gap-2.5">
                  <span
                    title={result ? (result.ok ? "Connected" : "Connection failed") : "Untested"}
                    className={cn("w-2 h-2 rounded-full shrink-0 transition-colors", dotColor)}
                  />
                  <span className={cn("text-sm font-medium truncate flex-1", isSelected ? "text-white" : "text-zinc-300")}>
                    {conn.name}
                  </span>
                  <Badge variant="outline" className={cn("text-xs shrink-0", TYPE_COLORS[conn.conn_type] ?? "")}>
                    {TYPE_LABELS[conn.conn_type] ?? conn.conn_type}
                  </Badge>
                </div>
                <p className="text-xs font-mono text-zinc-500 mt-1 truncate pl-4">{conn.dsn_preview}</p>
                {conn.schema_name && (
                  <p className="text-[10px] text-zinc-500 mt-0.5 pl-4">
                    schema: <span className="font-mono text-zinc-400">{conn.schema_name}</span>
                  </p>
                )}
                <ExplorationBadge connectionId={conn.id} />
              </button>

              <div className="px-4 pb-2.5 flex items-center gap-3">
                <button
                  onClick={() => handleTest(conn.id)}
                  disabled={testing === conn.id}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition disabled:opacity-40"
                >
                  {testing === conn.id ? "Testing…" : "Test"}
                </button>
                {result && (
                  <span className={cn("text-xs", result.ok ? "text-emerald-400" : "text-red-400")}>
                    {result.ok ? "✓" : "✕"} {result.msg}
                  </span>
                )}
                <button
                  onClick={() => onSchemaSelect(isSchemaActive ? null : conn.id)}
                  className={cn(
                    "text-xs transition",
                    isSchemaActive ? "text-violet-400" : "text-zinc-500 hover:text-zinc-300"
                  )}
                >
                  {isSchemaActive ? "Schema ●" : "Schema"}
                </button>
                {!conn.builtin && (
                  <button
                    onClick={() => handleDelete(conn.id)}
                    className={cn(
                      "text-xs transition ml-auto flex items-center gap-1",
                      pendingDelete === conn.id
                        ? "text-red-400 font-medium"
                        : "text-zinc-500 hover:text-red-400"
                    )}
                  >
                    {pendingDelete === conn.id ? (
                      <>
                        <DeleteIcon label="Delete" size="small" />
                        Confirm delete
                      </>
                    ) : (
                      <>
                        <DeleteIcon label="Delete" size="small" />
                        Delete
                      </>
                    )}
                  </button>
                )}
              </div>

            </div>
          );
        })}
      </div>
    </div>
  );
}
