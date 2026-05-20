"use client";

import { useEffect, useRef, useState } from "react";
import { getSchemaRich, getSchemaDiagram, RichSchema } from "@/lib/api";
import { SchemaCards } from "./SchemaCards";

interface Props {
  connId: string | null;
  connName?: string;
}

type PanelTab = "schema" | "diagram";

export function SchemaPanel({ connId, connName }: Props) {
  const [tab, setTab] = useState<PanelTab>("schema");
  const [richSchema, setRichSchema] = useState<RichSchema | null>(null);
  const [diagram, setDiagram] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [diagramLoading, setDiagramLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const diagramRef = useRef<HTMLDivElement>(null);
  const mermaidLoaded = useRef(false);

  useEffect(() => {
    if (!connId) { setRichSchema(null); setDiagram(""); return; }
    setLoading(true);
    setError(null);
    getSchemaRich(connId)
      .then(setRichSchema)
      .catch(() => setError("Failed to load schema."))
      .finally(() => setLoading(false));
  }, [connId]);

  // Load diagram lazily when tab is first switched to "diagram"
  useEffect(() => {
    if (tab !== "diagram" || !connId || diagram) return;
    setDiagramLoading(true);
    getSchemaDiagram(connId)
      .then(setDiagram)
      .catch(() => setDiagram(""))
      .finally(() => setDiagramLoading(false));
  }, [tab, connId, diagram]);

  // Reset caches when connection changes
  useEffect(() => { setDiagram(""); setRichSchema(null); }, [connId]);

  // Render Mermaid once source is ready and tab is active
  useEffect(() => {
    if (tab !== "diagram" || !diagram || !diagramRef.current) return;

    const render = async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        if (!mermaidLoaded.current) {
          mermaid.initialize({
            startOnLoad: false,
            theme: "dark",
            er: { layoutDirection: "LR", diagramPadding: 20, entityPadding: 12, useMaxWidth: true },
          });
          mermaidLoaded.current = true;
        }
        const id = `er-${Date.now()}`;
        const { svg } = await mermaid.render(id, diagram);
        if (diagramRef.current) diagramRef.current.innerHTML = svg;
      } catch (e) {
        if (diagramRef.current) {
          diagramRef.current.innerHTML = `<pre class="text-red-400 text-xs p-4 whitespace-pre-wrap">Diagram render error:\n${e}</pre>`;
        }
      }
    };
    render();
  }, [tab, diagram]);

  if (!connId) {
    return (
      <div className="flex-1 flex items-center justify-center border-l border-zinc-600">
        <p className="text-xs text-zinc-600">Select a connection to view its schema</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 border-l border-zinc-600">
      {/* Header with sub-tabs */}
      <div className="border-b border-zinc-600 shrink-0">
        <div className="px-4 flex items-center gap-0">
          {(["schema", "diagram"] as PanelTab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2.5 text-xs font-medium transition-colors border-b-2 -mb-px ${
                tab === t
                  ? "border-violet-500 text-violet-400"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {t === "schema" ? "Tables" : "ER Diagram"}
            </button>
          ))}
          {(loading || diagramLoading) && (
            <span className="text-xs text-zinc-700 ml-auto">Loading…</span>
          )}
        </div>
        {/* Search — schema tab only */}
        {tab === "schema" && richSchema && (
          <div className="px-3 pb-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search tables or columns…"
              className="w-full rounded-lg bg-zinc-800 border border-zinc-600 text-xs text-zinc-300 placeholder:text-zinc-600 px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-600 transition"
            />
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {tab === "schema" ? (
          error ? (
            <div className="p-4">
              <p className="text-xs text-red-400">{error}</p>
            </div>
          ) : loading ? (
            <div className="p-4 space-y-3 animate-pulse">
              {[70, 50, 85, 60, 75].map((w, i) => (
                <div key={i} className="h-3 bg-zinc-800 rounded" style={{ width: `${w}%` }} />
              ))}
            </div>
          ) : richSchema ? (
            <SchemaCards schema={richSchema} search={search} />
          ) : null
        ) : (
          <div className="p-4 min-h-full">
            {diagramLoading ? (
              <div className="flex items-center justify-center h-48">
                <span className="text-xs text-zinc-600">Building ER diagram…</span>
              </div>
            ) : !diagram ? (
              <div className="flex items-center justify-center h-48">
                <span className="text-xs text-zinc-600">No schema loaded or no tables found.</span>
              </div>
            ) : (
              <>
                <div
                  ref={diagramRef}
                  className="w-full overflow-auto [&_svg]:max-w-full [&_svg]:h-auto"
                />
                <details className="mt-4">
                  <summary className="text-xs text-zinc-600 cursor-pointer hover:text-zinc-400 transition-colors">
                    Mermaid source
                  </summary>
                  <pre className="mt-2 text-xs text-zinc-500 font-mono whitespace-pre-wrap bg-zinc-800 rounded p-3">
                    {diagram}
                  </pre>
                </details>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
