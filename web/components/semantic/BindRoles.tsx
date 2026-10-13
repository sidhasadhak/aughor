"use client";

/**
 * Bind a package's roles to this connection, from the Semantic Layer itself (the user, 2026-10-13: "when the user clicks
 * on bind roles, it goes to the settings tab, but it's not clear what the user is supposed to do"). It went to Settings ▸
 * System, where an industry package showed only its description and no way to bind; where binding did show, proposing
 * read only a DuckDB connection and binding dropped the columns a recipe reads.
 *
 * Here: what binding is, in one line; for each role the metrics read, the table that plays it and the column for each
 * attribute — only columns that can carry the attribute's type are offered, the package's own proposal first; where no
 * column fits, that is said, with the metric's other way: writing its SQL over this connection's own columns.
 */
import { useEffect, useMemo, useState } from "react";

import { Chip, MUTED, ROW } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { SelectField } from "@/components/ui/select";
import {
  bindPack, getPackBinding, getPackDetail, getSchemaRich, proposePackBindings,
  type BindingCandidateDTO, type PackDetail, type RoleBinding, type SchemaTable,
} from "@/lib/api";
import { withUniqueKeys } from "@/lib/listKeys";
import { attributeWords, bindingToSave, complete, fits, needsOf, tablesOf, type Choice } from "@/lib/semanticBind";

export interface BindRecipe { name: string; label: string; sql: string }

const bare = (t: string) => t.split(".").pop() ?? t;

