"use client";

/**
 * ButtonsSetup — the setup of a cockpit's action buttons (Arc AP-3; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.5;
 * design-mockups/cockpit-builder.html screen 4).
 *
 * Each button names a declared action and takes each of its parameters from one source. Only sources that hold the
 * parameter's entity are offered — an order parameter is offered the chosen order, the ticked orders and the sets of
 * orders, never a customer — and a value parameter is asked in the form or fixed. The author picks whether the button
 * asks first, what it does when it cannot run, and which sets are read again after it runs. Who may press it, what it
 * checks and what it changes stay the declared action's own.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { SelectField } from "@/components/ui/select";
import { MAX_BUTTONS, MAX_LABEL, type ActionButtonDef, type ParamSource } from "@/lib/cockpit/catalog";
import { setProps, type CockpitSpec } from "@/lib/cockpit/edit";
import { choicesOf, isRefused, readSet } from "@/lib/cockpit/sets";
import { withUniqueKeys } from "@/lib/listKeys";
import { getDeclaredActions, type DeclaredAction } from "@/lib/objects";

type Change = (next: CockpitSpec, note: string) => void;
const words = (s: string) => s.replace(/[_-]+/g, " ").trim();
/** Two spellings of one entity — `order`, `Order`, `orders` — read alike. */
export const sameEntity = (a: string, b: string) => {
  const w = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "").replace(/s$/, "");
  return !!a && !!b && w(a) === w(b);
};

function Row({ label, hint, children, testid }: { label: string; hint?: string; children: React.ReactNode; testid?: string }) {
  return (
    <div data-testid={testid} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 14px" }}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>{label}</div>
      {children}
      {hint && <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.45 }}>{hint}</div>}
    </div>
  );
}

/** A source as a select carries it, and back. */
const encode = (s: ParamSource | undefined): string => (!s ? "" : "from" in s ? `from:${s.from}` : "set" in s ? `set:${s.set}`
  : "ask" in s ? "ask" : "value");
function decode(v: string, fixed: string): ParamSource | null {
  if (!v) return null;
  if (v === "ask") return { ask: true };
  if (v === "value") return { value: fixed };
  const at = v.indexOf(":");
  return v.slice(0, at) === "from" ? { from: v.slice(at + 1) } : { set: v.slice(at + 1) };
}

