"use client";

/**
 * DS-1 · the palette — the canvas's vocabulary, on the canvas.
 *
 * Before this, adding a step meant clicking "Add Action", getting a `notify` row you did
 * not ask for, and changing its kind afterwards from a `<select>` that showed nine words
 * and explained none of them. The descriptions for those kinds had been written months
 * earlier and rendered nowhere. This panel is where they finally are.
 *
 * **It refuses to look the same on every deployment.** Each row carries the server's
 * reading of whether the object that kind REFERENCES exists here (`/automations/palette`),
 * so an install with no Slack bot sees "Post to Slack" dimmed with the sentence that says
 * why, instead of discovering it at save. That is §3.4's alt-door rule — a card offers the
 * door this deployment can open — applied one level down, to every entry.
 *
 * **Two add paths, one gate.** A row can be clicked (or Entered) and it appends; it can be
 * dragged and it lands where it was dropped. Both call the single `onAdd` the canvas owns,
 * because an affordance that adds by a path the gate does not know about is how a refusal
 * comes to disagree with itself. The placement arithmetic lives in `automationFlow.ts` —
 * jsdom cannot see geometry, so the part that is silently wrong by a viewport is pure.
 *
 * Search is a plain normalised substring over label · description · kind, not a fuzzy
 * index: the population is nine entries, and on nine items fuzziness returns noise a
 * reader has to discard rather than the near-miss tolerance it buys over hundreds
 * (`CommandPalette` has the Fuse index, and hundreds of rows to justify it).
 */
import React from "react";

import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { getAutomationPalette, type AutomationPaletteEntry } from "@/lib/api";

export type PaletteGroup = "trigger" | "action";

const GROUP_TITLE: Record<PaletteGroup, string> = {
  trigger: "Triggers",
  action: "Actions",
};

/** The panel is a fixed column beside the canvas; 232 keeps a two-word label and its
 *  badge on one line at 13px without the row wrapping, measured against the longest
 *  label the server offers ("Deliver briefing"). */
const PALETTE_W = 232;

function norm(s: string): string {
  return s.toLowerCase().normalize("NFKD");
}

function matches(entry: AutomationPaletteEntry, query: string): boolean {
  if (!query) return true;
  const q = norm(query);
  return norm(`${entry.label} ${entry.description} ${entry.kind}`).includes(q);
}

/** DS-1 P1 — where the query hit, as a rank. A substring match produces no fuzzy
 *  score, but it does produce a PLACE: a label that starts with the query beats one
 *  that merely contains it, which beats a hit buried in the description. Exported
 *  because a sort key that is wrong is invisible on nine rows and decisive on ninety. */
export function searchScore(entry: AutomationPaletteEntry, query: string): number {
  if (!query) return 0;
  const q = norm(query);
  const label = norm(entry.label);
  if (label.startsWith(q)) return 0;
  if (label.includes(q)) return 1;
  return 2;
}

/** DS-17b — a gated row ranks below every row this deployment can actually run.
 *
 *  Measured 2026-09-19: `trusted_query` ships at priority 90 and sorted after eight
 *  runnable kinds, so on a connection with no trusted queries its prereq sentence fell
 *  BELOW THE FOLD and the step read as a capability that does not exist — it was reported
 *  missing while it was shipping. The server already says which rows work here; the sort
 *  was the one reader that did not ask.
 *
 *  Availability, not priority, because `priority` is a CURATED order — the server's
 *  statement of which steps matter most — and it is right about that whether or not this
 *  connection can run them. The two facts compose; neither replaces the other. */
export function availabilityRank(entry: AutomationPaletteEntry): number {
  return entry.availability === "ready" ? 0 : 1;
}

/** The palette's sort: availability → search score → priority → name.
 *
 *  **Availability leads only while nothing is typed.** A query is the person naming the
 *  thing they want, and ranking a gated exact match under a ready description hit would be
 *  this same defect in new clothes — a row you asked for, pushed down for a reason you did
 *  not ask about. With a query, relevance leads and availability moves nothing.
 *
 *  🔑 **Relevance now sits ABOVE priority, and that is a second defect this wave found.**
 *  The previous order was priority → search score → name, so a curated weight decided
 *  before the query did: typing "trusted" ranked the priority-10 "Notify" (which merely
 *  says *trusted* in its description) above the priority-90 "Trusted query" the person had
 *  just named. Search barely reordered anything. It is inert while nothing is typed —
 *  `searchScore` is 0 for every row on an empty query — so this changes exactly the case it
 *  is about, which is why it is safe to take here rather than as its own wave. */
