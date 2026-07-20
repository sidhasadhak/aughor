"use client";

/**
 * VizEditorPanel — the Databricks-style right-docked "Edit visualization" drawer.
 *
 * Structured as ENCODING CHANNELS (Visualization · X axis · Y axis · Color) plus a few
 * mark/reference sections (Labels · Tooltip · Transform · Annotation). Each channel shows its
 * FIELD as one clean dropdown; rarely-touched formatting (axis title, number format, the
 * reference-line editor) hides behind a per-section options toggle, so the default view is a
 * short, scannable list. Table + Pivot fold into the single Visualization dropdown. Every
 * control is the app's design-system Select/Input (Base UI), not a native element.
 *
 * It is a pure presentational component: it renders whatever the caller passes in the
 * VizEditorModel. Single-instance drawering is handled by the caller (vizEditorStore + portal).
 */

import { useEffect, useRef, useState } from "react";
import { Minus, X, Download, BarChart3, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select as UiSelect, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface VizSelectOption { v: string; t: string }

/** Everything the drawer needs to render + drive one chart's controls. The caller owns
 *  the state; the panel is stateless. `null`/empty option lists hide their section. */
export interface VizEditorModel {
  title?: string;
  // Visualization — view mode + chart type (folded into one dropdown here)
  view: "chart" | "table" | "pivot";
  setView: (v: "chart" | "table" | "pivot") => void;
  chartAvailable: boolean;
  canPivot: boolean;
  chartTypeValue: string;
  chartTypeOptions: VizSelectOption[];   // [] → not chartable (Table/Pivot only)
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
  // Color binding — colour marks by a CHOSEN field: a dimension → discrete legend, a
  // measure → gradient legend. Scale type auto-defaults by the field's role, overridable.
  colorFieldValue: string;
  colorFieldOptions: VizSelectOption[];
  setColorField: (v: string) => void;
  colorScaleValue: "" | "continuous" | "categorical";
  setColorScale: (v: "continuous" | "categorical") => void;
  colorNameValue: string;
  setColorName: (v: string) => void;
  legendValue: string;
  legendOptions: VizSelectOption[];
  setLegend: (v: string) => void;
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

// ── primitives ────────────────────────────────────────────────────────────────

const SECTION_LABEL: React.CSSProperties = { fontSize: 12.5, fontWeight: 600, color: "var(--t2)" };

/** The app's design-system dropdown (Base UI), wrapped to the panel's {value, options, onChange}
 *  API. Portals its menu to <body> — the drawer's outside-click handler guards for that. */
function Select({ value, options, onChange, leading }: {
  value: string; options: VizSelectOption[]; onChange: (v: string) => void; leading?: React.ReactNode;
}) {
  const items = Object.fromEntries(options.map((o) => [o.v, o.t]));
  return (
    <UiSelect value={value} onValueChange={(v) => onChange((v ?? "") as string)} items={items}>
      <SelectTrigger className="w-full">
        {leading}
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => <SelectItem key={o.v} value={o.v}>{o.t}</SelectItem>)}
      </SelectContent>
    </UiSelect>
  );
}

function TextInput({ value, placeholder, onChange }: { value: string; placeholder?: string; onChange: (v: string) => void }) {
  return <Input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />;
}

/** A label above its control (the stacked layout the sections use). */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span style={{ fontSize: 11, fontWeight: 500, color: "var(--t3)" }}>{label}</span>
      {children}
    </label>
  );
}

/** A plain titled section (the Visualization dropdown). */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--b1)", display: "flex", flexDirection: "column", gap: 9 }}>
      <div style={SECTION_LABEL}>{title}</div>
      {children}
    </div>
  );
}

/** An encoding channel: a header (with optional options-toggle + remove), a primary control,
 *  and a collapsible `more` block for rarely-touched formatting. */
