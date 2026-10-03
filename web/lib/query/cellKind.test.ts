/**
 * DE-5e (ROADMAP §3.51) — what a cell's value is, read strictly: a WKT must parse to its end, a WKB
 * must consume every byte, a JSON document must be whole. The engines return geometry three ways
 * (BigQuery WKT, Snowflake GeoJSON, Postgres hex EWKB, MySQL SRID-prefixed WKB) and the kind is read
 * from the value, with the declared type as the second witness.
 */
import { describe, expect, it } from "vitest";
import {
  classifyCell, describeGeometry, describeKind, geometryBounds, imageRef, looksLikeLonLat,
  parseGeometry, parseJsonDocument, parseWkbHex, parseWkt, positionsOf,
} from "./cellKind";

/** A little-endian WKB double, as hex. */
function le(n: number): string {
  const b = new ArrayBuffer(8);
  new DataView(b).setFloat64(0, n, true);
  return Array.from(new Uint8Array(b), x => x.toString(16).padStart(2, "0")).join("");
}
const u32 = (n: number) => { const b = new ArrayBuffer(4); new DataView(b).setUint32(0, n, true); return Array.from(new Uint8Array(b), x => x.toString(16).padStart(2, "0")).join(""); };
const POINT_1_2 = "01" + u32(1) + le(1) + le(2);                       // POINT (1 2), little-endian
const EWKB_4326 = "01" + u32(0x20000001) + u32(4326) + le(1) + le(2);  // PostGIS: the SRID flag, then the SRID
const MYSQL = u32(4326) + POINT_1_2;                                  // MySQL: a 4-byte SRID before the WKB
const SQUARE = "01" + u32(3) + u32(1) + u32(5) + [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]].map(([x, y]) => le(x) + le(y)).join("");

describe("WKT", () => {
  it("parses the seven types, Z/M suffixes, EMPTY and an SRID prefix", () => {
    expect(parseWkt("POINT (4.9 52.37)")).toEqual({ geometry: { type: "Point", coordinates: [4.9, 52.37] }, encoding: "wkt", srid: undefined });
    expect(parseWkt("SRID=4326;POINT Z (1 2 3)")?.srid).toBe(4326);
    expect(parseWkt("POINT Z (1 2 3)")?.geometry).toEqual({ type: "Point", coordinates: [1, 2, 3] });
    expect(parseWkt("LINESTRING (0 0, 1 1, 2 0)")?.geometry.type).toBe("LineString");
    expect(parseWkt("POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0), (0.2 0.2, 0.4 0.2, 0.4 0.4, 0.2 0.2))")?.geometry)
      .toMatchObject({ type: "Polygon", coordinates: [expect.any(Array), expect.any(Array)] });
    expect(parseWkt("MULTIPOINT ((1 2), (3 4))")?.geometry).toEqual({ type: "MultiPoint", coordinates: [[1, 2], [3, 4]] });
    expect(parseWkt("MULTIPOINT (1 2, 3 4)")?.geometry).toEqual({ type: "MultiPoint", coordinates: [[1, 2], [3, 4]] });
    expect(parseWkt("MULTILINESTRING ((0 0, 1 1), (2 2, 3 3))")?.geometry.type).toBe("MultiLineString");
    expect(parseWkt("MULTIPOLYGON (((0 0, 1 0, 1 1, 0 0)), ((5 5, 6 5, 6 6, 5 5)))")?.geometry.type).toBe("MultiPolygon");
    expect(parseWkt("GEOMETRYCOLLECTION (POINT (1 2), LINESTRING (0 0, 1 1))")?.geometry)
      .toMatchObject({ type: "GeometryCollection", geometries: [{ type: "Point" }, { type: "LineString" }] });
    expect(parseWkt("POLYGON EMPTY")?.geometry).toEqual({ type: "Polygon", coordinates: [] });
    expect(parseWkt("point(1e3 -2.5)")?.geometry).toEqual({ type: "Point", coordinates: [1000, -2.5] });
  });

  it("refuses text that only starts like WKT", () => {
    expect(parseWkt("POINT (1 2) and then some")).toBeNull();
    expect(parseWkt("POINT (1)")).toBeNull();
    expect(parseWkt("POINTER (1 2)")).toBeNull();
    expect(parseWkt("Pointe-à-Pitre")).toBeNull();
  });
});

describe("WKB as hex", () => {
  it("reads plain WKB, PostGIS EWKB with its SRID, and MySQL's SRID-prefixed form", () => {
    expect(parseWkbHex(POINT_1_2)).toEqual({ geometry: { type: "Point", coordinates: [1, 2] }, encoding: "wkb-hex", srid: undefined });
    expect(parseWkbHex(EWKB_4326)).toEqual({ geometry: { type: "Point", coordinates: [1, 2] }, encoding: "wkb-hex", srid: 4326 });
    expect(parseWkbHex(MYSQL)).toEqual({ geometry: { type: "Point", coordinates: [1, 2] }, encoding: "wkb-hex", srid: 4326 });
    expect(parseWkbHex(SQUARE)?.geometry).toEqual({ type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] });
    expect(parseWkbHex(POINT_1_2.toUpperCase())?.geometry.type).toBe("Point");
  });

  it("never mistakes a hex id for a shape: every byte must be consumed", () => {
    expect(parseWkbHex("5d41402abc4b2a76b9719d911017c592")).toBeNull();                 // an md5
    expect(parseWkbHex(POINT_1_2 + "00")).toBeNull();                                    // a byte too many
    expect(parseWkbHex("0101000000000000000000f03f00000000000000400000000000000000000000000000000000000000000000")).toBeNull(); // a sha256-length string that starts like a point
    expect(parseWkbHex("01" + u32(99) + le(1) + le(2))).toBeNull();                      // an unknown type code
    expect(parseWkbHex("not hex at all, not hex at all, not hex at all!")).toBeNull();
  });
});