export function ordered(
  entries: AutomationPaletteEntry[], query: string,
): AutomationPaletteEntry[] {
  return [...entries].sort((a, b) =>
    !query && availabilityRank(a) !== availabilityRank(b)
      ? availabilityRank(a) - availabilityRank(b)
    : searchScore(a, query) !== searchScore(b, query)
      ? searchScore(a, query) - searchScore(b, query)
    : a.priority !== b.priority ? a.priority - b.priority
      : a.label.localeCompare(b.label));
}

/** What a row hands to the canvas on a drag, and the smallest thing the add gate needs.
 *
 *  Deliberately not the whole entry: a payload carrying labels and availability would be
 *  a second copy of the server's answer, decided at drag time and acted on at drop time.
 *  The kind and its group are the only two facts placement turns on. */
export const PALETTE_DRAG_TYPE = "application/x-aughor-palette";

export interface PalettePlacement { kind: string; group: PaletteGroup }

/** Read a drop back, tolerating anything that is not ours. */
export function readPaletteDrag(data: string | null | undefined): PalettePlacement | null {
  if (!data) return null;
  try {
    const parsed = JSON.parse(data) as Partial<PalettePlacement>;
    if (!parsed?.kind || (parsed.group !== "trigger" && parsed.group !== "action")) return null;
    return { kind: parsed.kind, group: parsed.group };
  } catch {
    return null;
  }
}

interface RowProps {
  entry: AutomationPaletteEntry;
  onAdd: (placement: PalettePlacement) => void;
}

/** A row plus, when it is gated, the sentence that says why.
 *
 *  Extracted so the ready rows and the ones behind DS-17b's fold render through ONE path:
 *  two copies of this would be two chances for a gated row to lose the sentence that is
 *  its only door. */
function PaletteRowWithReason({ entry, onAdd }: RowProps) {
  return (
    <>
      <PaletteRow entry={entry} onAdd={onAdd} />
      {entry.availability !== "ready" && (
        // The reason sits UNDER its row rather than in a tooltip: it is the one thing a
        // reader needs in order to act, and a hover is not a place to put an instruction.
        <div
          className="aug-fs-xs"
          style={{ color: "var(--t3)", padding: "0 6px 6px", lineHeight: 1.45 }}
          data-testid={`palette-reason-${entry.kind}`}
        >
          {entry.reason}
        </div>
      )}
    </>
  );
}

