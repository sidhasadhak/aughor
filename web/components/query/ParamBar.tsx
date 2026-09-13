"use client";

/**
 * SE-4 H — the parameter bar: one control per `:name` in the current statement.
 * SE-8C — those controls became WIDGETS (Databricks' parameter widgets): a gear beside
 * each one configures label, widget kind, choices and default; a date widget carries
 * the ⚡ dynamic-value menu; a multiselect binds a list (`x IN :name` — the server
 * expands it to scalar binds); a dropdown's choices can come from a saved query.
 *
 * Appears only when the SQL actually has parameters, so a plain query is not paying
 * for a row of chrome it never uses. It sits BETWEEN the editor and the results now —
 * where Databricks puts it, and where "fill these, then look below" reads in order.
 *
 * **Values are never substituted into the SQL here.** They travel to the server as a
 * separate field and are executed as real bind values. Doing the substitution
 * client-side would hand the server a statement whose shape depends on user input —
 * exactly what parameterisation exists to prevent — and it would also defeat the
 * guard rendering, which needs to know which parts of the query were parameters.
 */
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  DYNAMIC_DATE_TOKENS, OPTIONS_QUERY_CAP, isDynamicDate,
  type ParamDef, type ParamValue,
} from "@/lib/query/paramDefs";
import { listSavedQueries, runWorkbenchQuery, type SavedQuery } from "@/lib/api";

const WIDGETS: { v: ParamDef["widget"]; label: string }[] = [
  { v: "text", label: "Text" },
  { v: "number", label: "Number" },
  { v: "date", label: "Date" },
  { v: "dropdown", label: "Dropdown" },
  { v: "multiselect", label: "Multi-select" },
];

// UPWARD, deliberately: this bar is the LAST row of the editor pane, and the pane
// clips (`overflow: hidden`), so a menu dropping below it renders fully — in the DOM —
// and shows nothing. Measured live: the gear "opened" invisibly. Opening over the
// editor keeps every pixel inside the pane.
const menuStyle: React.CSSProperties = {
  position: "absolute", bottom: "100%", left: 0, zIndex: 41, marginBottom: 4,
  minWidth: 200, padding: 5, background: "var(--bg-2)",
  border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-md)",
};

