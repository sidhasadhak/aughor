"use client";

/**
 * DE-5e (ROADMAP §3.51) — the value viewer under the grid, by what the value IS.
 *
 * A JSON document opens as a tree, an image URL as the image — once asked, because loading it tells
 * that host somebody looked — and a geometry as its outline drawn to its own bounds, with the bounds
 * said beside it. Everything else is the text it always was. The header says how the value was read
 * (`lib/query/cellKind.ts`): from the text, from the declared type, or both; and a "Text" toggle shows
 * the raw value under any viewer, so nothing a viewer draws is ever the only thing on offer.
 */
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { formatCount } from "@/lib/format";
import { classifyCell, describeGeometry, describeKind } from "@/lib/query/cellKind";
import { NULL_GLYPH, jsonLiteral } from "@/lib/query/cellMenu";
import { GeometryOutline } from "@/components/query/GeometryOutline";
import type { Cell } from "@/lib/query/resultFilter";

const mono: React.CSSProperties = { fontFamily: "var(--font-mono)" };

export function ValueViewer({ value, column, declaredType, row, onClose }: {
  value: Cell;
  column: string;
  /** The column's declared type, as the result's `columns_typed` names it; null for a legacy result. */
  declaredType?: string | null;
  /** 1-based, for the header. */
  row: number;
  onClose: () => void;
}) {
  const [raw, setRaw] = useState(false);
  const kind = useMemo(() => classifyCell(value, declaredType), [value, declaredType]);
  const text = value === null || value === undefined ? "" : String(value);
  // A new cell is a new viewer: the raw toggle and a loaded image belong to the value they were asked for.
  useEffect(() => { setRaw(false); }, [value]);
  const structured = kind.kind === "json" || kind.kind === "image" || kind.kind === "geometry";

  const copy = () => { navigator.clipboard?.writeText(text).catch(() => {}); };

  let body: React.ReactNode;
  if (!structured || raw) {
    body = (
      <pre className="aug-fs-sm" data-testid="grid-value-text" style={{ ...mono, margin: 0, whiteSpace: "pre-wrap",
        wordBreak: "break-word", color: value === null ? "var(--t3)" : "var(--t2)" }}>
        {value === null || value === undefined ? NULL_GLYPH : kind.kind === "json" ? jsonLiteral(value) : text}
      </pre>
    );
  } else if (kind.kind === "json") {
    body = <JsonTree value={kind.value} />;
  } else if (kind.kind === "image") {
    body = <ImageView key={text} url={kind.image.url} host={kind.image.host} inline={kind.image.via === "data"} alt={column} />;
  } else {
    body = (
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start", paddingTop: 4 }}>
        <GeometryOutline geometry={kind.parsed.geometry} />
        <div className="aug-fs-xs" data-testid="geometry-caption" style={{ color: "var(--t3)", lineHeight: 1.5 }}>
          <div style={{ color: "var(--t2)" }}>{describeGeometry(kind.parsed)}</div>
          <div>Drawn to its own bounds — not on a map.</div>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="value-viewer" style={{ flexShrink: 0, borderTop: "1px solid var(--b1)", background: "var(--bg-1)",
      display: "flex", flexDirection: "column", maxHeight: 260 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 10px", flexWrap: "wrap" }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{column}</span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          row {row}{value === null ? " · NULL" : ` · ${formatCount(text.length)} chars`}
        </span>
        <span className="aug-fs-xs" data-testid="viewer-kind" style={{ color: "var(--t3)" }}>{describeKind(kind, declaredType)}</span>
        <span style={{ flex: 1 }} />
        {structured && (
          <Button size="xs" variant="ghost" data-testid="viewer-raw" onClick={() => setRaw(v => !v)}
            title={raw ? "Back to the viewer" : "The value as text, exactly as it came back"}>
            {raw ? "Viewer" : "Text"}
          </Button>
        )}
        <Button size="xs" variant="ghost" onClick={copy}>
          <Icon name="copy" size={12} /> Copy value
        </Button>
        <Button size="xs" variant="ghost" onClick={onClose} aria-label="Close">
          <Icon name="close" size={12} />
        </Button>
      </div>
      <div style={{ overflow: "auto", padding: "0 10px 10px" }}>{body}</div>
    </div>
  );
}

// ── JSON as a tree ────────────────────────────────────────────────────────────────────────────

function JsonTree({ value }: { value: unknown }) {
  const [closed, setClosed] = useState<Set<string>>(() => new Set());
  const toggle = (path: string) => setClosed(prev => {
    const next = new Set(prev);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });
  return (
    <div className="aug-fs-sm" data-testid="json-tree" style={{ ...mono, color: "var(--t2)", lineHeight: 1.6 }}>
      <JsonNode name={null} value={value} path="$" depth={0} closed={closed} toggle={toggle} />
    </div>
  );
}

function JsonNode({ name, value, path, depth, closed, toggle }: {
  name: string | null; value: unknown; path: string; depth: number;
  closed: Set<string>; toggle: (path: string) => void;
}) {
  const label = name !== null ? <span style={{ color: "var(--t1)" }}>{name}: </span> : null;
  if (value === null || typeof value !== "object") {
    return <div style={{ paddingLeft: depth * 14 + 14 }}>{label}<JsonLeaf value={value} /></div>;
  }
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as [string, unknown])
    : Object.entries(value as Record<string, unknown>);
  const open = !closed.has(path);
  const n = entries.length;
  const summary = Array.isArray(value) ? `[${n} ${n === 1 ? "item" : "items"}]` : `{${n} ${n === 1 ? "key" : "keys"}}`;
  return (
    <div>
      <div role="button" tabIndex={0} data-testid="json-node" aria-expanded={open}
        onClick={() => toggle(path)}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(path); } }}
        style={{ paddingLeft: depth * 14, cursor: "pointer", userSelect: "none" }}>
        <span aria-hidden style={{ display: "inline-block", width: 14, color: "var(--t3)" }}>{open ? "▾" : "▸"}</span>
        {label}<span style={{ color: "var(--t3)" }}>{summary}</span>
      </div>
      {open && entries.map(([k, v]) => (
        <JsonNode key={k} name={k} value={v} path={`${path}.${k}`} depth={depth + 1} closed={closed} toggle={toggle} />
      ))}
    </div>
  );
}

