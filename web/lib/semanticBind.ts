/**
 * Binding a package's roles to this connection's data, as the Semantic Layer asks it (the user, 2026-10-13: "when the
 * user clicks on bind roles … it's not clear what the user is supposed to do"). An industry metric is a recipe written
 * over ROLES — `{{role.order_item.returned_at}}` — never over tables; binding says which table plays each role and
 * which column holds each attribute the recipe reads. Decided here, laid out by `components/semantic/BindRoles.tsx`.
 * Pure: nothing here fetches.
 */
import type { PackDetail, RoleBinding, SchemaTable } from "@/lib/api";

const TOKEN = /\{\{\s*role\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\}\}/g;

export interface AttributeNeed { name: string; type: string; description: string }
export interface RoleNeed {
  role: string;
  description: string;
  /** The attributes the recipes read — only those, never every attribute the role could carry. */
  attributes: AttributeNeed[];
  /** The recipes that read this role, by their label. */
  recipes: string[];
}

/** The roles and attributes these recipes read, from their own formulas, in the order the recipes name them. */
export function needsOf(recipes: { label: string; sql: string }[], pack: PackDetail): RoleNeed[] {
  const out = new Map<string, RoleNeed>();
  for (const r of recipes) {
    for (const m of (r.sql || "").matchAll(TOKEN)) {
      const [, role, attr] = m;
      const spec = pack.entities?.[role];
      const need = out.get(role) ?? { role, description: spec?.description?.trim() ?? "", attributes: [], recipes: [] };
      if (!need.attributes.some(a => a.name === attr)) {
        const a = spec?.attributes?.[attr];
        need.attributes.push({ name: attr, type: a?.type ?? "", description: (a?.description ?? "").trim() });
      }
      if (!need.recipes.includes(r.label)) need.recipes.push(r.label);
      out.set(role, need);
    }
  }
  return [...out.values()];
}

const DATEY = /(^|_)(date|day|time|timestamp|at|on|start|end)(_|$)/i;
const NUMERIC = /int|numeric|decimal|double|float|real|number|money/i;
const TEXTY = /char|text|string/i;

/** Whether a column can carry an attribute of this type. A timestamp takes a date or time column — or a day kept as
 *  text, by its name — and never a true/false one: a recipe tests it `IS NOT NULL`, and a false is not NULL, so a flag
 *  bound there would count every row as returned. */
export function fits(attrType: string, dtype: string, column: string): boolean {
  const t = (attrType || "").toLowerCase();
  const d = (dtype || "").toLowerCase();
  if (t === "timestamp" || t === "date" || t === "datetime") return /date|time/.test(d) || (TEXTY.test(d) && DATEY.test(column));
  if (["money", "amount", "number", "measure", "count", "quantity", "duration"].includes(t)) return NUMERIC.test(d);
  if (t === "flag" || t === "boolean") return /bool/.test(d) || /int/.test(d);
  return true;
}

/** The tables of the schema the binding is for — "luxexperience.order_items" — or every table when none is named. */
export function tablesOf(tables: SchemaTable[], schema?: string): SchemaTable[] {
  if (!schema) return tables;
  const mine = tables.filter(t => t.name.split(".").slice(-2, -1)[0] === schema);
  return mine.length ? mine : tables;
}

export interface Choice { table: string; columns: Record<string, string> }

/** Whether a role is chosen whole: its table and a column for every attribute its recipes read. */
export function complete(need: RoleNeed, choice: Choice | undefined): boolean {
  return !!choice?.table && need.attributes.every(a => !!choice.columns[a.name]);
}

/** The binding to pin: what the connection already has, with each role chosen whole laid over it. A role not chosen
 *  whole is left as it was — a half-bound role would let a recipe render an unresolved token. */
export function bindingToSave(existing: Record<string, RoleBinding>, needs: RoleNeed[],
                              choices: Record<string, Choice>): Record<string, RoleBinding> {
  const out: Record<string, RoleBinding> = { ...existing };
  for (const need of needs) {
    const c = choices[need.role];
    if (!complete(need, c)) continue;
    out[need.role] = {
      ...(existing[need.role] ?? {}),
      table: c.table,
      columns: { ...(existing[need.role]?.columns ?? {}), ...c.columns },
      confidence: 1,
      evidence: "chosen by a person in the Semantic Layer",
    };
  }
  return out;
}

/** An attribute as a reader says it: `converted_order_id` → "converted order id". */
export const attributeWords = (name: string) => name.replace(/_/g, " ");
