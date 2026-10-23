"use client";

/**
 * Starting a cockpit from an object (2026-10-10) — the first view of design-mockups/cockpit-from-object.html, which the
 * user approved as "absolute perfection". The server proposes what the object holds, each piece with a preview it
 * measured (`GET /cockpits/from-object`); the person ticks what they want; the cockpit is kept as their own first
 * version, with no model asked. Drawn inside New cockpit and in a dialog from the Ontology tab's object panel.
 */
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon, type IconName } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import { toast } from "@/components/ui/toast";
import { getCockpitFromObject, type CockpitFromObject, type ShapeName } from "@/lib/api";
import { figureText } from "@/lib/cockpit/objectView";
import { SHAPES, shapeHolds, shapeSpec } from "@/lib/cockpit/shapes";
import { everything, holdsAPiece, objectCockpitSpec, startCockpit, type ObjectCockpitChoice } from "@/lib/cockpit/start";
import { formatCount } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";

const ROW = "18px 18px minmax(0, 1fr) 150px 230px";

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em", margin: "4px 0" }}>{label}</div>
      {children}
    </div>
  );
}

function Row({ on, onChange, icon, name, via, code, preview, testid }: {
  on: boolean; onChange: (on: boolean) => void; icon: IconName; name: string; via?: string; code: string;
  preview: ReactNode; testid: string;
}) {
  return (
    <label data-testid={testid} className="aug-fs-sm" style={{
      display: "grid", gridTemplateColumns: ROW, alignItems: "center", gap: 8, padding: "6px 8px", marginBottom: 3,
      borderRadius: "var(--r2)", background: "var(--bg-0)", cursor: "pointer", color: "var(--t1)" }}>
      <Checkbox checked={on} aria-label={name} onChange={e => onChange(e.target.checked)} />
      <Icon name={icon} size={15} />
      <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {name}{via && <span className="aug-fs-xs" style={{ color: "var(--vio4)", marginLeft: 6 }}>via {via}</span>}
      </span>
      <code className="aug-fs-xs" style={{ color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{code}</code>
      <span style={{ justifySelf: "end", minWidth: 0 }}>{preview}</span>
    </label>
  );
}

/** A category's values as a small run of bars, tallest first. */
function MiniBars({ values }: { values: number[] }) {
  const top = Math.max(1, ...values);
  return (
    <span aria-hidden="true" style={{ display: "inline-flex", alignItems: "flex-end", gap: 2, height: 18 }}>
      {values.map((v, i) => (
        <i key={i} style={{ width: 7, height: Math.max(2, (v / top) * 18), borderRadius: "2px 2px 0 0", background: "var(--chart-1)" }} />
      ))}
    </span>
  );
}

/** The objects per day, drawn small in the de-emphasis grey. */
function MiniDays({ bars }: { bars: number[] }) {
  const top = Math.max(1, ...bars);
  const w = 96 / Math.max(1, bars.length);
  return (
    <svg width="96" height="22" viewBox="0 0 96 22" aria-hidden="true">
      {bars.map((v, i) => {
        const h = Math.max(1, (v / top) * 22);
        return <rect key={i} x={i * w} y={22 - h} width={Math.max(1, w - 1)} height={h} rx={1} fill="var(--chart-deemph)" />;
      })}
    </svg>
  );
}

const set = <T,>(list: T[], item: T, on: boolean): T[] => (on ? [...new Set([...list, item])] : list.filter(x => x !== item));

export function ObjectCockpitStarter({ connectionId, schema, entity, sym = "$", onKept, onCancel }: {
  connectionId: string; schema?: string; entity: string; sym?: string;
  onKept: (cockpitId: string) => void; onCancel: () => void;
}) {
  const [proposal, setProposal] = useState<CockpitFromObject | null>(null);
  const [problem, setProblem] = useState("");
  const [choice, setChoice] = useState<ObjectCockpitChoice | null>(null);
  const [starting, setStarting] = useState(false);
  // Arc AP-5 — the shape chosen (the best fit, until a person picks another) and the days a queue looks back over
  const [shape, setShape] = useState<ShapeName>("overview");
  const [windowDays, setWindowDays] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    setProposal(null); setProblem("");
    getCockpitFromObject(connectionId, entity, schema)
      .then(p => { if (alive) { setProposal(p); setChoice(everything(p)); setShape(p.shapes?.[0]?.shape ?? "overview"); setWindowDays(null); } })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [connectionId, entity, schema]);

  if (problem) {
    return <div className="aug-fs-sm" data-testid="object-starter-problem" style={{ color: "var(--t2)" }}>{problem}</div>;
  }
  if (!proposal || !choice) {
    return <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading {entity} — each piece is measured before it is offered…</div>;
  }
  const p = proposal;
  const noun = p.title.toLowerCase();
  const create = async () => {
    setStarting(true);
    try {
      // while shapes are offered, an overview says it is one: a shape's cockpits are read against each other's
      onKept(await startCockpit(connectionId, p.title, objectCockpitSpec(p, choice),
        `Started from the object ${p.name}${p.shapes?.length ? " as an overview" : ""}`));
    } catch (e) {
      toast.error("The dashboard was not made", { description: (e as Error).message.slice(0, 200) });
    } finally { setStarting(false); }
  };
  const ready = holdsAPiece(choice, p);
  const offered = p.shapes ?? [];
  const shaped = offered.length > 0 && shape !== "overview";
  const sized = p.signals ? { ...p, signals: { ...p.signals, window: windowDays ?? p.signals.window } } : p;
  const holds = shaped ? shapeHolds(shape, sized) : [];
  const make = async () => {
    const spec = shapeSpec(shape, sized) as { elements: { cockpit: { props: { title: string } } } } | null;
    if (!spec) return;
    setStarting(true);
    try {
      const label = SHAPES[shape].label.toLowerCase();
      onKept(await startCockpit(connectionId, spec.elements.cockpit.props.title, spec,
        `Started from the object ${p.name} as ${/^[aeiou]/.test(label) ? "an" : "a"} ${label}`));
    } catch (e) {
      toast.error("The dashboard was not made", { description: (e as Error).message.slice(0, 200) });
    } finally { setStarting(false); }
  };
  const why = offered.find(o => o.shape === shape)?.why;
  const q = p.signals?.queue;
  return (
    <div data-testid="object-starter">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>New dashboard from {p.name}</div>
        {p.total != null && (
          <span className="aug-fs-xs" style={{ color: "var(--t2)", background: "var(--bg-3)", border: "1px solid var(--b1)",
            borderRadius: "var(--r-chip)", padding: "2px 7px" }}>{formatCount(p.total)} {noun}</span>
        )}
      </div>
      <p className="aug-fs-sm" style={{ margin: "6px 0 12px", color: "var(--t2)" }}>
        {offered.length ? "The shape follows what the ontology holds. Every piece can be changed after."
          : <>Picked from {p.name}&apos;s properties. Every piece reads the same {noun}, so a click in one narrows the rest.</>}
      </p>

      {offered.length > 0 && (
        <>
          <div role="radiogroup" aria-label="Shape" data-testid="object-starter-shapes"
            style={{ display: "grid", gridTemplateColumns: `repeat(${offered.length}, minmax(0, 1fr))`, gap: 8, marginBottom: 10 }}>
            {withUniqueKeys(offered, o => o.shape).map(([k, o], i) => (
              <Button key={k} variant="outline" role="radio" aria-checked={shape === o.shape} data-testid="object-starter-shape" data-shape={o.shape}
                onClick={() => setShape(o.shape)}
                style={{ height: "auto", justifyContent: "flex-start", textAlign: "left", whiteSpace: "normal", padding: "10px 12px",
                  background: shape === o.shape ? "var(--bg-sel)" : undefined, borderColor: shape === o.shape ? "var(--accent)" : undefined }}>
                <span style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
                  <span style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                    <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600 }}>{SHAPES[o.shape].label}</span>
                    {i === 0 && <span className="aug-fs-xs" style={{ color: "var(--accent-11)" }}>fits best</span>}
                  </span>
                  <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{SHAPES[o.shape].says}</span>
                </span>
              </Button>
            ))}
          </div>
          {why && (
            <p className="aug-fs-sm" data-testid="object-starter-why" style={{ margin: "0 0 12px", color: "var(--t2)" }}>
              <b style={{ color: "var(--t1)", fontWeight: 500 }}>Why {SHAPES[shape].label.toLowerCase()}:</b> {why}
            </p>
          )}
        </>
      )}

      {shaped && shape === "queue" && q?.kind === "promise" && p.signals && (
        <Group label={`Which ${noun} wait`}>
          <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t2)" }}>
            Past the {q.noun.replace(/_/g, " ")} promise, placed in the last
            <Segmented label="Days" value={String(windowDays ?? p.signals.window)}
              options={[7, 14, 30].map(d => ({ value: String(d), label: `${d} days` }))} onChange={v => setWindowDays(Number(v))} />
          </div>
        </Group>
      )}
      {shaped && (
        <Group label="It holds">
          <ul data-testid="object-starter-holds" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 3 }}>
            {withUniqueKeys(holds, line => line).map(([k, line]) => (
              <li key={k} className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "6px 8px",
                borderRadius: "var(--r2)", background: "var(--bg-0)", color: "var(--t1)" }}>
                <Icon name="check" size={13} />{line}
              </li>
            ))}
          </ul>
        </Group>
      )}

      {!shaped && p.filters.length > 0 && (
        <Group label="Filters · its categories">
          {withUniqueKeys(p.filters, f => f.path).map(([k, f]) => (
            <Row key={k} testid="object-starter-filter" on={choice.filters.includes(f.path)} icon="filter" name={f.label}
              via={f.via || undefined} code={f.path} preview={<MiniBars values={f.values.map(v => v[1] ?? 0)} />}
              onChange={on => setChoice({ ...choice, filters: set(choice.filters, f.path, on) })} />
          ))}
        </Group>
      )}
      {!shaped && p.figures.length > 0 && (
        <Group label="Figures · its numbers">
          {p.figures.map((f, i) => (
            <Row key={`${f.agg}-${f.path}`} testid="object-starter-figure" on={choice.figures.includes(i)} icon="metric" name={f.label}
              code={f.path ? `${f.agg} of ${f.path}` : "count"}
              preview={<b style={{ fontVariantNumeric: "tabular-nums" }}>{figureText(f.value, f.agg, f.format, sym)}</b>}
              onChange={on => setChoice({ ...choice, figures: set(choice.figures, i, on) })} />
          ))}
        </Group>
      )}
      {!shaped && p.chart && (
        <Group label="Chart · its dates">
          <Row testid="object-starter-chart" on={choice.chart} icon="chart" name={p.chart.label} code={p.chart.time}
            preview={<MiniDays bars={p.chart.bars} />} onChange={on => setChoice({ ...choice, chart: on })} />
        </Group>
      )}
      {!shaped && <Group label={p.actions.length ? "Table and actions" : "Table"}>
        {p.listable === false ? (
          <div className="aug-fs-sm" data-testid="object-starter-unlisted" style={{ padding: "6px 8px", color: "var(--t3)" }}>
            {p.name} declares no key, so its objects are counted and charted here, never listed one by one.
          </div>
        ) : (
          <Row testid="object-starter-table" on={choice.table} icon="table" name={p.title}
            code={`${p.table.columns.length} columns`}
            preview={<span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{p.table.labels.join(" · ").toLowerCase()}</span>}
            onChange={on => setChoice({ ...choice, table: on })} />
        )}
        {p.listable !== false && p.actions.map(a => (
          <Row key={a.id} testid="object-starter-action" on={choice.table && choice.actions.includes(a.id)} icon="bolt" name={a.label}
            code={`declared on ${p.name}`}
            preview={<span className="aug-fs-xs" style={{ color: "var(--t3)" }}>runs on the chosen {p.name.toLowerCase()}</span>}
            onChange={on => setChoice({ ...choice, table: choice.table || on, actions: set(choice.actions, a.id, on) })} />
        ))}
      </Group>}

      {p.caveats.length > 0 && (
        <div className="aug-fs-xs" data-testid="object-starter-caveats" style={{ color: "var(--t3)", margin: "4px 0 0" }}>
          {p.caveats.map(c => <div key={c}>{c}</div>)}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14 }}>
        <span className="aug-fs-sm" style={{ color: "var(--t3)", marginRight: "auto" }}>
          {shaped ? "Nothing is kept until you press Make it."
            : ready ? "Opens in the Dashboards tab. Move, resize or remove any piece." : "Tick a figure, the chart or the table — filters alone narrow nothing."}
        </span>
        <Button size="sm" variant="ghost" disabled={starting} onClick={onCancel}>Cancel</Button>
        <Button size="sm" data-testid="object-starter-create" disabled={(!shaped && !ready) || starting} onClick={() => void (shaped ? make() : create())}>
          {starting ? "Creating…" : offered.length ? "Make it" : "Create dashboard"}
        </Button>
      </div>
    </div>
  );
}