function JsonLeaf({ value }: { value: unknown }) {
  if (value === null) return <span style={{ color: "var(--t3)" }}>{NULL_GLYPH}</span>;
  if (typeof value === "string") return <span style={{ color: "var(--t1)" }}>{JSON.stringify(value)}</span>;
  return <span style={{ color: "var(--t2)" }}>{String(value)}</span>;
}

// ── An image, once asked ─────────────────────────────────────────────────────────────────────

function ImageView({ url, host, inline, alt }: { url: string; host: string | null; inline: boolean; alt: string }) {
  // Inline data carries its own bytes, so showing it tells nobody anything; a URL is fetched from
  // its host, and that is the viewer's decision to make, not the grid's.
  const [state, setState] = useState<"idle" | "loading" | "loaded" | "failed">(inline ? "loading" : "idle");
  const [size, setSize] = useState("");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 4 }}>
      {state === "idle" ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Button size="xs" variant="secondary" data-testid="image-load" onClick={() => setState("loading")}>
            <Icon name="eye" size={12} /> Load image
          </Button>
          <span className="aug-fs-xs" data-testid="image-note" style={{ color: "var(--t3)" }}>
            Not loaded — loading it tells {host ?? "its host"} that you looked.
          </span>
        </div>
      ) : (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element -- a value from a cell, not an asset of ours */}
          <img src={url} alt={alt} data-testid="image-view"
            onLoad={e => { setState("loaded"); setSize(`${e.currentTarget.naturalWidth} × ${e.currentTarget.naturalHeight}`); }}
            onError={() => setState("failed")}
            style={{ maxWidth: "100%", maxHeight: 180, objectFit: "contain", alignSelf: "flex-start",
              border: "1px solid var(--b1)", borderRadius: "var(--r1)", background: "var(--bg-2)" }} />
          <span className="aug-fs-xs" data-testid="image-note" style={{ color: state === "failed" ? "var(--red4)" : "var(--t3)" }}>
            {state === "failed" ? `The image could not be loaded from ${host ?? "the data URL"}.`
              : state === "loaded" ? `${size} px${host ? ` · from ${host}` : ""}`
                : "Loading…"}
          </span>
        </>
      )}
    </div>
  );
}