export function ButtonsSetup({ spec, k, onChange, connectionId, schema }: {
  spec: CockpitSpec; k: string; onChange: Change; connectionId: string; schema?: string;
}) {
  const [declared, setDeclared] = useState<Record<string, DeclaredAction> | null>(null);
  const [at, setAt] = useState(0);
  useEffect(() => {
    let alive = true;
    getDeclaredActions(connectionId, schema).then(a => { if (alive) setDeclared(a); }).catch(() => { if (alive) setDeclared({}); });
    return () => { alive = false; };
  }, [connectionId, schema]);
  const buttons = (spec.elements[k]?.props.buttons as ActionButtonDef[] | undefined) ?? [];
  const put = (next: ActionButtonDef[], note: string) => onChange(setProps(spec, k, { buttons: next }), note);
  const b = buttons[Math.min(at, buttons.length - 1)];
  const i = Math.min(at, buttons.length - 1);
  const action = b ? declared?.[b.action] : undefined;
  const choices = [...choicesOf(spec).values()];
  const sets = Object.keys(spec.sets ?? {}).map(n => ({ name: n, label: spec.sets?.[n]?.label ?? n, read: readSet(spec, n) }));
  const setButton = (patch: Partial<ActionButtonDef>, note: string) => put(buttons.map((x, j) => (j === i ? { ...x, ...patch } : x)), note);
  const actions = Object.values(declared ?? {});
  return (
    <>
      <Row label="Buttons" testid="setup-buttons" hint={`At most ${MAX_BUTTONS}. Each runs a declared action.`}>
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 2 }}>
          {buttons.map((x, j) => (
            <li key={`${x.action}-${j}`} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <Button variant="ghost" data-testid="setup-button" aria-pressed={j === i} onClick={() => setAt(j)} className="aug-fs-sm"
                style={{ flex: 1, justifyContent: "flex-start", textAlign: "left", height: "auto", padding: "4px 8px", borderRadius: "var(--r2)", fontWeight: 400,
                  background: j === i ? "var(--accent-a3, var(--bg-3))" : "transparent", color: "var(--t1)" }}>
                {x.label || declared?.[x.action]?.display_name || words(x.action)}
                {x.primary && <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: 6 }}>primary</span>}
              </Button>
              <Button size="xs" variant="ghost" aria-label="Move the button earlier" disabled={j === 0}
                onClick={() => { const n = [...buttons]; [n[j - 1], n[j]] = [n[j], n[j - 1]]; put(n, "buttons arranged by hand"); setAt(j - 1); }}><Icon name="chevu" size={12} /></Button>
              <Button size="xs" variant="ghost" aria-label="Take the button off" disabled={buttons.length === 1}
                onClick={() => { put(buttons.filter((_, n) => n !== j), "a button taken off by hand"); setAt(0); }}><Icon name="close" size={12} /></Button>
            </li>
          ))}
        </ul>
        {buttons.length < MAX_BUTTONS && actions.length > 0 && (
          <SelectField aria-label="Add a button" value="" onChange={e => { if (e.target.value) { put([...buttons, { action: e.target.value }], "a button added by hand"); setAt(buttons.length); } }}>
            <option value="">+ Add a button</option>
            {withUniqueKeys(actions, a => a.id).map(([key, a]) => <option key={key} value={a.id}>{a.display_name || words(a.id)}</option>)}
          </SelectField>
        )}
      </Row>
      {b && (
        <>
          <Row label="It runs" hint={action ? `${action.risk === "high" ? "High risk — each run proposed for approval" : action.risk === "low" ? "Low risk — runs at once" : "Reads only"}. ${action.description ?? ""}` : declared ? "Not declared on this connection." : "Reading the declared actions…"}>
            <SelectField aria-label="The button's action" value={b.action} onChange={e => setButton({ action: e.target.value, params: null }, "a button's action chosen by hand")}>
              {!action && <option value={b.action}>{words(b.action)}</option>}
              {withUniqueKeys(actions, a => a.id).map(([key, a]) => <option key={key} value={a.id}>{a.display_name || words(a.id)}</option>)}
            </SelectField>
            <Input aria-label="The button's label" placeholder={action?.display_name || words(b.action)} maxLength={MAX_LABEL} defaultValue={b.label ?? ""} key={`${k}-${i}-label`}
              onBlur={e => { const t = e.target.value.trim(); if (t !== (b.label ?? "")) setButton({ label: t || null }, "a button's label written by hand"); }} />
            <label className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t2)" }}>
              <Checkbox checked={!!b.primary} onChange={e => setButton({ primary: e.target.checked || null }, "a button's emphasis chosen by hand")} aria-label="Primary" />
              The primary button
            </label>
          </Row>
          {action && action.params.length > 0 && (
            <Row label="Its parameters" testid="setup-params" hint="Only what holds the parameter's entity is offered.">
              {withUniqueKeys(action.params, p => p.name).map(([key, p]) => {
                const src = b.params?.[p.name];
                const fixed = src && "value" in src ? String(src.value) : "";
                const options: { value: string; label: string }[] = p.kind === "object" ? [
                  ...choices.filter(c => c.kind !== "shown" && sameEntity(c.entity, p.object_type)).map(c => ({
                    value: `from:${c.name}`, label: c.kind === "chosen" ? `${words(c.name)} — runs once` : `${words(c.name)} — once for each, at most 50` })),
                  ...sets.filter(s => !isRefused(s.read) && sameEntity(s.read.entity, p.object_type)).map(s => ({
                    value: `set:${s.name}`, label: `Every one in ${s.label} — asks first` })),
                ] : [{ value: "ask", label: "Asked in the form" }, { value: "value", label: "The same every time" }];
                return (
                  <div key={key} data-testid="setup-param" style={{ display: "flex", flexDirection: "column", gap: 4, padding: "4px 0" }}>
                    <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>
                      {p.display_name || words(p.name)}
                      <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: 6 }}>
                        {p.kind === "object" ? `${an(words(p.object_type).toLowerCase())}` : words(p.data_type || "value").toLowerCase()}{p.required ? " · needed" : ""}
                      </span>
                    </span>
                    <SelectField aria-label={`Where ${p.display_name || words(p.name)} comes from`} value={encode(src)}
                      onChange={e => {
                        const next = { ...(b.params ?? {}) };
                        const s = decode(e.target.value, fixed);
                        if (s) next[p.name] = s; else delete next[p.name];
                        setButton({ params: Object.keys(next).length ? next : null }, "a button's parameter wired by hand");
                      }}>
                      <option value="">{p.kind === "object" ? "Choose its source" : p.required && p.default_value == null ? "Asked in the form" : "Left as declared"}</option>
                      {withUniqueKeys(options, o => o.value).map(([key, o]) => <option key={key} value={o.value}>{o.label}</option>)}
                    </SelectField>
                    {src && "value" in src && (
                      <Input aria-label={`The value of ${p.display_name || words(p.name)}`} defaultValue={fixed} key={`${k}-${i}-${p.name}`}
                        onBlur={e => setButton({ params: { ...(b.params ?? {}), [p.name]: { value: e.target.value } } }, "a button's fixed value written by hand")} />
                    )}
                    {p.kind === "object" && !options.length && (
                      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Nothing here holds {words(p.object_type).toLowerCase()} objects yet: a table&rsquo;s click can choose one.</span>
                    )}
                  </div>
                );
              })}
            </Row>
          )}
          <Row label="Ask first">
            <Segmented label="Ask first" value={b.ask ?? "form"} options={[{ value: "form", label: "Show the form" }, { value: "run", label: "Run when complete" }]}
              onChange={v => setButton({ ask: v === "form" ? null : "run" }, "a button's form chosen by hand")} />
          </Row>
          <Row label="When it cannot run">
            <Segmented label="When it cannot run" value={b.blocked ?? "disable"} options={[{ value: "disable", label: "Disabled, saying why" }, { value: "hide", label: "Hidden" }]}
              onChange={v => setButton({ blocked: v === "disable" ? null : "hide" }, "a button's blocked look chosen by hand")} />
          </Row>
          {sets.length > 0 && (
            <Row label="After it runs" hint="Every piece is read again; the sets ticked here are named as what it changes.">
              {withUniqueKeys(sets, s => s.name).map(([key, s]) => (
                <label key={key} className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t2)" }}>
                  <Checkbox checked={(b.after?.read ?? []).includes(s.name)} aria-label={`Read ${s.label} again`}
                    onChange={e => {
                      const read = new Set(b.after?.read ?? []);
                      if (e.target.checked) read.add(s.name); else read.delete(s.name);
                      setButton({ after: read.size ? { read: [...read] } : null }, "what a button reads again chosen by hand");
                    }} />
                  Read {s.label} again
                </label>
              ))}
            </Row>
          )}
          <div className="aug-fs-xs" style={{ padding: "10px 14px", color: "var(--t3)", lineHeight: 1.45 }}>
            Who may press it, what it checks and what it changes are the action&rsquo;s own — Ontology ▸ Actions.
          </div>
        </>
      )}
    </>
  );
}

const an = (w: string) => (/^[aeiou]/i.test(w) ? `an ${w}` : `a ${w}`);