export function ParamBar({
  connId,
  names,
  values,
  defs,
  onChange,
  onDefsChange,
}: {
  connId: string;
  /** Parameter names found in the statement, in first-appearance order. */
  names: string[];
  values: Record<string, ParamValue>;
  /** Widget definitions per parameter — absent means a plain text input. */
  defs: Record<string, ParamDef>;
  onChange: (next: Record<string, ParamValue>) => void;
  onDefsChange: (next: Record<string, ParamDef>) => void;
}) {
  const [gear, setGear] = useState("");        // param whose config popover is open
  const [multi, setMulti] = useState("");      // param whose multiselect list is open
  const [zap, setZap] = useState("");          // param whose ⚡ menu is open
  // Query-sourced choices, keyed by saved-query id. "loading"/"error" are states the
  // menu shows honestly instead of an empty list that looks like "no options".
  const [queryOptions, setQueryOptions] = useState<Record<string, string[] | "loading" | "error">>({});
  // The saved-query list for the gear's source picker — fetched when a gear opens.
  const [savedList, setSavedList] = useState<SavedQuery[] | null>(null);

  useEffect(() => {
    if (!gear || savedList !== null || !connId) return;
    listSavedQueries(connId).then(setSavedList).catch(() => setSavedList([]));
  }, [gear, savedList, connId]);

  const closeAll = useCallback(() => { setGear(""); setMulti(""); setZap(""); }, []);
  useEffect(() => {
    if (!gear && !multi && !zap) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeAll(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [gear, multi, zap, closeAll]);

  /** Fetch a query-sourced option list, once per saved query. Lazy — on the click
   *  that needs it, never on mount: restoring ten tabs must not fire ten queries. */
  const loadQueryOptions = useCallback((queryId: string) => {
    if (!connId || !queryId) return;
    setQueryOptions(prev => {
      if (prev[queryId]) return prev;
      void (async () => {
        try {
          const list = savedList ?? await listSavedQueries(connId);
          const q = list.find(s => s.id === queryId);
          if (!q) throw new Error("saved query is gone");
          const res = await runWorkbenchQuery(connId, q.sql, OPTIONS_QUERY_CAP);
          if (res.error) throw new Error(res.error);
          const seen = new Set<string>();
          for (const row of res.rows) {
            const v = row[0];
            if (v !== null && v !== undefined) seen.add(String(v));
          }
          setQueryOptions(p => ({ ...p, [queryId]: [...seen] }));
        } catch {
          setQueryOptions(p => ({ ...p, [queryId]: "error" }));
        }
      })();
      return { ...prev, [queryId]: "loading" };
    });
  }, [connId, savedList]);

  if (!names.length) return null;

  const defFor = (n: string): ParamDef => defs[n] ?? { widget: "text" };
  const setValue = (n: string, v: ParamValue) => onChange({ ...values, [n]: v });
  const patchDef = (n: string, patch: Partial<ParamDef>) =>
    onDefsChange({ ...defs, [n]: { ...defFor(n), ...patch } });

  /** The choices a dropdown/multiselect offers right now. */
  const choicesFor = (def: ParamDef): string[] | "loading" | "error" => {
    if (def.optionsQueryId) return queryOptions[def.optionsQueryId] ?? "loading";
    return def.options ?? [];
  };

  const missing = names.filter(n => {
    const v = values[n] ?? defFor(n).default;
    return Array.isArray(v) ? v.length === 0 : !(v ?? "").trim();
  });

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        padding: "6px 10px", borderTop: "1px solid var(--b0)", flexShrink: 0,
      }}
    >
      <span className="aug-fs-ui" style={{ color: "var(--t3)", flexShrink: 0 }}>
        Parameters
      </span>

      {names.map(name => {
        const def = defFor(name);
        const value = values[name] ?? def.default ?? (def.widget === "multiselect" ? [] : "");
        const choices = choicesFor(def);
        const label = def.label || `:${name}`;

        return (
          <span key={name} style={{ position: "relative", display: "flex", alignItems: "center", gap: 4 }}>
            <span className={def.label ? "aug-fs-ui" : "aug-fs-ui font-mono"} style={{ color: "var(--t3)" }}>
              {label}
            </span>

            {def.widget === "dropdown" ? (
              <select
                className="aug-input aug-fs-ui"
                style={{ width: 140 }}
                value={typeof value === "string" ? value : ""}
                onFocus={() => def.optionsQueryId && loadQueryOptions(def.optionsQueryId)}
                onChange={e => setValue(name, e.target.value)}
              >
                <option value="">— pick —</option>
                {choices === "loading" ? <option disabled>Loading…</option>
                  : choices === "error" ? <option disabled>Choices failed to load</option>
                  : choices.map(o => <option key={o} value={o}>{o}</option>)}
                {/* A value set before the choices changed stays visible and selected. */}
                {typeof value === "string" && value && Array.isArray(choices) && !choices.includes(value) && (
                  <option value={value}>{value}</option>
                )}
              </select>
            ) : def.widget === "multiselect" ? (
              <Button variant="secondary" size="xs" className="aug-fs-ui"
                style={{ minWidth: 120, justifyContent: "flex-start" }}
                onClick={() => {
                  if (def.optionsQueryId) loadQueryOptions(def.optionsQueryId);
                  setMulti(m => m === name ? "" : name);
                }}>
                {Array.isArray(value) && value.length
                  ? value.length === 1 ? value[0] : `${value.length} selected`
                  : "— pick —"}
              </Button>
            ) : def.widget === "date" && isDynamicDate(value) ? (
              // A ⚡ token stays a token on screen — showing its resolution would look
              // like a literal date that then silently moved.
              <Button variant="secondary" size="xs" className="aug-fs-ui"
                title="A dynamic value — resolved when the query runs. Click to change."
                onClick={() => setZap(z => z === name ? "" : name)}>
                <Icon name="bolt" size={11} /> {value}
              </Button>
            ) : (
              <input
                className="aug-input aug-fs-ui"
                style={{ width: def.widget === "date" ? 130 : 120 }}
                type={def.widget === "number" ? "number" : def.widget === "date" ? "date" : "text"}
                value={typeof value === "string" ? value : ""}
                placeholder="value"
                list={def.widget === "text" && def.options?.length ? `parambar-dl-${name}` : undefined}
                onChange={e => setValue(name, e.target.value)}
              />
            )}
            {/* Text + options = a combobox: free entry with suggestions. */}
            {def.widget === "text" && def.options?.length ? (
              <datalist id={`parambar-dl-${name}`}>
                {def.options.map(o => <option key={o} value={o} />)}
              </datalist>
            ) : null}

            {def.widget === "date" && (
              <Button variant="ghost" size="xs" title="Dynamic values — today, start of this month, …"
                aria-label={`Dynamic date for ${label}`}
                onClick={() => setZap(z => z === name ? "" : name)}
                style={{ padding: "0 3px" }}>
                <Icon name="bolt" size={12} />
              </Button>
            )}

            <Button variant="ghost" size="xs" title={`Configure the ${label} widget`}
              aria-label={`Configure ${label}`}
              onClick={() => setGear(g => g === name ? "" : name)}
              style={{ padding: "0 3px" }}>
              <Icon name="settings" size={12} />
            </Button>

            {zap === name && (
              <>
                <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setZap("")} />
                <div className="aug-fs-ui" style={menuStyle}>
                  {DYNAMIC_DATE_TOKENS.map(t => (
                    <Button key={t} variant="ghost" size="xs" className="aug-fs-ui"
                      style={{ width: "100%", justifyContent: "flex-start" }}
                      onClick={() => { setValue(name, t); setZap(""); }}>
                      {t}
                    </Button>
                  ))}
                  {isDynamicDate(value) && (
                    <Button variant="ghost" size="xs" className="aug-fs-ui"
                      style={{ width: "100%", justifyContent: "flex-start", color: "var(--t3)" }}
                      onClick={() => { setValue(name, ""); setZap(""); }}>
                      Clear — type a date instead
                    </Button>
                  )}
                </div>
              </>
            )}

            {multi === name && (
              <>
                <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setMulti("")} />
                <div className="aug-fs-ui" style={{ ...menuStyle, maxHeight: 240, overflowY: "auto" }}>
                  {choices === "loading" ? (
                    <span style={{ display: "block", padding: "3px 7px", color: "var(--t3)" }}>Loading…</span>
                  ) : choices === "error" ? (
                    <span style={{ display: "block", padding: "3px 7px", color: "var(--red4)" }}>Choices failed to load</span>
                  ) : choices.length === 0 ? (
                    <span style={{ display: "block", padding: "3px 7px", color: "var(--t3)" }}>
                      No choices yet — add them with the gear
                    </span>
                  ) : choices.map(o => {
                    const selected = Array.isArray(value) && value.includes(o);
                    return (
                      <Button key={o} variant="ghost" size="xs" className="aug-fs-ui"
                        style={{ width: "100%", justifyContent: "flex-start", gap: 6 }}
                        onClick={() => {
                          const cur = Array.isArray(value) ? value : [];
                          setValue(name, selected ? cur.filter(x => x !== o) : [...cur, o]);
                        }}>
                        <span style={{ width: 14, flexShrink: 0 }}>
                          {selected && <Icon name="check" size={12} />}
                        </span>
                        {o}
                      </Button>
                    );
                  })}
                </div>
              </>
            )}

            {gear === name && (
              <>
                <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setGear("")} />
                <div className="aug-fs-ui" style={{ ...menuStyle, minWidth: 260, padding: "8px 10px" }}>
                  <div className="aug-label" style={{ marginBottom: 6 }}>:{name}</div>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                    <span style={{ color: "var(--t3)", width: 64, flexShrink: 0 }}>Label</span>
                    <input className="aug-input aug-fs-ui" style={{ flex: 1 }}
                      value={def.label ?? ""} placeholder={`:${name}`}
                      onChange={e => patchDef(name, { label: e.target.value })} />
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                    <span style={{ color: "var(--t3)", width: 64, flexShrink: 0 }}>Widget</span>
                    <select className="aug-input aug-fs-ui" style={{ flex: 1 }}
                      value={def.widget}
                      onChange={e => {
                        const widget = e.target.value as ParamDef["widget"];
                        patchDef(name, { widget });
                        // A scalar value cannot survive into a list widget, nor a list
                        // into a scalar one — clearing beats a silently wrong bind.
                        const wasList = Array.isArray(values[name]);
                        if (wasList !== (widget === "multiselect")) setValue(name, widget === "multiselect" ? [] : "");
                      }}>
                      {WIDGETS.map(w => <option key={w.v} value={w.v}>{w.label}</option>)}
                    </select>
                  </label>
                  {(def.widget === "dropdown" || def.widget === "multiselect" || def.widget === "text") && (
                    <>
                      <label style={{ display: "flex", alignItems: "flex-start", gap: 6, marginBottom: 6 }}>
                        <span style={{ color: "var(--t3)", width: 64, flexShrink: 0, paddingTop: 3 }}>
                          {def.widget === "text" ? "Suggest" : "Choices"}
                        </span>
                        <textarea className="aug-input aug-fs-ui" rows={3} style={{ flex: 1, resize: "vertical" }}
                          placeholder={"one per line"}
                          value={(def.options ?? []).join("\n")}
                          onChange={e => patchDef(name, {
                            options: e.target.value.split("\n").map(s => s.trim()).filter(Boolean),
                          })} />
                      </label>
                      {def.widget !== "text" && (
                        <label style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                          <span style={{ color: "var(--t3)", width: 64, flexShrink: 0 }}>From query</span>
                          <select className="aug-input aug-fs-ui" style={{ flex: 1 }}
                            value={def.optionsQueryId ?? ""}
                            onChange={e => patchDef(name, { optionsQueryId: e.target.value || undefined })}>
                            <option value="">— typed choices above —</option>
                            {(savedList ?? []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                          </select>
                        </label>
                      )}
                    </>
                  )}
                  {def.widget !== "multiselect" && (
                    <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ color: "var(--t3)", width: 64, flexShrink: 0 }}>Default</span>
                      <input className="aug-input aug-fs-ui" style={{ flex: 1 }}
                        value={typeof def.default === "string" ? def.default : ""}
                        placeholder="none"
                        onChange={e => patchDef(name, { default: e.target.value || undefined })} />
                    </label>
                  )}
                  {def.widget === "multiselect" && (
                    <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "2px 0 0" }}>
                      Write the SQL as <code>IN :{name}</code> — no parentheses; the
                      selection binds as a list.
                    </p>
                  )}
                </div>
              </>
            )}
          </span>
        );
      })}

      {Object.keys(values).length > 0 && (
        <Button
          variant="ghost" size="xs" className="aug-fs-ui"
          title="Clear every parameter value"
          onClick={() => onChange({})}
        >
          Clear
        </Button>
      )}

      {/* Stated, not enforced by a disabled Run: the engine's own error for a missing
          bind value is clearer than a greyed-out button that explains nothing. What
          this line adds is WHICH one is missing, before the round trip. */}
      {missing.length > 0 && (
        <span className="aug-fs-ui" style={{ color: "var(--amb4)" }}>
          {missing.map(n => `:${n}`).join(", ")} {missing.length === 1 ? "has" : "have"} no value —
          guards cannot check this query until filled
        </span>
      )}
    </div>
  );
}
