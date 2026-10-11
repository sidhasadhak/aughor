"use client";

/**
 * ActionButtonsPiece — a row of buttons, each a declared action run on what a reader chose or ticked, on a set, or with
 * what they fill in (Arc AP-3; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.5; design-mockups/cockpit-builder.html
 * screens 4 and 6).
 *
 * A cockpit defines no action of its own: a button names a declared action, and the declaration owns who may press it,
 * its criteria, its risk and its approval. Each run is one call to that action's own door (`runOrPropose`), so a
 * high-risk action on twenty ticked orders is twenty proposals in the Actions inbox, never one silent batch. What a
 * press did is said on the button's own row — a run refused says why — and the sets the button names are read again.
 * A button that cannot run says why, or is hidden, as its author chose.
 */
import { useEffect, useState } from "react";

import { usePieces, ranSaid } from "@/components/cockpit/OntologyPieces";
import { Frame } from "@/components/cockpit/CockpitTile";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { MAX_TICKED_RUNS, type ActionButtonDef } from "@/lib/cockpit/catalog";
import { planRuns, pressSaid, runsOf, type ParamDecl } from "@/lib/cockpit/runs";
import { choicesOf, doorConditions, isRefused, readSet } from "@/lib/cockpit/sets";
import { conditionsFor } from "@/lib/cockpit/objectView";
import { withUniqueKeys } from "@/lib/listKeys";
import { formatCount } from "@/lib/format";
import { listObjects, runOrPropose, type DeclaredAction } from "@/lib/objects";

const words = (s: string) => s.replace(/[_-]+/g, " ").trim();
/** A value parameter's input, by the type the declaration gives it. */
const inputType = (t: string) => (/INT|FLOAT|NUM|DEC|DOUBLE|REAL|number/i.test(t) ? "number" : /DATE|TIME/i.test(t) ? "date" : "text");
const isFlag = (t: string) => /BOOL/i.test(t);

export function ActionButtonsPiece({ buttons }: { buttons: ActionButtonDef[] }) {
  const { actions } = usePieces();
  const [declared, setDeclared] = useState<Record<string, DeclaredAction> | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    actions().then(all => { if (alive) setDeclared(all); }).catch(() => { if (alive) setDeclared(null); });
    return () => { alive = false; };
  }, [actions]);
  return (
    <Frame testid="action-buttons">
      {declared === undefined ? (
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading the declared actions…</span>
      ) : declared === null ? (
        <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>The declared actions could not be read, so no button is offered.</span>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-start" }}>
          {buttons.map((b, i) => <OneButton key={`${b.action}-${i}`} def={b} declared={declared[b.action] ?? null} />)}
        </div>
      )}
    </Frame>
  );
}

type Outcome = { status: "ran" } | { status: "proposed" } | { status: "refused"; message: string } | { status: "failed"; message: string };

