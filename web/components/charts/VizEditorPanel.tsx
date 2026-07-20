"use client";

/**
 * VizEditorPanel — the Databricks-style right-docked "Edit visualization" drawer.
 *
 * Every chart-editing control that used to sit ON the chart (metric / dimension /
 * aggregation / transform / chart-type / view / labels) lives here instead, grouped
 * into layered sections (Visualization · X axis · Y axis · Transform · Labels). The
 * chart itself renders clean, with only a hover pencil that opens this panel. Edits
 * apply live to the chart behind the drawer — no Apply button.
 *
 * It is a pure presentational component: it renders whatever the caller passes in the
 * VizEditorModel. Single-instance drawering (only one open app-wide) is handled by the
 * caller via vizEditorStore + a body portal.
 */

import { useEffect, useRef, useState } from "react";
import { BarChart3, Table2, Grid3x3, X, Download } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface VizSelectOption { v: string; t: string }

/** Everything the drawer needs to render + drive one chart's controls. The caller owns
 *  the state; the panel is stateless. `null`/empty option lists hide their section. */
export interface VizEditorModel {
  title?: string;
  // Visualization — view mode + chart type
  view: "chart" | "table" | "pivot";
  setView: (v: "chart" | "table" | "pivot") => void;
  chartAvailable: boolean;
  canPivot: boolean;
  chartTypeValue: string;
  chartTypeOptions: VizSelectOption[];   // [] → no chart-type control
  setChartType: (v: string) => void;
  // X axis
  dimValue: string;
  dimOptions: VizSelectOption[];         // [] → no X control
  setDim: (v: string) => void;
  // Y axis
  metricValue: string;
  metricOptions: VizSelectOption[];      // [] → no measure control
  setMetric: (v: string) => void;
  aggValue: string | null;               // null → hide aggregation (not meaningful)
  aggOptions: VizSelectOption[];
  setAgg: (v: string) => void;
  rateSummed: boolean;
  // Transform (post-processing)
  transformValue: string;
  transformOptions: VizSelectOption[];
  setTransform: (v: string) => void;
  transformErr?: string;
  // Labels
  showLabels: boolean;
  setShowLabels: (b: boolean) => void;
  // Color
  colorSchemeValue: string;
  colorSchemeOptions: VizSelectOption[];
  setColorScheme: (v: string) => void;
  legendValue: string;
  legendOptions: VizSelectOption[];
  setLegend: (v: string) => void;
  // Color binding — colour marks by a CHOSEN field: a dimension → discrete legend, a
  // measure → gradient legend. Scale type auto-defaults by the field's role, overridable.
  colorFieldValue: string;
  colorFieldOptions: VizSelectOption[];
  setColorField: (v: string) => void;
  colorScaleValue: "" | "continuous" | "categorical";
  setColorScale: (v: "continuous" | "categorical") => void;
  colorNameValue: string;
  setColorName: (v: string) => void;
  // Format & axis titles
  numberFormatValue: string;
  numberFormatOptions: VizSelectOption[];
  setNumberFormat: (v: string) => void;
  xTitleValue: string;
  setXTitle: (v: string) => void;
  yTitleValue: string;
  setYTitle: (v: string) => void;
  // Tooltip
  tooltipOn: boolean;
  setTooltipOn: (b: boolean) => void;
  // Annotation (reference lines)
  refLines: { label: string; value: number }[];
  addRefLine: (value: number, label: string) => void;
  addAverageLine: () => void;
  removeRefLine: (idx: number) => void;
  measureLabel: string;
  // Export
  onDownload?: (() => void) | null;
}

// ── Section + control primitives ─────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: "13px 15px", borderBottom: "1px solid var(--b1)", display: "flex", flexDirection: "column", gap: 9 }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--t3)" }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
      <span style={{ fontSize: 11.5, color: "var(--t2)", whiteSpace: "nowrap" }}>{label}</span>
      {children}
    </label>
  );
}

const SELECT_STYLE: React.CSSProperties = {
  fontSize: 11.5, color: "var(--t1)", background: "var(--bg-1)",
  border: "1px solid var(--b2)", borderRadius: "var(--r2)", padding: "4px 6px",
  outline: "none", cursor: "pointer", minWidth: 128, maxWidth: 168,
};