function Channel({ title, onRemove, more, children }: {
  title: string; onRemove?: (() => void) | null; more?: React.ReactNode; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--b1)", display: "flex", flexDirection: "column", gap: 9 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4, minHeight: 20 }}>
        <span style={SECTION_LABEL}>{title}</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 1 }}>
          {more && (
            <Button variant="ghost" size="icon-sm" onClick={() => setOpen((o) => !o)} title="More options"
              style={{ color: open ? "var(--accent)" : "var(--t4)" }}>
              <SlidersHorizontal size={13} />
            </Button>
          )}
          {onRemove && (
            <Button variant="ghost" size="icon-sm" onClick={onRemove} title="Remove" style={{ color: "var(--t4)" }}>
              <Minus size={14} />
            </Button>
          )}
        </div>
      </div>
      {children}
      {more && open && <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>{more}</div>}
    </div>
  );
}

/** A single-toggle row that reads as a section header (Labels / Tooltip). */
function ToggleRow({ title, on, onChange }: { title: string; on: boolean; onChange: (b: boolean) => void }) {
  return (
    <div style={{ padding: "13px 16px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <span style={SECTION_LABEL}>{title}</span>
      <Toggle on={on} onChange={onChange} />
    </div>
  );
}

/** A small on/off pill toggle, built on the Button primitive (tokens only). */
function Toggle({ on, onChange }: { on: boolean; onChange: (b: boolean) => void }) {
  return (
    <Button
      variant="ghost" size="icon-sm" onClick={() => onChange(!on)} aria-pressed={on}
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

/** A segmented control (Categorical | Continuous). */
function SegToggle<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 3, border: "1px solid var(--b2)", borderRadius: "var(--r2)", padding: 3, alignSelf: "flex-start", background: "var(--bg-1)" }}>
      {options.map(([v, label]) => {
        const on = value === v;
        return (
          <Button key={v} variant="ghost" size="xs" onClick={() => onChange(v)} aria-pressed={on}
            className="!h-6 !px-2.5 !rounded-[var(--r2)] !font-medium"
            style={on ? { background: "var(--bg-sel)", color: "var(--accent)" } : { color: "var(--t3)" }}>
            {label}
          </Button>
        );
      })}
    </div>
  );
}

function Warn({ text }: { text: string }) {
  return <div style={{ fontSize: 10.5, color: "var(--amb4)" }}>⚠ {text}</div>;
}

