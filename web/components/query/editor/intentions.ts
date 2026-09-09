/**
 * SE-6 — intentions: DataGrip's ⌥⏎, in CodeMirror.
 *
 * The idea DataGrip gets right is that the editor should offer the small rewrites you
 * would otherwise do by hand, IN PLACE, and offer only the ones that apply where the
 * caret actually is. So this is a *context* menu in the literal sense: `Expand
 * wildcard` appears when the statement selects `*` and the catalog knows the columns;
 * `Introduce alias` appears when the caret is on an un-aliased table; `Rename` appears
 * when it is on an identifier the statement uses more than once. Nothing is offered
 * that cannot be carried out.
 *
 * Rendered as a CodeMirror tooltip rather than as completions. A completion popup is
 * for "what could I type here"; this is "what should the editor do to what is already
 * here", and mixing the two makes both harder to scan. The tooltip owns its own
 * keyboard handling while it is open (↑ ↓ ⏎ Esc) at `Prec.highest`, so the list
 * responds before the editor's own bindings see the key.
 *
 * Every action is ONE `dispatch` — therefore one undo step, and ⌘Z puts the document
 * back exactly as it was. An intention that leaves half of itself behind on undo is a
 * worse trade than not offering it.
 */
import {
  EditorSelection, Prec, StateEffect, StateField, type Extension,
} from "@codemirror/state";
import {
  EditorView, keymap, showTooltip, type Tooltip,
} from "@codemirror/view";
import {
  identifierAt, identifierOccurrences, selectStar, statementRangeAt,
  suggestAlias, tableRefs,
} from "@/lib/query/sqlText";

export interface Intention {
  id: string;
  label: string;
  detail?: string;
  run: (view: EditorView) => void;
}

/** The schema the editor already holds for completion: `{ "schema.table": [col, …] }`.
 *  Wildcard expansion needs exactly this and nothing more. */
export type SchemaMap = Record<string, string[]>;

/** One detected relationship, as the rich schema reports it. Both directions matter:
 *  the query may already hold either side. */
export interface JoinHint { t1: string; c1: string; t2: string; c2: string; match?: string }

// ── Finding the columns of a written table name ──────────────────────────────

/** Resolve a table as WRITTEN (`orders`, `main.orders`, `"Orders"`) against the
 *  completion schema, which is keyed however the catalog qualified it. Matching is
 *  case-insensitive on the bare name and prefers an exact key, so a two-part write
 *  never silently resolves to a same-named table in another schema when the exact
 *  key exists. */
