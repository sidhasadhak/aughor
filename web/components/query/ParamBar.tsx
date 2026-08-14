"use client";

/**
 * SE-4 H — the parameter bar: one input per `:name` in the current statement.
 *
 * Appears only when the SQL actually has parameters, so a plain query is not paying
 * for a row of chrome it never uses.
 *
 * **Values are never substituted into the SQL here.** They travel to the server as a
 * separate field and are executed as real bind values. Doing the substitution
 * client-side would hand the server a statement whose shape depends on user input —
 * exactly what parameterisation exists to prevent — and it would also defeat the
 * guard rendering, which needs to know which parts of the query were parameters.
 *
 * Everything is a string here. Typed inputs (a date picker for a DATE column, a number
 * spinner for a numeric one) need the parameter's USE SITE to be resolved against the
 * schema, which is worth doing and is not this PR: guessing a type from the name would
 * make `:count_of_things` a number and `:order_id` a number that must not be one.
 */
import { Button } from "@/components/ui/button";

export function ParamBar({
  names,
  values,
  onChange,
}: {
  /** Parameter names found in the statement, in first-appearance order. */
  names: string[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  if (!names.length) return null;

  const missing = names.filter(n => !(values[n] ?? "").trim());

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        padding: "6px 10px", borderBottom: "1px solid var(--b0)", flexShrink: 0,
      }}
    >
      <span className="aug-fs-ui" style={{ color: "var(--t4)", flexShrink: 0 }}>
        Parameters
      </span>

      {names.map(name => (
        <label key={name} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span className="aug-fs-ui font-mono" style={{ color: "var(--t3)" }}>:{name}</span>
          <input
            className="aug-input aug-fs-ui"
            style={{ width: 130 }}
            value={values[name] ?? ""}
            placeholder="value"
            onChange={e => onChange({ ...values, [name]: e.target.value })}
          />
        </label>
      ))}

      {values && Object.keys(values).length > 0 && (
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