describe("GeoJSON and the one entry point", () => {
  it("reads a GeoJSON geometry or Feature, and tells the three encodings apart", () => {
    const gj = parseGeometry('{"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}');
    expect(gj?.encoding).toBe("geojson");
    expect(parseGeometry('{"type":"Feature","geometry":{"type":"Point","coordinates":[1,2]},"properties":{}}')?.geometry)
      .toEqual({ type: "Point", coordinates: [1, 2] });
    expect(parseGeometry("POINT (1 2)")?.encoding).toBe("wkt");
    expect(parseGeometry(POINT_1_2)?.encoding).toBe("wkb-hex");
    expect(parseGeometry('{"type": "Point"}')).toBeNull();           // no coordinates
    expect(parseGeometry('{"a": 1}')).toBeNull();
    expect(parseGeometry("")).toBeNull();
  });

  it("knows a geometry's positions, bounds and whether they fit longitude and latitude", () => {
    const sq = parseWkbHex(SQUARE)!.geometry;
    expect(positionsOf(sq)).toHaveLength(5);
    expect(geometryBounds(sq)).toEqual({ minX: 0, minY: 0, maxX: 1, maxY: 1 });
    expect(looksLikeLonLat(sq)).toBe(true);
    expect(looksLikeLonLat(parseWkt("POINT (500000 4649776)")!.geometry)).toBe(false);
    expect(geometryBounds(parseWkt("POINT EMPTY")!.geometry)).toBeNull();
  });

  it("describes a geometry in one line", () => {
    expect(describeGeometry(parseWkt("SRID=4326;POINT (4.9 52.37)")!))
      .toBe("Point · 1 position · longitude 4.9 to 4.9, latitude 52.37 to 52.37 · SRID 4326");
    expect(describeGeometry(parseWkt("POINT (500000 4649776)")!))
      .toBe("Point · 1 position · x 500000 to 500000, y 4649776 to 4649776");
    expect(describeGeometry(parseWkt("LINESTRING EMPTY")!)).toBe("LineString · empty");
  });
});

describe("images and JSON", () => {
  it("names an image URL by its host and an inline image by its data", () => {
    expect(imageRef("https://img.example.com/cat.png")).toEqual({ url: "https://img.example.com/cat.png", host: "img.example.com", via: "url" });
    expect(imageRef("http://x.test/a/b.JPEG?size=large")?.via).toBe("url");
    expect(imageRef("data:image/png;base64,iVBORw0KGgo=")).toEqual({ url: "data:image/png;base64,iVBORw0KGgo=", host: null, via: "data" });
    expect(imageRef("https://example.com/report.pdf")).toBeNull();
    expect(imageRef("https://example.com/cat.png and more")).toBeNull();
    expect(imageRef("cat.png")).toBeNull();
  });

  it("reads a whole JSON document and nothing less", () => {
    expect(parseJsonDocument('{"a": [1, 2]}')).toEqual({ a: [1, 2] });
    expect(parseJsonDocument("[1, 2]")).toEqual([1, 2]);
    expect(parseJsonDocument("{not json")).toBeUndefined();
    expect(parseJsonDocument("42")).toBeUndefined();
  });
});

describe("the kind, and how it is said", () => {
  it("reads the value first and lets the declared type be the second witness", () => {
    expect(classifyCell(null, "JSON")).toEqual({ kind: "null" });
    expect(classifyCell(12, "BIGINT")).toEqual({ kind: "text" });
    expect(classifyCell("hello", "VARCHAR")).toEqual({ kind: "text" });
    expect(classifyCell('{"a": 1}', "JSON")).toMatchObject({ kind: "json", declared: true });
    expect(classifyCell('{"a": 1}', "VARCHAR")).toMatchObject({ kind: "json", declared: false });
    expect(classifyCell("POINT (1 2)", "GEOGRAPHY")).toMatchObject({ kind: "geometry", declared: true });
    expect(classifyCell("POINT (1 2)", "VARCHAR")).toMatchObject({ kind: "geometry", declared: false });
    expect(classifyCell(POINT_1_2, "BLOB")).toMatchObject({ kind: "geometry", declared: false });
    expect(classifyCell("https://img.example.com/cat.png", "VARCHAR")).toMatchObject({ kind: "image" });
    // A column declared JSON whose value is not a document is text — and the header will say both.
    expect(classifyCell("not a document", "JSON")).toEqual({ kind: "text" });
  });

  it("says how it read the value", () => {
    expect(describeKind(classifyCell('{"a": 1}', "JSON"), "JSON")).toBe("JSON · declared JSON");
    expect(describeKind(classifyCell('{"a": 1}', "VARCHAR"), "VARCHAR")).toBe("JSON · read from the text, declared VARCHAR");
    expect(describeKind(classifyCell("POINT (1 2)", "VARCHAR"), "VARCHAR")).toBe("geometry · WKT, read from the text, declared VARCHAR");
    expect(describeKind(classifyCell(EWKB_4326, "GEOMETRY"), "GEOMETRY")).toBe("geometry · WKB (hex), declared GEOMETRY");
    expect(describeKind(classifyCell("https://img.example.com/cat.png", null), null)).toBe("image URL · img.example.com, no declared type");
    expect(describeKind(classifyCell("hello", "VARCHAR"), "VARCHAR")).toBe("text · declared VARCHAR");
    expect(describeKind(classifyCell(null, "VARCHAR"), "VARCHAR")).toBe("NULL");
  });
});
