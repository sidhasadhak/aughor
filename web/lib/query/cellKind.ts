/**
 * DE-5e (ROADMAP §3.51) — what a cell's value IS, read from the value and the column's declared type,
 * so the value viewer can show a JSON document as a tree, an image URL as the image (once asked), and
 * a geometry as its outline — and say in each case how it read the value.
 *
 * Measured first: no engine hands the web a geometry it can recognise by TYPE alone. BigQuery returns a
 * GEOGRAPHY as WKT text, Snowflake as GeoJSON text, Postgres (PostGIS) as hex EWKB under an OID the
 * driver does not name, MySQL as bytes with a 4-byte SRID in front of the WKB, and the warehouse
 * connectors used to flatten every such type name to VARCHAR. So the kind is read from the VALUE first,
 * and the declared type is the second witness: the viewer says which one it believed.
 *
 * Pure functions, no DOM. The parsers are strict — a WKB decode must consume every byte, a WKT must
 * parse to its end — so a hex id or a bracketed note is never mistaken for a shape.
 */
import type { Cell } from "@/lib/query/resultFilter";
import { columnTypeKind } from "@/lib/format";

// ── Geometry ──────────────────────────────────────────────────────────────────────────────────

export type Position = number[];
export type GeoJsonGeometry =
  | { type: "Point"; coordinates: Position }
  | { type: "MultiPoint"; coordinates: Position[] }
  | { type: "LineString"; coordinates: Position[] }
  | { type: "MultiLineString"; coordinates: Position[][] }
  | { type: "Polygon"; coordinates: Position[][] }
  | { type: "MultiPolygon"; coordinates: Position[][][] }
  | { type: "GeometryCollection"; geometries: GeoJsonGeometry[] };

export type GeometryEncoding = "wkt" | "geojson" | "wkb-hex";

export interface ParsedGeometry {
  geometry: GeoJsonGeometry;
  encoding: GeometryEncoding;
  /** The spatial reference the value carried (`SRID=4326;…`, an EWKB flag, MySQL's prefix); undefined when none. */
  srid?: number;
}

const WKT_HEAD = /^\s*(?:SRID=(\d+)\s*;\s*)?(POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON|GEOMETRYCOLLECTION)\b/i;
const GEOMETRY_TYPES = new Set(["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"]);

/** Parse a WKT text (with an optional `SRID=n;` prefix, Z/M/ZM suffixes and EMPTY) into GeoJSON. null when it is not WKT. */
export function parseWkt(text: string): ParsedGeometry | null {
  const head = WKT_HEAD.exec(text);
  if (!head) return null;
  const srid = head[1] ? Number(head[1]) : undefined;
  const body = text.slice(text.indexOf(head[2]) + 0).trim();
  const tokens = tokenizeWkt(body);
  if (!tokens) return null;
  let i = 0;
  const peek = () => tokens[i];
  const next = () => tokens[i++];
  const expect = (t: string) => { if (next() !== t) throw new Error("wkt"); };
  const number = (): number => {
    const t = next();
    const n = Number(t);
    if (t === undefined || !Number.isFinite(n)) throw new Error("wkt");
    return n;
  };
  const position = (): Position => {
    const out: Position = [];
    while (peek() !== undefined && peek() !== "," && peek() !== ")") out.push(number());
    if (out.length < 2) throw new Error("wkt");
    return out;
  };
  const list = <T,>(item: () => T): T[] => {
    expect("(");
    const out: T[] = [item()];
    while (peek() === ",") { next(); out.push(item()); }
    expect(")");
    return out;
  };
  const positions = () => list(position);
  const pointBody = (): Position => { expect("("); const p = position(); expect(")"); return p; };
  const geometry = (): GeoJsonGeometry => {
    const kind = String(next() ?? "").toUpperCase();
    // Z, M and ZM say how many numbers a position carries; the numbers themselves say it too.
    while (/^(Z|M|ZM)$/i.test(String(peek() ?? ""))) next();
    if (String(peek() ?? "").toUpperCase() === "EMPTY") {
      next();
      switch (kind) {
        case "POINT": return { type: "Point", coordinates: [] };
        case "LINESTRING": return { type: "LineString", coordinates: [] };
        case "POLYGON": return { type: "Polygon", coordinates: [] };
        case "MULTIPOINT": return { type: "MultiPoint", coordinates: [] };
        case "MULTILINESTRING": return { type: "MultiLineString", coordinates: [] };
        case "MULTIPOLYGON": return { type: "MultiPolygon", coordinates: [] };
        case "GEOMETRYCOLLECTION": return { type: "GeometryCollection", geometries: [] };
        default: throw new Error("wkt");
      }
    }
    switch (kind) {
      case "POINT": return { type: "Point", coordinates: pointBody() };
      case "LINESTRING": return { type: "LineString", coordinates: positions() };
      case "POLYGON": return { type: "Polygon", coordinates: list(positions) };
      case "MULTIPOINT":
        // Both spellings are WKT: `MULTIPOINT ((1 2), (3 4))` and `MULTIPOINT (1 2, 3 4)`.
        return { type: "MultiPoint", coordinates: list(() => (peek() === "(" ? pointBody() : position())) };
      case "MULTILINESTRING": return { type: "MultiLineString", coordinates: list(positions) };
      case "MULTIPOLYGON": return { type: "MultiPolygon", coordinates: list(() => list(positions)) };
      case "GEOMETRYCOLLECTION": return { type: "GeometryCollection", geometries: list(geometry) };
      default: throw new Error("wkt");
    }
  };
  try {
    const g = geometry();
    if (i !== tokens.length) return null;
    return { geometry: g, encoding: "wkt", srid };
  } catch {
    return null;
  }
}