function OneButton({ def, declared }: { def: ActionButtonDef; declared: DeclaredAction | null }) {
  const { connectionId, schema, wire, picked, ticked, filters, bump } = usePieces();
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const [setKeys, setSetKeys] = useState<{ keys: string[]; total: number | null } | null>(null);
  if (!declared) {
    return <span className="aug-fs-xs" data-testid="action-button-missing" style={{ color: "var(--t3)" }}>The action “{def.action}” is not declared here.</span>;
  }
  const label = def.label || declared.display_name || words(declared.id);
  const choices = choicesOf(wire);
  const plan = planRuns(def, declared.params as ParamDecl[], {
    kindOf: c => choices.get(c)?.kind,
    chosen: c => picked[c] ?? null,
    ticked: c => ticked[c] ?? [],
  });
  const target = declared.params.find(p => p.kind === "object");
  const thing = words(target?.object_type || "object").toLowerCase();
  if ("blocked" in plan && def.blocked === "hide") return null;
  const needed = "blocked" in plan ? [] : plan.asks.filter(p => p.required && p.default_value == null);
  const complete = needed.every(p => asked[p.name] !== undefined && asked[p.name] !== "");
  const formFirst = !("blocked" in plan) && (def.ask === "form" || plan.asks.length > 0 || !!plan.set || (def.ask !== "run" && !!plan.each));

  /** A set's objects, read at the press — at most the most one press runs on, and its count. */
  const readSetKeys = async (name: string) => {
    const r = readSet(wire, name);
    if (isRefused(r)) { setSaid(r.refused); return null; }
    const read = doorConditions(r, c => picked[c]?.pk ?? null);
    if ("waiting" in read) { setSaid(`Choose one in ${words(read.waiting)} first.`); return null; }
    const out = await listObjects({ entity: r.entity, segment: r.segment, columns: [], order_by: "", descending: false, offset: 0,
      limit: MAX_TICKED_RUNS, filters: [...read.filters, ...(conditionsFor(filters, r.entity) as typeof read.filters)] }, connectionId, schema);
    if (out.path === "refused") { setSaid(out.refused); return null; }
    return { keys: out.rows.map(row => String(row[0])), total: out.total };
  };

  const press = async () => {
    if ("blocked" in plan) return;
    setSaid("");
    if (plan.set) {
      const got = await readSetKeys(plan.set.set);
      if (!got) return;
      setSetKeys(got);
      // more than one press runs on: said on the row, and nothing opens — never a form whose Run does nothing
      if (got.total != null && got.total > MAX_TICKED_RUNS) return;
    }
    if (formFirst) { setOpen(true); return; }
    await run();
  };

  const run = async (keys = setKeys?.keys ?? []) => {
    if ("blocked" in plan || !connectionId) return;
    setBusy(true);
    const outcomes: Outcome[] = [];
    try {
      for (const params of runsOf(plan, asked, keys)) {
        try {
          const out = await runOrPropose(declared.id, params, connectionId, schema, `from a cockpit's button: ${label}`);
          // a server that failed is said as one, never as a refusal the action made
          outcomes.push(out.status !== "refused" ? { status: out.status }
            : /^HTTP 5\d\d$/.test(out.message) ? { status: "failed", message: `the server failed while running it (${out.message}) — Actions shows what landed` }
              : { status: "refused", message: out.message });
          if (outcomes.length === 1 && out.status === "ran") setSaid(ranSaid(out.verification));
        } catch (e) {
          // nothing came back to say what the action decided: a failure, never a refusal it made
          outcomes.push({ status: "failed", message: (e as Error).message });
        }
      }
    } finally {
      setBusy(false);
    }
    const one = outcomes.length === 1 && outcomes[0].status === "ran";
    if (!one) setSaid(pressSaid(outcomes, thing));
    setOpen(false); setAsked({});
    // what ran changed what the cockpit reads: its sets, and every piece, are read again
    if (outcomes.some(o => o.status === "ran")) bump();
  };

  const blockedWhy = "blocked" in plan ? plan.blocked : plan.set && setKeys?.total != null && setKeys.total > MAX_TICKED_RUNS
    ? `${words(plan.set.set)} holds ${formatCount(setKeys.total)}; a press runs on at most ${MAX_TICKED_RUNS} — tick the ones to run on.` : "";
  const runs = "blocked" in plan ? 0 : plan.each ? plan.each.pks.length : plan.set ? setKeys?.keys.length ?? 0 : 1;
  return (
    <span data-testid="action-buttons-row" style={{ display: "inline-flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
      <Button size="sm" variant={def.primary ? "default" : "secondary"} disabled={busy || "blocked" in plan} aria-label={label}
        title={"blocked" in plan ? plan.blocked : declared.description || label} onClick={() => void press()}>
        <Icon name="bolt" /> {busy ? "Running…" : label}
      </Button>
      {(blockedWhy || said) && (
        <span className="aug-fs-xs" data-testid="action-buttons-said" style={{ color: blockedWhy ? "var(--t3)" : "var(--t2)", maxWidth: 280 }}>
          {blockedWhy || said}
        </span>
      )}
      {!("blocked" in plan) && (
        <Dialog open={open} onOpenChange={o => { if (!busy) setOpen(o); }}>
          <DialogContent data-testid="action-buttons-form" style={{ maxWidth: 440 }}>
            <DialogHeader>
              <DialogTitle>{label}</DialogTitle>
              <DialogDescription>{declared.description || `On ${runs === 1 ? `one ${thing}` : `${formatCount(runs)} ${thing}s`}.`}</DialogDescription>
            </DialogHeader>
            {withUniqueKeys(plan.said, s => s.param.name).map(([key, { param, words: w }]) => (
              <div key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>{param.display_name || words(param.name)}</span>
                <span className="aug-fs-sm" style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--t1)" }}>
                  <Icon name="lock" size={12} />{w}{plan.set && param.name === plan.set.param && setKeys ? ` · ${formatCount(setKeys.keys.length)} now` : ""}
                </span>
              </div>
            ))}
            {withUniqueKeys(plan.asks, p => p.name).map(([key, p]) => (
              <label key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                  {p.display_name || words(p.name)}{p.required && p.default_value == null ? "" : " · if you like"}
                </span>
                {isFlag(p.data_type) ? (
                  <Checkbox checked={asked[p.name] === true} aria-label={p.display_name || words(p.name)}
                    onChange={e => setAsked(a => ({ ...a, [p.name]: e.target.checked }))} />
                ) : (
                  <Input aria-label={p.display_name || words(p.name)} type={inputType(p.data_type)} value={String(asked[p.name] ?? "")}
                    placeholder={p.default_value ?? p.description ?? ""}
                    onChange={e => setAsked(a => ({ ...a, [p.name]: inputType(p.data_type) === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value }))} />
                )}
              </label>
            ))}
            <div className="aug-fs-xs" style={{ display: "flex", gap: 6, flexWrap: "wrap", color: "var(--t2)" }}>
              <span className="aug-tag">{declared.risk === "high" ? "high risk · proposed for approval, each on its own" : declared.risk === "low" ? "low risk · runs at once" : "reads only"}</span>
              {runs > 1 && <span className="aug-tag">{formatCount(runs)} runs, each its own</span>}
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
              <Button size="sm" disabled={busy || !complete || runs === 0} data-testid="action-buttons-run" onClick={() => void run()}>
                {busy ? "Running…" : runs > 1 ? `${label} · ${formatCount(runs)}` : label}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </span>
  );
}