// Annotation channel owns the "add a line" input state (the panel is otherwise stateless).
function AnnotationSection({ model }: { model: VizEditorModel }) {
  const [val, setVal] = useState("");
  const [label, setLabel] = useState("");
  const add = () => {
    const n = Number(val);
    if (val && !Number.isNaN(n)) { model.addRefLine(n, label); setVal(""); setLabel(""); }
  };
  const more = (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Input type="number" value={val} placeholder="value" className="w-[76px]"
          onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
        <Input value={label} placeholder="label" className="flex-1 min-w-0"
          onChange={(e) => setLabel(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
        <Button variant="ghost" size="xs" onClick={add} disabled={!val} style={{ color: "var(--accent)" }}>Add</Button>
      </div>
      <Button variant="ghost" size="xs" onClick={model.addAverageLine} style={{ alignSelf: "flex-start", color: "var(--t3)" }}>
        + Average of {model.measureLabel}
      </Button>
    </>
  );
  return (
    <Channel title="Annotation" more={more}>
      {model.refLines.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {model.refLines.map((l, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--t2)" }}>
              <span style={{ width: 12, borderTop: "1.5px dashed var(--t3)" }} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.label} · {l.value}</span>
              <Button variant="ghost" size="icon-sm" onClick={() => model.removeRefLine(i)} title="Remove" style={{ color: "var(--t4)" }}>
                <X size={13} />
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 11.5, color: "var(--t4)" }}>No reference lines yet — open options to add one.</div>
      )}
    </Channel>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function VizEditorPanel({ model, onClose }: { model: VizEditorModel; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  // Escape closes; a click outside the drawer closes — EXCEPT clicks in a design-system Select
  // menu, which portals to <body> (a click there, or a dismiss while one is open, is the select's
  // to handle, not the drawer's). The listener is attached on mount, AFTER the opening pencil click.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Element | null;
      if (t?.closest?.('[data-slot="select-content"]')) return;                 // inside an open menu
      if (document.querySelector('[data-slot="select-content"][data-open]')) return;  // a menu is open → dismiss it
      if (ref.current && !ref.current.contains(t as globalThis.Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { window.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [onClose]);

  const chartMode = model.view === "chart" && model.chartAvailable;

  // Table + Pivot fold into the ONE Visualization dropdown (Databricks-style), alongside the
  // chart types. Selecting Table/Pivot switches the view; a chart type switches to chart view.
  const VIZ_TABLE = "__table__", VIZ_PIVOT = "__pivot__";
  const vizValue = model.view === "table" ? VIZ_TABLE : model.view === "pivot" ? VIZ_PIVOT : model.chartTypeValue;
  const vizOptions: VizSelectOption[] = [
    ...model.chartTypeOptions,
    { v: VIZ_TABLE, t: "Table" },
    ...(model.canPivot ? [{ v: VIZ_PIVOT, t: "Pivot" }] : []),
  ];
  const setViz = (v: string) => {
    if (v === VIZ_TABLE) model.setView("table");
    else if (v === VIZ_PIVOT) model.setView("pivot");
    else { model.setView("chart"); model.setChartType(v); }
  };

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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 16px", borderBottom: "1px solid var(--b1)" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>Edit visualization</div>
          {model.title && (
            <div style={{ fontSize: 11, color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 250 }} title={model.title}>
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
          <Select value={vizValue} options={vizOptions} onChange={setViz}
            leading={<BarChart3 size={15} style={{ color: "var(--accent)", flexShrink: 0 }} />} />
        </Section>

        {chartMode && model.dimOptions.length > 0 && (
          <Channel title="X axis" more={<Field label="Axis title"><TextInput value={model.xTitleValue} placeholder="auto" onChange={model.setXTitle} /></Field>}>
            <Select value={model.dimValue} options={model.dimOptions} onChange={model.setDim} />
          </Channel>
        )}

        {chartMode && model.metricOptions.length > 0 && (
          <Channel
            title="Y axis"
            more={
              <>
                <Field label="Number format"><Select value={model.numberFormatValue} options={model.numberFormatOptions} onChange={model.setNumberFormat} /></Field>
                <Field label="Axis title"><TextInput value={model.yTitleValue} placeholder="auto" onChange={model.setYTitle} /></Field>
              </>
            }
          >
            <Select value={model.metricValue} options={model.metricOptions} onChange={model.setMetric} />
            {model.aggValue != null && (
              <Field label="Aggregation"><Select value={model.aggValue} options={model.aggOptions} onChange={model.setAgg} /></Field>
            )}
            {model.rateSummed && <Warn text="summing a rate — AVG is the grain-correct aggregate" />}
          </Channel>
        )}

        {chartMode && model.colorFieldOptions.length > 1 && (
          <Channel title="Color" onRemove={model.colorFieldValue ? () => model.setColorField("") : null}>
            <Select value={model.colorFieldValue} options={model.colorFieldOptions} onChange={model.setColorField} />
            {model.colorFieldValue && (
              <>
                <Field label="Scale type">
                  <SegToggle
                    value={model.colorScaleValue || "categorical"}
                    onChange={model.setColorScale}
                    options={[["categorical", "Categorical"], ["continuous", "Continuous"]]}
                  />
                </Field>
                <Field label="Display name"><TextInput value={model.colorNameValue} placeholder="auto" onChange={model.setColorName} /></Field>
                <Field label="Legend"><Select value={model.legendValue} options={model.legendOptions} onChange={model.setLegend} /></Field>
              </>
            )}
          </Channel>
        )}

        {chartMode && <ToggleRow title="Labels" on={model.showLabels} onChange={model.setShowLabels} />}
        {chartMode && <ToggleRow title="Tooltip" on={model.tooltipOn} onChange={model.setTooltipOn} />}

        {model.view !== "pivot" && model.transformOptions.length > 0 && (
          <Channel title="Transform">
            <Select value={model.transformValue} options={model.transformOptions} onChange={model.setTransform} />
            {model.transformErr && <Warn text="transform not available for this shape" />}
          </Channel>
        )}

        {chartMode && <AnnotationSection model={model} />}
      </div>
    </div>
  );
}