function Select({ value, options, onChange }: { value: string; options: VizSelectOption[]; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={SELECT_STYLE}>
      {options.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
    </select>
  );
}

const INPUT_STYLE: React.CSSProperties = {
  fontSize: 11.5, color: "var(--t1)", background: "var(--bg-1)",
  border: "1px solid var(--b2)", borderRadius: "var(--r2)", padding: "4px 6px", outline: "none",
};

function TextInput({ value, placeholder, onChange, width }: { value: string; placeholder?: string; onChange: (v: string) => void; width?: number }) {
  return (
    <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
      style={{ ...INPUT_STYLE, width: width ?? 148, maxWidth: 168 }} />
  );
}

// Annotation section owns the "add a line" input state (the panel is otherwise stateless).
function AnnotationSection({ model }: { model: VizEditorModel }) {
  const [val, setVal] = useState("");
  const [label, setLabel] = useState("");
  const add = () => {
    const n = Number(val);
    if (val && !Number.isNaN(n)) { model.addRefLine(n, label); setVal(""); setLabel(""); }
  };
  return (
    <Section title="Annotation">
      {model.refLines.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {model.refLines.map((l, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--t2)" }}>
              <span style={{ width: 12, borderTop: "1.5px dashed var(--t3)" }} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.label} · {l.value}</span>
              <Button variant="ghost" size="icon-sm" onClick={() => model.removeRefLine(i)} title="Remove" style={{ color: "var(--t4)" }}>
                <X size={13} />
              </Button>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input type="number" value={val} placeholder="value" onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") add(); }} style={{ ...INPUT_STYLE, width: 72 }} />
        <input value={label} placeholder="label" onChange={(e) => setLabel(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") add(); }} style={{ ...INPUT_STYLE, flex: 1, minWidth: 0 }} />
        <Button variant="ghost" size="xs" onClick={add} disabled={!val} style={{ color: "var(--accent)" }}>Add</Button>
      </div>
      <Button variant="ghost" size="xs" onClick={model.addAverageLine} style={{ alignSelf: "flex-start", color: "var(--t3)" }}>
        + Average of {model.measureLabel}
      </Button>
    </Section>
  );
}

/** A small on/off pill toggle, built on the Button primitive (tokens only). */
function Toggle({ on, onChange }: { on: boolean; onChange: (b: boolean) => void }) {
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={() => onChange(!on)}
      aria-pressed={on}
      className="!h-5 !w-9 !rounded-[var(--r-pill)] !p-0"
      style={{
        background: on ? "var(--accent)" : "var(--bg-3)",
        border: "1px solid " + (on ? "var(--accent)" : "var(--b2)"),
        justifyContent: on ? "flex-end" : "flex-start",
        transition: "background var(--dur-fast, .12s)",
      }}
    >
      <span style={{ width: 13, height: 13, borderRadius: "var(--r-pill)", background: on ? "var(--bg-0)" : "var(--t3)", margin: "0 2px", display: "block" }} />
    </Button>
  );
}

/** A small segmented control (Continuous | Categorical) matching the Display view toggle. */
function SegToggle<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, border: "1px solid var(--b2)", borderRadius: "var(--r2)", padding: 2 }}>
      {options.map(([v, label]) => (
        <Button
          key={v} variant="ghost" size="xs" onClick={() => onChange(v)} aria-pressed={value === v}
          style={value === v ? { background: "var(--bg-sel)", color: "var(--accent)" } : { color: "var(--t3)" }}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}

function ViewButton({ active, disabled, title, onClick, children }: {
  active: boolean; disabled?: boolean; title: string; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <Button
      variant="ghost" size="icon-sm" onClick={onClick} disabled={disabled} title={title}
      style={active ? { background: "var(--bg-sel)", color: "var(--accent)" } : { color: "var(--t3)" }}
    >
      {children}
    </Button>
  );
}

function Warn({ text }: { text: string }) {
  return <div style={{ fontSize: 10.5, color: "var(--amb4)" }}>⚠ {text}</div>;
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function VizEditorPanel({ model, onClose }: { model: VizEditorModel; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  // Escape closes; a click outside the drawer closes. The listener is attached on mount,
  // AFTER the pencil click that opened it, so that opening click never self-closes it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as globalThis.Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    // capture:false, next tick — the opening mousedown has already been dispatched.
    document.addEventListener("mousedown", onDown);
    return () => { window.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [onClose]);

  const showChartType = model.view === "chart" && model.chartTypeOptions.length > 0;
  const showFields = model.view !== "pivot";
  const chartMode = model.view === "chart" && model.chartAvailable;

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Edit visualization"
      className="animate-in slide-in-from-right-8 fade-in-0 duration-150"
      style={{
        position: "fixed", top: 0, right: 0, bottom: 0, width: "min(340px, 92vw)", zIndex: 300,
        background: "var(--bg-2)", borderLeft: "1px solid var(--b2)",
        boxShadow: "-8px 0 28px -12px rgba(0,0,0,.55)",
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 15px", borderBottom: "1px solid var(--b1)" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--t1)" }}>Edit visualization</div>
          {model.title && (
            <div style={{ fontSize: 10.5, color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 250 }} title={model.title}>
              {model.title}
            </div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
          {model.onDownload && (
            <Button variant="ghost" size="icon-sm" onClick={model.onDownload} title="Download PNG" style={{ color: "var(--t3)" }}>
              <Download size={15} />
            </Button>
          )}
          <Button variant="ghost" size="icon-sm" onClick={onClose} title="Close" style={{ color: "var(--t3)" }}>
            <X size={16} />
          </Button>
        </div>
      </div>

      {/* Sections */}
      <div style={{ overflowY: "auto", flex: 1 }}>
        <Section title="Visualization">
          <Row label="Display">
            <div style={{ display: "flex", alignItems: "center", gap: 2, border: "1px solid var(--b2)", borderRadius: "var(--r2)", padding: 2 }}>
              <ViewButton active={model.view === "chart"} disabled={!model.chartAvailable} title="Chart" onClick={() => model.setView("chart")}>
                <BarChart3 size={14} />
              </ViewButton>
              <ViewButton active={model.view === "table"} title="Table" onClick={() => model.setView("table")}>
                <Table2 size={14} />
              </ViewButton>
              <ViewButton active={model.view === "pivot"} disabled={!model.canPivot} title="Pivot (cross-tab)" onClick={() => model.setView("pivot")}>
                <Grid3x3 size={14} />
              </ViewButton>
            </div>
          </Row>
          {showChartType && (
            <Row label="Chart type">
              <Select value={model.chartTypeValue} options={model.chartTypeOptions} onChange={model.setChartType} />
            </Row>
          )}
        </Section>

        {showFields && model.dimOptions.length > 0 && (
          <Section title="X axis">
            <Row label="Field"><Select value={model.dimValue} options={model.dimOptions} onChange={model.setDim} /></Row>
            {chartMode && <Row label="Axis title"><TextInput value={model.xTitleValue} placeholder="auto" onChange={model.setXTitle} /></Row>}
          </Section>
        )}

        {showFields && model.metricOptions.length > 0 && (
          <Section title="Y axis">
            <Row label="Measure"><Select value={model.metricValue} options={model.metricOptions} onChange={model.setMetric} /></Row>
            {model.aggValue != null && (
              <Row label="Aggregation"><Select value={model.aggValue} options={model.aggOptions} onChange={model.setAgg} /></Row>
            )}
            {model.rateSummed && <Warn text="summing a rate — AVG is the grain-correct aggregate" />}
            {chartMode && <Row label="Number format"><Select value={model.numberFormatValue} options={model.numberFormatOptions} onChange={model.setNumberFormat} /></Row>}
            {chartMode && <Row label="Axis title"><TextInput value={model.yTitleValue} placeholder="auto" onChange={model.setYTitle} /></Row>}
          </Section>
        )}

        {showFields && model.transformOptions.length > 0 && (
          <Section title="Transform">
            <Row label="Compute"><Select value={model.transformValue} options={model.transformOptions} onChange={model.setTransform} /></Row>
            {model.transformErr && <Warn text="transform not available for this shape" />}
          </Section>
        )}

        {chartMode && (
          <Section title="Color">
            {model.colorFieldOptions.length > 1 && (
              <Row label="Color by"><Select value={model.colorFieldValue} options={model.colorFieldOptions} onChange={model.setColorField} /></Row>
            )}
            {model.colorFieldValue && (
              <>
                <Row label="Scale type">
                  <SegToggle
                    value={model.colorScaleValue || "categorical"}
                    onChange={model.setColorScale}
                    options={[["continuous", "Continuous"], ["categorical", "Categorical"]]}
                  />
                </Row>
                <Row label="Display name"><TextInput value={model.colorNameValue} placeholder="auto" onChange={model.setColorName} /></Row>
              </>
            )}
            <Row label="Scheme"><Select value={model.colorSchemeValue} options={model.colorSchemeOptions} onChange={model.setColorScheme} /></Row>
            <Row label="Legend"><Select value={model.legendValue} options={model.legendOptions} onChange={model.setLegend} /></Row>
          </Section>
        )}

        {chartMode && (
          <Section title="Labels">
            <Row label="Show data labels"><Toggle on={model.showLabels} onChange={model.setShowLabels} /></Row>
          </Section>
        )}

        {chartMode && (
          <Section title="Tooltip">
            <Row label="Show on hover"><Toggle on={model.tooltipOn} onChange={model.setTooltipOn} /></Row>
          </Section>
        )}

        {chartMode && <AnnotationSection model={model} />}
      </div>
    </div>
  );
}