function tokenizeWkt(body: string): string[] | null {
  const out: string[] = [];
  const re = /\s*([A-Za-z]+|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[(),])\s*/y;
  let pos = 0;
  while (pos < body.length) {
    re.lastIndex = pos;
    const m = re.exec(body);
    if (!m || m.index !== pos) return null;
    out.push(m[1]);
    pos = re.lastIndex;
  }
  return out;
}

/** A parsed JSON value that is a GeoJSON geometry (or a Feature wrapping one). */
export function geoJsonGeometry(value: unknown): GeoJsonGeometry | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (v.type === "Feature" && v.geometry) return geoJsonGeometry(v.geometry);
  if (typeof v.type !== "string" || !GEOMETRY_TYPES.has(v.type)) return null;
  if (v.type === "GeometryCollection") {
    if (!Array.isArray(v.geometries)) return null;
    const parts = v.geometries.map(geoJsonGeometry);
    if (parts.some(p => p === null)) return null;
    return { type: "GeometryCollection", geometries: parts as GeoJsonGeometry[] };
  }
  if (!Array.isArray(v.coordinates)) return null;
  return v as unknown as GeoJsonGeometry;
}

const HEX = /^[0-9A-Fa-f]+$/;

/** Decode WKB given as hex — plain WKB, PostGIS EWKB (Z/M/SRID flags), ISO WKB (1000/2000/3000 type codes)
 *  and MySQL's internal form (a 4-byte SRID before the WKB). Every byte must be consumed. */