export function BindRolesDialog({ open, onClose, connId, schema, packId, recipes, onBound, onWriteSql }: {
  open: boolean;
  onClose: () => void;
  connId: string;
  schema?: string;
  packId: string;
  /** The package's metrics this connection cannot compute yet. */
  recipes: BindRecipe[];
  onBound: () => void;
  /** The other way: copy the recipe as a draft and write its SQL over this connection's own columns. */
  onWriteSql: (name: string) => void;
}) {
  const [pack, setPack] = useState<PackDetail | null>(null);
  const [existing, setExisting] = useState<Record<string, RoleBinding>>({});
  const [tables, setTables] = useState<SchemaTable[] | null>(null);
  const [proposed, setProposed] = useState<Record<string, BindingCandidateDTO>>({});
  const [unread, setUnread] = useState<string[]>([]);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setResult(null);
    Promise.allSettled([
      getPackDetail(packId), getPackBinding(packId, connId, schema), getSchemaRich(connId),
      proposePackBindings(packId, connId, schema),
    ]).then(([p, b, s, pr]) => {
      if (!alive) return;
      const missing: string[] = [];
      if (p.status === "fulfilled") setPack(p.value); else missing.push("the package");
      if (b.status === "fulfilled") setExisting(b.value?.bindings ?? {}); else missing.push("the current binding");
      if (s.status === "fulfilled") setTables(tablesOf(s.value.tables ?? [], schema)); else { setTables([]); missing.push("this connection's tables"); }
      if (pr.status === "fulfilled") setProposed(pr.value.proposals ?? {}); else missing.push("the package's proposal");
      setUnread(missing);
    });
    return () => { alive = false; };
  }, [open, packId, connId, schema]);

  const needs = useMemo(() => (pack ? needsOf(recipes, pack) : []), [pack, recipes]);

  // What each role starts as: what this connection already bound, else the package's proposal for its table.
  useEffect(() => {
    if (!tables) return;
    const known = (t?: string | null) => (t ? tables.find(x => x.name === t || bare(x.name) === bare(t))?.name ?? "" : "");
    setChoices(Object.fromEntries(needs.map(n => {
      const had = existing[n.role];
      const table = known(had?.table) || known(proposed[n.role]?.table);
      return [n.role, { table, columns: { ...(had?.columns ?? {}) } }];
    })));
  }, [needs, existing, proposed, tables]);

  const columnsOf = (table: string) => tables?.find(t => t.name === table)?.columns ?? [];
  const setTable = (role: string, table: string) =>
    setChoices(c => ({ ...c, [role]: { table, columns: {} } }));
  const setColumn = (role: string, attr: string, column: string) =>
    setChoices(c => ({ ...c, [role]: { ...c[role], columns: { ...c[role].columns, [attr]: column } } }));

  // A recipe that cannot be bound here: a role it reads has a table chosen and no column that fits an attribute.
  const stuck = needs.flatMap(n => {
    const table = choices[n.role]?.table;
    if (!table) return [];
    return n.attributes.filter(a => !columnsOf(table).some(c => fits(a.type, c.type, c.name))).map(a => ({ need: n, attr: a, table }));
  });
  const ready = needs.filter(n => complete(n, choices[n.role]));

  const bind = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await bindPack(packId, connId, bindingToSave(existing, needs, choices), schema);
      if (r.verified) {
        setResult({ ok: true, text: "Bound and checked — every chosen column answered." });
        onBound();
      } else {
        const why = [...(r.dry_run_errors ?? []), ...(r.missing ?? [])].join(" · ");
        setResult({ ok: false, text: `Saved, but not every column answered when checked${why ? ` — ${why}` : ""}.` });
        onBound();
      }
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : "The binding could not be saved." });
    } finally { setBusy(false); }
  };

  const packName = pack?.manifest?.name || packId;
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose(); }}>
      <DialogContent maxWidth="760px" aria-describedby={undefined} data-testid="bind-roles">
        <DialogTitle>{`Bind the ${packName} package here${schema ? ` · ${schema}` : ""}`}</DialogTitle>
        <p className="aug-fs-sm" style={{ margin: 0, color: "var(--t2)" }}>
          Its metrics are recipes written over roles, not over your tables. Choose the table that plays each role and the
          column that holds what the metrics read — then they can be measured here.
        </p>
        {unread.length > 0 && (
          <p className="aug-fs-xs" style={{ margin: 0, color: "var(--amb4)" }} data-testid="bind-unread">
            {`Not read just now: ${unread.join(", ")}.`}
          </p>
        )}
        {!pack || !tables ? (
          <p className="aug-fs-sm" style={{ ...MUTED, margin: 0 }}>Reading the package and this connection&apos;s tables…</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {withUniqueKeys(needs, n => n.role).map(([nKey, n]) => {
              const choice = choices[n.role] ?? { table: "", columns: {} };
              const proposal = proposed[n.role];
              return (
                <div key={nKey} data-testid={`bind-role-${n.role}`}
                  style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 10, borderTop: "1px solid var(--b0)" }}>
                  <div style={ROW}>
                    <span className="aug-fs-ui" style={{ fontWeight: 600, color: "var(--t1)" }}>{attributeWords(n.role)}</span>
                    <span className="aug-fs-xs" style={MUTED}>{`read by ${n.recipes.join(", ")}`}</span>
                    {complete(n, choice) && <Chip tone="up">ready</Chip>}
                  </div>
                  {n.description && <p className="aug-fs-xs" style={{ ...MUTED, margin: 0 }}>{n.description}</p>}
                  <label className="aug-fs-xs" style={{ color: "var(--t2)", display: "flex", alignItems: "center", gap: 8 }}>
                    Table
                    <SelectField value={choice.table} aria-label={`Table for ${n.role}`} onChange={e => setTable(n.role, e.target.value)}>
                      <option value="">Choose the table…</option>
                      {withUniqueKeys(tables, t => t.name).map(([k, t]) => <option key={k} value={t.name}>{t.name}</option>)}
                    </SelectField>
                    {proposal?.table ? (
                      <span style={MUTED} title={proposal.evidence}>{`proposed: ${bare(proposal.table)}`}</span>
                    ) : proposal?.evidence ? (
                      // Nothing proposed is said, with why — never an empty select the reader must puzzle over.
                      <span style={MUTED} data-testid={`bind-unproposed-${n.role}`}>{`nothing proposed — ${proposal.evidence}`}</span>
                    ) : null}
                  </label>
                  {choice.table && withUniqueKeys(n.attributes, a => a.name).map(([aKey, a]) => {
                    const options = columnsOf(choice.table).filter(c => fits(a.type, c.type, c.name));
                    return (
                      <div key={aKey} style={{ display: "grid", gridTemplateColumns: "minmax(140px, 220px) 1fr", gap: 8, alignItems: "center" }}>
                        <span className="aug-fs-xs" style={{ color: "var(--t2)" }} title={a.description}>
                          {attributeWords(a.name)}{a.type ? <span style={MUTED}>{` · ${a.type}`}</span> : null}
                        </span>
                        {options.length ? (
                          <SelectField value={choice.columns[a.name] ?? ""} aria-label={`Column for ${n.role}.${a.name}`}
                            onChange={e => setColumn(n.role, a.name, e.target.value)}>
                            <option value="">Choose the column…</option>
                            {withUniqueKeys(options, c => c.name).map(([k, c]) => <option key={k} value={c.name}>{`${c.name} · ${c.type}`}</option>)}
                          </SelectField>
                        ) : (
                          <span className="aug-fs-xs" style={{ color: "var(--amb4)" }} data-testid={`bind-none-${n.role}-${a.name}`}>
                            {`No ${a.type || "fitting"} column on ${bare(choice.table)}`}
                            {a.type === "timestamp" ? " — a true/false column would count every row" : ""}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
        {stuck.length > 0 && (
          <div style={{ ...ROW, alignItems: "flex-start" }} data-testid="bind-stuck">
            <span className="aug-fs-xs" style={{ ...MUTED, flex: "1 1 320px" }}>
              {`${[...new Set(stuck.flatMap(s => s.need.recipes))].join(", ")} can't be bound to this data as it stands — write its SQL over your own columns instead.`}
            </span>
            {withUniqueKeys(recipes.filter(r => stuck.some(s => s.need.recipes.includes(r.label))), r => r.name).map(([k, r]) => (
              <Button key={k} size="xs" variant="secondary" onClick={() => onWriteSql(r.name)}>{`Write the SQL of ${r.label}`}</Button>
            ))}
          </div>
        )}
        {result && (
          <p className="aug-fs-sm" style={{ margin: 0, color: result.ok ? "var(--grn4)" : "var(--amb4)" }} data-testid="bind-result">
            {result.text}
          </p>
        )}
        <div style={ROW}>
          <Button size="sm" onClick={bind} disabled={busy || ready.length === 0}
            title={ready.length ? undefined : "Choose a table and every column for at least one role first"}>
            {busy ? "Binding…" : ready.length === needs.length || !needs.length ? "Bind" : `Bind ${ready.length} of ${needs.length} roles`}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