function PaletteRow({ entry, onAdd }: RowProps) {
  const usable = entry.availability === "ready";
  const gives = entry.publishes === null ? "its outcome" : entry.publishes.join(", ");

  return (
    <div
      draggable={usable}
      onDragStart={(e) => {
        e.dataTransfer.setData(PALETTE_DRAG_TYPE,
          JSON.stringify({ kind: entry.kind, group: entry.group }));
        e.dataTransfer.effectAllowed = "copy";
      }}
      style={{
        display: "flex", alignItems: "center", gap: 7,
        padding: "5px 6px", marginBottom: 3,
        borderRadius: "var(--r2)",
        border: "1px solid var(--b1)",
        background: usable ? "var(--bg-2)" : "var(--bg-1)",
        opacity: usable ? 1 : 0.62,
        cursor: usable ? "grab" : "not-allowed",
      }}
      data-testid={`palette-row-${entry.kind}`}
    >
      <Icon name={entry.icon as IconName} size={14} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          className="aug-fs-sm"
          style={{
            color: "var(--t1)", fontWeight: 500,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
          title={entry.description}
        >
          {entry.label}
        </div>
        {/* The ports, in words. A reader deciding between two steps is usually deciding
            what the next one can bind to, and that is not visible until the node is on
            the canvas otherwise. */}
        {!!gives && usable && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            gives {gives}
          </div>
        )}
      </div>
      {usable && (
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={`Add ${entry.label} to the canvas`}
          onClick={() => onAdd({ kind: entry.kind, group: entry.group })}
        >
          <Icon name="plus" size={12} />
        </Button>
      )}
    </div>
  );
}

export interface AutomationPaletteProps {
  /** The automation's connection — scopes the objects that are themselves
   *  connection-scoped (subscriptions, monitors) when the server counts them. */
  connId?: string;
  /** Show only this group. The on-canvas "Add Trigger" / "Add Action" buttons open the
   *  palette already narrowed, which is what those buttons always meant. */
  only?: PaletteGroup;
  /** DS-1 P1 — an edge was dropped on empty canvas: show only steps that can CONSUME
   *  it (an input port exists), with a banner naming the value being offered. Triggers
   *  are out by construction — a trigger cannot take a binding — which is the
   *  "one trigger node" constraint surfaced as a filter instead of a refusal. */
  bindFilter?: { ref: string };
  /** ×-to-clear on the banner: drop the filter, keep the palette. */
  onClearBindFilter?: () => void;
  /** The ONE add gate — click and drop both arrive here (drop with a position). */
  onAdd: (placement: PalettePlacement, position?: { x: number; y: number }) => void;
  onClose: () => void;
}

export function AutomationPalette({ connId, only, bindFilter, onClearBindFilter,
                                    onAdd, onClose }: AutomationPaletteProps) {
  const [entries, setEntries] = React.useState<AutomationPaletteEntry[] | null>(null);
  const [failed, setFailed] = React.useState(false);
  const [query, setQuery] = React.useState("");
  /** DS-17b — which groups have their "needs setup" fold open. Per group, because
   *  triggers and actions are two lists and one shared flag would open a fold the
   *  reader did not touch. Collapsed by default: the fold exists to buy back the
   *  vertical space the prereq sentences were spending. */
  const [gatedOpen, setGatedOpen] = React.useState<Record<string, boolean>>({});
  const searchRef = React.useRef<HTMLInputElement>(null);

  // Not cached module-side, unlike the vocabulary: this document counts objects that a
  // reader can create in another tab, and a palette insisting you have no bots an hour
  // after you made one is worse than one request per open.
  React.useEffect(() => {
    let live = true;
    getAutomationPalette(connId)
      .then(rows => { if (live) { setEntries(rows); setFailed(false); } })
      .catch(() => { if (live) { setEntries([]); setFailed(true); } });
    return () => { live = false; };
  }, [connId]);

  React.useEffect(() => { searchRef.current?.focus(); }, []);

  // Switching halves clears the query. The panel stays mounted while the canvas's two
  // buttons swap `only` between them, so a search typed against Actions would otherwise
  // survive into Triggers and silently hide everything in it.
  React.useEffect(() => { setQuery(""); }, [only]);

  const groups: PaletteGroup[] = bindFilter ? ["action"]
    : only ? [only] : ["trigger", "action"];
  // Scoped to the half being SHOWN before the search is applied — found by driving it:
  // computing the empty state over every entry meant a query matching only the other
  // half ("channel", with Triggers open) rendered no rows, no heading and no message,
  // which reads as a broken panel rather than an empty result.
  const inScope = (entries ?? []).filter(e =>
    bindFilter ? (e.group === "action" && e.bindable.length > 0)
               : (!only || e.group === only));
  const shown = inScope.filter(e => matches(e, query));

  return (
    <div
      style={{
        width: PALETTE_W, flexShrink: 0, display: "flex", flexDirection: "column",
        border: "1px solid var(--border)", borderRadius: 8,
        background: "var(--bg-1)", overflow: "hidden",
      }}
      data-testid="automation-palette"
    >
      <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "6px 6px 4px" }}>
        <Input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
          placeholder="Search steps…"
          aria-label="Search the palette"
          className="aug-fs-sm"
          style={{ height: 26 }}
        />
        <Button variant="ghost" size="icon-xs" aria-label="Close the palette" onClick={onClose}>
          <Icon name="close" size={12} />
        </Button>
      </div>

      {bindFilter && (
        // The active filter, NAMED — a silently narrowed list reads as a small platform.
        <div
          className="aug-fs-xs"
          data-testid="palette-bind-banner"
          style={{ display: "flex", alignItems: "center", gap: 6, margin: "0 6px 4px",
            padding: "4px 7px", borderRadius: "var(--r2)",
            border: "1px solid color-mix(in srgb, var(--chart-2) 45%, transparent)",
            background: "color-mix(in srgb, var(--chart-2) 9%, var(--bg-1))",
            color: "var(--t2)" }}>
          <Icon name="link" size={11} />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            can bind <span style={{ fontFamily: "var(--font-mono)",
              color: "var(--chart-2)" }}>{bindFilter.ref}</span>
          </span>
          {onClearBindFilter && (
            <Button variant="ghost" size="icon-xs" aria-label="Clear the binding filter"
              style={{ marginLeft: "auto", width: 16, height: 16 }}
              onClick={onClearBindFilter}>
              <Icon name="close" size={10} />
            </Button>
          )}
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto", padding: "0 6px 6px" }}>
        {entries === null ? (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "6px 4px" }}>
            Loading…
          </div>
        ) : failed ? (
          // A palette that could not load must not read as a platform with nothing in it.
          <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "6px 4px" }}>
            Could not load the palette — the canvas still adds steps from the buttons above.
          </div>
        ) : (
          groups.map((group) => {
            const all = ordered(shown.filter(e => e.group === group), query);
            if (!all.length) return null;
            // DS-17b — the ranking alone did not fix what it was written for, and the
            // arithmetic says why: `trusted_query` is the 9th of 10 action rows under
            // BOTH orders, so the same eight rows precede it and it occupies the same
            // pixels. What pushed it past the fold was never its rank — it was the three
            // multi-line prereq sentences above it, which the ranking moves around but
            // does not remove. So the gated rows collapse behind one line that says how
            // many there are. The ranking is what makes them contiguous enough to.
            //
            // Not while SEARCHING: a row hidden inside a fold when the person typed its
            // name is the original defect with a lid on it.
            const collapsible = !query;
            const rows = collapsible ? all.filter(e => e.availability === "ready") : all;
            const gated = collapsible ? all.filter(e => e.availability !== "ready") : [];
            const open = gatedOpen[group] ?? false;
            return (
              <div key={group} style={{ marginTop: 4 }}>
                <div
                  className="aug-fs-xs"
                  style={{
                    color: "var(--t3)", textTransform: "uppercase",
                    letterSpacing: "0.06em", padding: "4px 4px 5px",
                  }}
                >
                  {GROUP_TITLE[group]}
                </div>
                {rows.map(entry => (
                  <PaletteRowWithReason key={entry.kind} entry={entry} onAdd={onAdd} />
                ))}
                {gated.length > 0 && (
                  <>
                    <button
                      type="button"
                      onClick={() => setGatedOpen(s => ({ ...s, [group]: !open }))}
                      aria-expanded={open}
                      className="aug-fs-xs"
                      data-testid={`palette-gated-toggle-${group}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 6, width: "100%",
                        padding: "5px 6px", marginTop: 2, marginBottom: 3,
                        borderRadius: "var(--r2)", border: "1px dashed var(--b1)",
                        background: "transparent", color: "var(--t3)", cursor: "pointer",
                        textAlign: "left",
                      }}
                    >
                      <Icon name={open ? "chevd" : "chevr"} size={11} />
                      {/* Counted and NAMED, because the number is the whole signal: a
                          reader who cannot see these still learns they exist, which is
                          exactly what the flat list failed to tell anyone. */}
                      <span>
                        {gated.length} {gated.length === 1 ? "step needs" : "steps need"} setup
                      </span>
                    </button>
                    {open && gated.map(entry => (
                      <PaletteRowWithReason key={entry.kind} entry={entry} onAdd={onAdd} />
                    ))}
                  </>
                )}
              </div>
            );
          })
        )}
        {entries !== null && !failed && !shown.length && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "6px 4px" }}>
            Nothing matches “{query}”.
          </div>
        )}
      </div>
    </div>
  );
}

export default AutomationPalette;