export function parseWkbHex(text: string): ParsedGeometry | null {
  const hex = text.trim();
  if (hex.length < 42 || hex.length % 2 !== 0 || !HEX.test(hex)) return null;
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  const view = new DataView(bytes.buffer);
  let offset = 0;
  let srid: number | undefined;
  // MySQL: the first byte is not a byte-order mark but the fifth is — a little-endian SRID leads.
  if (bytes[0] > 1 && bytes[4] <= 1) {
    srid = view.getUint32(0, true);
    offset = 4;
  }
  const readGeometry = (): GeoJsonGeometry => {
    const order = bytes[offset++];
    if (order !== 0 && order !== 1) throw new Error("wkb");
    const little = order === 1;
    let type = view.getUint32(offset, little); offset += 4;
    let dims = 2;
    if (type & 0x80000000) { dims += 1; type &= ~0x80000000; }
    if (type & 0x40000000) { dims += 1; type &= ~0x40000000; }
    if (type & 0x20000000) { type &= ~0x20000000; srid = view.getInt32(offset, little); offset += 4; }
    if (type >= 3000) { dims = 4; type -= 3000; }
    else if (type >= 2000) { dims = 3; type -= 2000; }
    else if (type >= 1000) { dims = 3; type -= 1000; }
    const position = (): Position => {
      const p: Position = [];
      for (let d = 0; d < dims; d++) { p.push(view.getFloat64(offset, little)); offset += 8; }
      return p;
    };
    const count = (): number => { const n = view.getUint32(offset, little); offset += 4; if (n > 1e6) throw new Error("wkb"); return n; };
    const positions = (): Position[] => { const n = count(); const out: Position[] = []; for (let k = 0; k < n; k++) out.push(position()); return out; };
    const many = <T,>(item: () => T): T[] => { const n = count(); const out: T[] = []; for (let k = 0; k < n; k++) out.push(item()); return out; };
    switch (type) {
      case 1: {
        const p = position();
        // A WKB empty point is NaN NaN.
        return { type: "Point", coordinates: p.every(Number.isNaN) ? [] : p };
      }
      case 2: return { type: "LineString", coordinates: positions() };
      case 3: return { type: "Polygon", coordinates: many(positions) };
      case 4: return { type: "MultiPoint", coordinates: many(() => { const g = readGeometry(); if (g.type !== "Point") throw new Error("wkb"); return g.coordinates; }) };
      case 5: return { type: "MultiLineString", coordinates: many(() => { const g = readGeometry(); if (g.type !== "LineString") throw new Error("wkb"); return g.coordinates; }) };
      case 6: return { type: "MultiPolygon", coordinates: many(() => { const g = readGeometry(); if (g.type !== "Polygon") throw new Error("wkb"); return g.coordinates; }) };
      case 7: return { type: "GeometryCollection", geometries: many(readGeometry) };
      default: throw new Error("wkb");
    }
  };
  try {
    const geometry = readGeometry();
    if (offset !== bytes.length) return null;
    return { geometry, encoding: "wkb-hex", srid };
  } catch {
    return null;
  }
}

/** Read a geometry from a cell's text in any of the three encodings an engine returns. */
export function parseGeometry(text: string): ParsedGeometry | null {
  const t = text.trim();
  if (!t) return null;
  const wkt = parseWkt(t);
  if (wkt) return wkt;
  if (t.startsWith("{")) {
    try {
      const g = geoJsonGeometry(JSON.parse(t));
      if (g) return { geometry: g, encoding: "geojson" };
    } catch { /* not JSON */ }
  }
  return parseWkbHex(t);
}

/** Every position of a geometry, flattened. */
export function positionsOf(g: GeoJsonGeometry): Position[] {
  switch (g.type) {
    case "Point": return g.coordinates.length ? [g.coordinates] : [];
    case "MultiPoint": case "LineString": return g.coordinates;
    case "MultiLineString": case "Polygon": return g.coordinates.flat();
    case "MultiPolygon": return g.coordinates.flat(2);
    case "GeometryCollection": return g.geometries.flatMap(positionsOf);
  }
}

export interface Bounds { minX: number; minY: number; maxX: number; maxY: number }

export function geometryBounds(g: GeoJsonGeometry): Bounds | null {
  const ps = positionsOf(g);
  if (!ps.length) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of ps) {
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
}

/** Whether every position fits longitude/latitude — the one thing the outline can say about what the numbers mean. */
export function looksLikeLonLat(g: GeoJsonGeometry): boolean {
  const ps = positionsOf(g);
  return ps.length > 0 && ps.every(([x, y]) => Math.abs(x) <= 180 && Math.abs(y) <= 90);
}

const fmtNum = (n: number) => (Number.isInteger(n) ? String(n) : n.toPrecision(6).replace(/\.?0+$/, ""));