export function columnsFor(schema: SchemaMap, written: string): string[] | null {
  const clean = written.replace(/["`[\]]/g, "");
  if (schema[clean]) return schema[clean];
  const lower = clean.toLowerCase();
  const keys = Object.keys(schema);
  const exact = keys.find(k => k.toLowerCase() === lower);
  if (exact) return schema[exact];
  const bare = lower.split(".").pop()!;
  const tail = keys.filter(k => k.toLowerCase().split(".").pop() === bare);
  // Ambiguous — two schemas hold a table of that name and the query did not say
  // which. Offering one of them would be a guess presented as a fact.
  return tail.length === 1 ? schema[tail[0]] : null;
}

// ── The intentions ───────────────────────────────────────────────────────────

/** How this engine writes an identifier that needs quoting. Supplied by the editor,
 *  which is the only layer that knows the connection's dialect. */
export type QuoteFn = (name: string) => string;

/** The bare table name, unqualified and unquoted — the key both the schema map and the
 *  join hints can be matched on without either having to re-encode the other's spelling. */
function bareName(name: string): string {
  return name.split(".").pop()!.replace(/["`[\]]/g, "").toLowerCase();
}

export function intentionsAt(
  view: EditorView, schema: SchemaMap, quote: QuoteFn = n => n, joins: JoinHint[] = [],
): Intention[] {
  const doc = view.state.doc.toString();
  const pos = view.state.selection.main.head;
  const stmt = statementRangeAt(doc, pos);
  const text = doc.slice(stmt.from, stmt.to);
  if (!text.trim()) return [];
  const refs = tableRefs(text, stmt.from);
  const out: Intention[] = [];

  // ── Expand wildcard ────────────────────────────────────────────────────────
  const star = selectStar(text);
  if (star) {
    const target = star.qualifier
      ? refs.find(r => (r.alias ?? r.name.split(".").pop()) === star.qualifier)
      : refs.length === 1 ? refs[0] : null;
    const cols = target ? columnsFor(schema, target.name) : null;
    if (target && cols && cols.length) {
      // Qualify only when the query itself qualifies — a single-table SELECT reads
      // better bare, and a joined one is ambiguous without the prefix.
      const prefix = star.qualifier ?? (refs.length > 1 ? (target.alias ?? target.name) : "");
      // Quoted where the name needs it: `Row ID` and `Sub-Category` are real column
      // names in the demo data, and an expansion that pasted them bare would produce
      // SQL that does not parse.
      const list = cols.map(c => (prefix ? `${prefix}.${quote(c)}` : quote(c))).join(", ");
      out.push({
        id: "expand-wildcard",
        label: "Expand wildcard",
        detail: `${cols.length} column${cols.length === 1 ? "" : "s"} of ${target.name}`,
        run: v => v.dispatch({
          changes: { from: stmt.from + star.range.from, to: stmt.from + star.range.to, insert: list },
          scrollIntoView: true,
        }),
      });
    }
  }

  // ── Introduce alias ────────────────────────────────────────────────────────
  // Offered for the table the caret is on, else for the only un-aliased table.
  const onRef = refs.find(r => pos >= r.range.from && pos <= r.range.to);
  const bare = refs.filter(r => !r.alias);
  const aliasTarget = onRef && !onRef.alias ? onRef : bare.length === 1 ? bare[0] : null;
  if (aliasTarget) {
    const taken = new Set(refs.map(r => r.alias).filter(Boolean) as string[]);
    const alias = suggestAlias(aliasTarget.name, taken);
    const shortName = aliasTarget.name.split(".").pop()!;
    out.push({
      id: "introduce-alias",
      label: `Introduce alias "${alias}"`,
      detail: `and qualify this statement's references to ${shortName}`,
      run: v => {
        // One dispatch: the alias, plus every bare reference to the table it now
        // covers. Two dispatches would be two undo steps, and undoing half of a
        // rename leaves a statement that does not run.
        const changes: { from: number; to: number; insert: string }[] = [
          { from: aliasTarget.range.to, to: aliasTarget.range.to, insert: ` ${alias}` },
        ];
        for (const occ of identifierOccurrences(text, shortName, stmt.from)) {
          if (occ.from >= aliasTarget.range.from && occ.to <= aliasTarget.range.to) continue;
          const after = doc.slice(occ.to, occ.to + 1);
          if (after === ".") changes.push({ from: occ.from, to: occ.to, insert: alias });
        }
        changes.sort((a, b) => a.from - b.from);
        v.dispatch({ changes, scrollIntoView: true });
      },
    });
  }

  // ── Rename ─────────────────────────────────────────────────────────────────
  const ident = identifierAt(doc, pos);
  if (ident && ident.range.from >= stmt.from && ident.range.to <= stmt.to) {
    const hits = identifierOccurrences(text, ident.text, stmt.from);
    if (hits.length > 1) {
      out.push({
        id: "rename",
        label: `Rename "${ident.text}"`,
        detail: `${hits.length} occurrences in this statement — edits them together`,
        run: v => renameInPlace(v, ident.text, hits),
      });
    }
  }

  // ── Join a related table ───────────────────────────────────────────────────
  //
  // DataGrip's most-used completion is the one that writes the ON clause for you from
  // the foreign key. Ours reads the same relationships the catalog already detected, so
  // the join it writes is the join the rail draws as `⋈`, not a guess made from column
  // names at the moment you asked.
  if (refs.length && /\bfrom\b/i.test(text)) {
    const present = new Map(refs.map(r => [bareName(r.name), r]));
    const seen = new Set<string>();
    for (const j of joins) {
      // Which side is already in the query, and which one would be new.
      const pairs: [string, string, string, string][] = [
        [j.t1, j.c1, j.t2, j.c2],
        [j.t2, j.c2, j.t1, j.c1],
      ];
      for (const [have, haveCol, want, wantCol] of pairs) {
        const anchor = present.get(bareName(have));
        if (!anchor || present.has(bareName(want))) continue;
        const key = `${bareName(want)}:${wantCol}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const left = anchor.alias ?? anchor.name;
        const alias = suggestAlias(want, new Set([
          ...refs.map(r => r.alias).filter(Boolean) as string[],
          ...[...present.keys()],
        ]));
        const clause = `\nJOIN ${want} ${alias} ON ${alias}.${quote(wantCol)} = ${left}.${quote(haveCol)}`;
        out.push({
          id: `join-${bareName(want)}`,
          label: `Join ${want}`,
          detail: `ON ${alias}.${wantCol} = ${left}.${haveCol}`,
          run: v => {
            // Inserted after the FROM clause, before WHERE/GROUP/ORDER — a JOIN placed
            // after a WHERE is a syntax error, and appending at the end of the
            // statement is how you get one.
            const tail = /\b(where|group\s+by|having|qualify|window|order\s+by|limit|offset|fetch)\b/i.exec(text);
            const at = stmt.from + (tail ? tail.index : text.length);
            v.dispatch({
              changes: { from: at, to: at, insert: tail ? `${clause}\n` : clause },
              scrollIntoView: true,
            });
          },
        });
      }
    }
  }

  // ── Add a LIMIT ────────────────────────────────────────────────────────────
  if (/^\s*(select|with)\b/i.test(text) && !/\blimit\b/i.test(text) && !/\bfetch\s+first\b/i.test(text)) {
    out.push({
      id: "add-limit",
      label: "Add LIMIT 100",
      detail: "cap what comes back while you are still shaping the query",
      run: v => v.dispatch({
        changes: { from: stmt.to, to: stmt.to, insert: "\nLIMIT 100" },
        selection: { anchor: stmt.to + 10 },
        scrollIntoView: true,
      }),
    });
  }

  // ── Wrap in a CTE ──────────────────────────────────────────────────────────
  if (/^\s*select\b/i.test(text)) {
    out.push({
      id: "wrap-cte",
      label: "Wrap in a CTE",
      detail: "make this statement the first step of a longer one",
      run: v => {
        const indented = text.split("\n").map(l => (l ? `  ${l}` : l)).join("\n");
        const next = `WITH base AS (\n${indented}\n)\nSELECT *\nFROM base`;
        v.dispatch({
          changes: { from: stmt.from, to: stmt.to, insert: next },
          selection: { anchor: stmt.from + 5, head: stmt.from + 9 },   // select `base`
          scrollIntoView: true,
        });
      },
    });
  }

  // ── Count instead ──────────────────────────────────────────────────────────
  const selMatch = /^\s*select\b/i.exec(text);
  const fromMatch = /\bfrom\b/i.exec(text);
  if (selMatch && fromMatch && !/\bcount\s*\(/i.test(text.slice(0, fromMatch.index))) {
    out.push({
      id: "count-instead",
      label: "Count the rows instead",
      detail: "replaces the select list with COUNT(*)",
      run: v => v.dispatch({
        changes: {
          from: stmt.from + selMatch[0].length,
          to: stmt.from + fromMatch.index,
          insert: " COUNT(*) ",
        },
        scrollIntoView: true,
      }),
    });
  }

  return out;
}

// ── Rename: a real multi-caret edit, not a find/replace ──────────────────────

/** Put a caret on every occurrence and select them all. Typing then replaces all of
 *  them at once — which is what DataGrip's inline rename feels like, and unlike a
 *  find/replace it stays previewable and undoable as one action. */
function renameInPlace(view: EditorView, _name: string, hits: { from: number; to: number }[]) {
  const ranges = hits.map(h => EditorSelection.range(h.from, h.to));
  view.dispatch({
    selection: EditorSelection.create(ranges, ranges.length - 1),
    scrollIntoView: true,
  });
  view.focus();
}

// ── The menu ─────────────────────────────────────────────────────────────────

interface MenuState { items: Intention[]; cursor: number; pos: number }

/** Opening the menu carries the caret position with it. The tooltip has to name a
 *  document position when it renders, and the field is the only thing that knows
 *  where the menu was summoned from — reading the selection at render time would
 *  move the menu whenever anything else touched the selection. */
const setMenu = StateEffect.define<MenuState | null>();
const moveCursor = StateEffect.define<number>();

const menuField = StateField.define<MenuState | null>({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) {
      if (e.is(setMenu)) return e.value;
      if (e.is(moveCursor) && value) {
        const n = value.items.length;
        return { ...value, cursor: (value.cursor + e.value + n) % n };
      }
    }
    // Any edit or caret move invalidates the menu: its actions were computed for a
    // position that no longer holds.
    if (tr.docChanged || tr.selection) return null;
    return value;
  },
  provide: f => showTooltip.from(f, v => (v ? renderMenu(v) : null)),
});

function renderMenu(state: MenuState): Tooltip {
  return {
    pos: state.pos,
    above: false,
    arrow: false,
    create: (view) => {
      const dom = document.createElement("div");
      dom.className = "cm-aug-intentions";
      dom.setAttribute("role", "listbox");
      dom.setAttribute("aria-label", "Editor actions");
      state.items.forEach((item, i) => {
        const row = document.createElement("div");
        row.className = "cm-aug-intention" + (i === state.cursor ? " cm-aug-intention-active" : "");
        row.setAttribute("role", "option");
        row.setAttribute("aria-selected", String(i === state.cursor));
        const label = document.createElement("span");
        label.className = "cm-aug-intention-label";
        label.textContent = item.label;
        row.appendChild(label);
        if (item.detail) {
          const det = document.createElement("span");
          det.className = "cm-aug-intention-detail";
          det.textContent = item.detail;
          row.appendChild(det);
        }
        row.addEventListener("mousedown", (e) => {
          e.preventDefault();                  // keep focus in the editor
          view.dispatch({ effects: setMenu.of(null) });
          item.run(view);
          view.focus();
        });
        dom.appendChild(row);
      });
      return { dom };
    },
  };
}

const menuKeymap = Prec.highest(keymap.of([
  {
    key: "ArrowDown",
    run: v => { if (!v.state.field(menuField)) return false; v.dispatch({ effects: moveCursor.of(1) }); return true; },
  },
  {
    key: "ArrowUp",
    run: v => { if (!v.state.field(menuField)) return false; v.dispatch({ effects: moveCursor.of(-1) }); return true; },
  },
  {
    key: "Enter",
    run: v => {
      const m = v.state.field(menuField);
      if (!m) return false;
      const item = m.items[m.cursor];
      v.dispatch({ effects: setMenu.of(null) });
      item?.run(v);
      return true;
    },
  },
  {
    key: "Escape",
    run: v => { if (!v.state.field(menuField)) return false; v.dispatch({ effects: setMenu.of(null) }); return true; },
  },
]));

/** The extension. `getSchema` is a thunk because the schema arrives after mount and
 *  changes with the connection, while the extension is built once — reading it
 *  through a function is what keeps the editor from being rebuilt on every
 *  catalog refresh (which would discard undo history and the cursor). */
export function sqlIntentions(
  getSchema: () => SchemaMap, getQuote: () => QuoteFn, getJoins: () => JoinHint[] = () => [],
): Extension {
  return [
    menuField,
    menuKeymap,
    Prec.highest(keymap.of([{
      key: "Alt-Enter",
      preventDefault: true,
      run: v => {
        if (v.state.field(menuField)) { v.dispatch({ effects: setMenu.of(null) }); return true; }
        const items = intentionsAt(v, getSchema(), getQuote(), getJoins());
        if (!items.length) return true;        // swallow the key; nothing applies here
        v.dispatch({ effects: setMenu.of({ items, cursor: 0, pos: v.state.selection.main.head }) });
        return true;
      },
    }])),
    EditorView.theme({
      ".cm-aug-intentions": {
        background: "var(--bg-2)",
        border: "1px solid var(--b2)",
        borderRadius: "var(--r2)",
        boxShadow: "var(--shadow-md)",
        padding: "4px",
        maxWidth: "440px",
        fontFamily: "var(--font-ui)",
      },
      ".cm-aug-intention": {
        display: "flex",
        alignItems: "baseline",
        gap: "8px",
        padding: "5px 9px",
        borderRadius: "var(--r1)",
        cursor: "pointer",
        color: "var(--t2)",
      },
      ".cm-aug-intention-active": { background: "var(--bg-sel)", color: "var(--t1)" },
      ".cm-aug-intention-label": { fontSize: "var(--aug-fs-sm)", whiteSpace: "nowrap" },
      ".cm-aug-intention-detail": {
        fontSize: "var(--aug-fs-xs)", color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis",
      },
    }),
  ];
}

export { setMenu as setIntentionMenu, menuField as intentionMenuField };
