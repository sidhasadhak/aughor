"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  addConnection,
  deleteConnection,
  getConnections,
  getSchema,
  testConnection,
  type Connection,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  selectedId: string;
  onSelect: (id: string) => void;
}

const TYPE_LABELS: Record<string, string> = {
  duckdb: "DuckDB",
  postgres: "Postgres",
};

const TYPE_COLORS: Record<string, string> = {
  duckdb: "border-yellow-500/30 bg-yellow-500/10 text-yellow-400",
  postgres: "border-blue-500/30 bg-blue-500/10 text-blue-400",
};

export function ConnectionsPanel({ selectedId, onSelect }: Props) {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [adding, setAdding] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; msg: string }>>({});
  const [schemaConn, setSchemaConn] = useState<string | null>(null);
  const [schema, setSchema] = useState<string>("");
  const [schemaLoading, setSchemaLoading] = useState(false);

  // Add form state
  const [formName, setFormName] = useState("");
  const [formType, setFormType] = useState("postgres");
  const [formDsn, setFormDsn] = useState("");
  const [formError, setFormError] = useState("");
  const [formLoading, setFormLoading] = useState(false);

  const load = async () => {
    try {
      setConnections(await getConnections());
    } catch {}
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

  const handleSchema = async (id: string) => {
    if (schemaConn === id) { setSchemaConn(null); return; }
    setSchemaConn(id);
    setSchemaLoading(true);
    try {
      setSchema(await getSchema(id));
    } catch {
      setSchema("Failed to load schema.");
    } finally {
      setSchemaLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    await deleteConnection(id);
    if (selectedId === id) onSelect("fixture");
    await load();
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    setFormLoading(true);
    try {
      await addConnection(formName, formType, formDsn);
      setFormName(""); setFormDsn(""); setAdding(false);
      await load();
    } catch (err: any) {
      setFormError(err.message);
    } finally {
      setFormLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
        <p className="text-xs font-semibold text-zinc-300 uppercase tracking-wide">Connections</p>
        <button
          onClick={() => setAdding(!adding)}
          className="text-xs text-zinc-400 hover:text-zinc-200 border border-zinc-700 hover:border-zinc-500 rounded px-2 py-1 transition"
        >
          {adding ? "Cancel" : "+ Add"}
        </button>
      </div>

      {/* Add connection form */}
      {adding && (
        <form onSubmit={handleAdd} className="p-4 border-b border-zinc-800 space-y-3 bg-zinc-900/40">
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">Name</label>
            <input
              className="w-full rounded bg-zinc-900 border border-zinc-700 text-sm text-zinc-100 px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              placeholder="Production DB"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">Type</label>
            <select
              className="w-full rounded bg-zinc-900 border border-zinc-700 text-sm text-zinc-100 px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500"
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
              className="w-full rounded bg-zinc-900 border border-zinc-700 text-sm text-zinc-300 font-mono px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              placeholder={formType === "postgres" ? "postgresql://user:pass@host:5432/db" : "/path/to/file.duckdb"}
              value={formDsn}
              onChange={e => setFormDsn(e.target.value)}
              required
            />
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

      {/* Connection list */}
      <div className="flex-1 overflow-y-auto">
        {connections.map(conn => {
          const isSelected = conn.id === selectedId;
          const result = testResults[conn.id];
          return (
            <div key={conn.id} className={cn("border-b border-zinc-800/60", isSelected && "bg-zinc-900/60")}>
              <button
                onClick={() => onSelect(conn.id)}
                className="w-full text-left px-4 py-3 hover:bg-zinc-900/40 transition"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={cn("text-sm font-medium", isSelected ? "text-white" : "text-zinc-300")}>
                    {conn.name}
                  </span>
                  <Badge variant="outline" className={cn("text-xs shrink-0", TYPE_COLORS[conn.conn_type] ?? "")}>
                    {TYPE_LABELS[conn.conn_type] ?? conn.conn_type}
                  </Badge>
                </div>
                <p className="text-xs font-mono text-zinc-600 mt-0.5 truncate">{conn.dsn_preview}</p>
              </button>

              {/* Actions row */}
              <div className="px-4 pb-2 flex items-center gap-3">
                <button
                  onClick={() => handleTest(conn.id)}
                  disabled={testing === conn.id}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition disabled:opacity-40"
                >
                  {testing === conn.id ? "Testing…" : "Test"}
                </button>
                <button
                  onClick={() => handleSchema(conn.id)}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition"
                >
                  {schemaConn === conn.id ? "Hide schema" : "Schema"}
                </button>
                {!conn.builtin && (
                  <button
                    onClick={() => handleDelete(conn.id)}
                    className="text-xs text-zinc-600 hover:text-red-400 transition ml-auto"
                  >
                    Remove
                  </button>
                )}
              </div>

              {result && (
                <p className={cn("px-4 pb-2 text-xs", result.ok ? "text-emerald-400" : "text-red-400")}>
                  {result.ok ? "✓" : "✕"} {result.msg}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* Schema drawer */}
      {schemaConn && (
        <div className="border-t border-zinc-800 flex flex-col" style={{ maxHeight: "40%" }}>
          <div className="px-4 py-2 flex items-center justify-between border-b border-zinc-800">
            <p className="text-xs text-zinc-500 uppercase tracking-wide">Schema</p>
            <button onClick={() => setSchemaConn(null)} className="text-xs text-zinc-600 hover:text-zinc-300">✕</button>
          </div>
          <div className="overflow-y-auto p-4">
            {schemaLoading ? (
              <p className="text-xs text-zinc-600">Loading…</p>
            ) : (
              <pre className="text-xs text-zinc-400 whitespace-pre-wrap font-mono leading-relaxed">{schema}</pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