/** One line about a geometry: its type, how many positions, its bounds, its SRID — what the outline is drawn from. */
export function describeGeometry(p: ParsedGeometry): string {
  const n = positionsOf(p.geometry).length;
  const b = geometryBounds(p.geometry);
  const parts = [p.geometry.type, n === 0 ? "empty" : `${n} ${n === 1 ? "position" : "positions"}`];
  if (b) parts.push(looksLikeLonLat(p.geometry)
    ? `longitude ${fmtNum(b.minX)} to ${fmtNum(b.maxX)}, latitude ${fmtNum(b.minY)} to ${fmtNum(b.maxY)}`
    : `x ${fmtNum(b.minX)} to ${fmtNum(b.maxX)}, y ${fmtNum(b.minY)} to ${fmtNum(b.maxY)}`);
  if (p.srid !== undefined) parts.push(`SRID ${p.srid}`);
  return parts.join(" · ");
}

export const ENCODING_NAMES: Record<GeometryEncoding, string> = { wkt: "WKT", geojson: "GeoJSON", "wkb-hex": "WKB (hex)" };

// ── Images ────────────────────────────────────────────────────────────────────────────────────

const IMAGE_URL = /^https?:\/\/[^\s"'<>]+\.(png|jpe?g|gif|webp|svg|avif|bmp)(\?[^\s"'<>]*)?$/i;
const IMAGE_DATA = /^data:image\/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+$/i;

export interface ImageRef { url: string; host: string | null; via: "url" | "data" }

/** An http(s) URL that names an image file, or an inline `data:image/…` — the value the viewer may load. */
export function imageRef(text: string): ImageRef | null {
  const t = text.trim();
  if (IMAGE_URL.test(t)) {
    let host: string | null = null;
    try { host = new URL(t).host || null; } catch { host = null; }
    return { url: t, host, via: "url" };
  }
  if (IMAGE_DATA.test(t)) return { url: t, host: null, via: "data" };
  return null;
}

// ── JSON ──────────────────────────────────────────────────────────────────────────────────────

/** The JSON document in a cell's text, when the text is one — an object or an array, whole. */
export function parseJsonDocument(text: string): unknown | undefined {
  const t = text.trim();
  if (!((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]")))) return undefined;
  try { return JSON.parse(t); } catch { return undefined; }
}

// ── The kind ──────────────────────────────────────────────────────────────────────────────────

export type ValueKind =
  | { kind: "null" }
  | { kind: "text" }
  | { kind: "json"; value: unknown; declared: boolean }
  | { kind: "image"; image: ImageRef }
  | { kind: "geometry"; parsed: ParsedGeometry; declared: boolean };

/**
 * What the cell holds. The value is read first; the declared type is the second witness, and the result
 * says whether the type agreed (`declared`). A column declared JSON or geometry whose value does not
 * parse as one is TEXT — the viewer then shows the text and the declared type side by side.
 */
export function classifyCell(value: Cell, declaredType?: string | null): ValueKind {
  if (value === null || value === undefined) return { kind: "null" };
  if (typeof value !== "string") return { kind: "text" };
  const kind = columnTypeKind(declaredType);
  const geometry = parseGeometry(value);
  if (geometry) return { kind: "geometry", parsed: geometry, declared: kind === "geo" };
  const image = imageRef(value);
  if (image) return { kind: "image", image };
  const doc = parseJsonDocument(value);
  if (doc !== undefined) return { kind: "json", value: doc, declared: kind === "json" };
  return { kind: "text" };
}

/** The one-line account of how the viewer read the value, for its header. */
export function describeKind(k: ValueKind, declaredType?: string | null, text?: string): string {
  const declared = declaredType ? `declared ${declaredType}` : "no declared type";
  switch (k.kind) {
    case "null": return "NULL";
    case "text": return `text · ${declared}`;
    case "json": return `JSON · ${k.declared ? declared : `read from the text, ${declared}`}`;
    case "image": return k.image.via === "data"
      ? `image · inline data, ${declared}`
      : `image URL · ${k.image.host ?? "unknown host"}, ${declared}`;
    case "geometry": return `geometry · ${ENCODING_NAMES[k.parsed.encoding]}, ${k.declared ? declared : `read from the text, ${declared}`}`;
  }
  return text ?? "";
}
