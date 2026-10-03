"use client";

/**
 * DE-5e — a geometry drawn to its OWN bounds: the shape, not a map. There is no base map here on
 * purpose: tiles would phone a tile server from a cell's value, and a projection would claim to
 * know what the numbers mean. The caption beside this outline says the bounds and whether the
 * positions fit longitude/latitude; the outline shows the shape at the scale its own extent gives it.
 *
 * Points are dots, lines are polylines, polygons are closed paths with a light fill. Extra
 * dimensions (Z, M) are read and ignored for drawing.
 */
import { geometryBounds, type GeoJsonGeometry, type Position } from "@/lib/query/cellKind";

const PAD = 8;

export function GeometryOutline({ geometry, width = 300, height = 150 }: {
  geometry: GeoJsonGeometry; width?: number; height?: number;
}) {
  const b = geometryBounds(geometry);
  if (!b) {
    return (
      <div className="aug-fs-xs" data-testid="geometry-outline-empty" style={{ color: "var(--t3)", padding: "8px 0" }}>
        An empty geometry — nothing to draw.
      </div>
    );
  }
  const spanX = b.maxX - b.minX || 1;
  const spanY = b.maxY - b.minY || 1;
  const scale = Math.min((width - 2 * PAD) / spanX, (height - 2 * PAD) / spanY);
  const drawnW = spanX * scale, drawnH = spanY * scale;
  const offX = (width - drawnW) / 2, offY = (height - drawnH) / 2;
  // SVG's y grows downward; a map's grows upward.
  const px = ([x, y]: Position) => [offX + (x - b.minX) * scale, offY + (b.maxY - y) * scale] as const;
  const path = (ring: Position[], close: boolean) =>
    ring.map((p, i) => { const [x, y] = px(p); return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`; }).join(" ") + (close ? " Z" : "");

  const marks: React.ReactNode[] = [];
  let k = 0;
  const dot = (p: Position) => { const [x, y] = px(p); marks.push(<circle key={k++} cx={x} cy={y} r={3.5} fill="currentColor" />); };
  const line = (ps: Position[]) => marks.push(<path key={k++} d={path(ps, false)} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />);
  const polygon = (rings: Position[][]) => marks.push(
    <path key={k++} d={rings.map(r => path(r, true)).join(" ")} fill="currentColor" fillOpacity={0.12} fillRule="evenodd"
      stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />);
  const draw = (g: GeoJsonGeometry) => {
    switch (g.type) {
      case "Point": if (g.coordinates.length) dot(g.coordinates); break;
      case "MultiPoint": g.coordinates.forEach(dot); break;
      case "LineString": line(g.coordinates); break;
      case "MultiLineString": g.coordinates.forEach(line); break;
      case "Polygon": polygon(g.coordinates); break;
      case "MultiPolygon": g.coordinates.forEach(polygon); break;
      case "GeometryCollection": g.geometries.forEach(draw); break;
    }
  };
  draw(geometry);

  return (
    <svg data-testid="geometry-outline" width={width} height={height} viewBox={`0 0 ${width} ${height}`}
      role="img" aria-label={`${geometry.type} drawn to its own bounds`}
      style={{ color: "var(--t2)", background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r1)", flexShrink: 0 }}>
      {marks}
    </svg>
  );
}
