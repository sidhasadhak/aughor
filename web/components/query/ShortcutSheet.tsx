"use client";

/**
 * SE-6 — the keys, where the keys are used.
 *
 * A verb nobody can find is a verb that does not exist. This wave added ten editor
 * commands, none of which appears on screen, and the codebase has already learned once
 * that a capability stalls at "shipped" rather than "leveraged" when its door is
 * missing. DataGrip solves this with a shortcuts reference; this is the same thing,
 * scoped to the keys this editor actually binds.
 *
 * Every row is a binding registered in `SqlEditorPane`. Adding a key there without a
 * row here leaves it undiscoverable — the two lists belong together, so keep them so.
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

/** ⌘ on a Mac, Ctrl everywhere else — read once, on the client only. */
function useModKey(): string {
  const [mod, setMod] = useState("Ctrl");
  useEffect(() => {
    if (typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || "")) setMod("⌘");
  }, []);
  return mod;
}

interface Group { title: string; keys: [string, string][] }

function groups(mod: string): Group[] {
  return [
    {
      title: "Run",
      keys: [
        [`${mod}↵`, "Run the selection, else the statement under the cursor"],
        [`${mod}⇧F`, "Format the selection, else the whole query"],
      ],
    },
    {
      title: "Write",
      keys: [
        ["⌥↵", "Actions for what is under the cursor — expand a wildcard, introduce an alias, rename, add a LIMIT"],
        [`${mod}J`, "Completion, live templates included — type sel, gb, cte, jn and press ↵"],
        ["Tab", "Move to the next hole in an expanded template"],
        [`${mod}/`, "Comment or uncomment the line"],
        [`⌥${mod}/`, "Block comment"],
      ],
    },
    {
      title: "Select",
      keys: [
        [`${mod}D`, "Add a caret at the next occurrence of the selection"],
        [`${mod}⇧L`, "Add a caret at every occurrence"],
        [`⌥${mod}↑ ↓`, "Add a caret on the line above or below"],
        ["⌥click", "Add a caret where you click"],
      ],
    },
    {
      title: "Find",
      keys: [
        [`${mod}F`, "Find and replace"],
        [`${mod}G`, "Go to line"],
      ],
    },
    {
      title: "Results",
      keys: [
        ["click · drag · ⇧click", "Select cells — the sum, average, min, max and distinct count appear above the grid"],
        ["⇧↵", "Open the focused cell in full"],
        [`${mod}C`, "Copy the selection as TSV"],
        [`${mod}A`, "Select every cell"],
      ],
    },
  ];
}

export function ShortcutSheet() {
  const [open, setOpen] = useState(false);
  const mod = useModKey();

  // Escape closes it, like every other overlay in the app.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <Button variant="ghost" size="xs" onClick={() => setOpen(true)}
        title="Keyboard shortcuts" data-testid="sql-shortcuts">
        <Icon name="key" size={14} />
      </Button>
      {open && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "var(--scrim)" }}
            onClick={() => setOpen(false)} />
          <div role="dialog" aria-label="Keyboard shortcuts" className="aug-fs-sm"
            style={{
              position: "fixed", zIndex: 61, top: "10vh", left: "50%", transform: "translateX(-50%)",
              width: "min(680px, 92vw)", maxHeight: "76vh", overflowY: "auto",
              background: "var(--bg-2)", border: "1px solid var(--b2)",
              borderRadius: "var(--r3)", boxShadow: "var(--shadow-md)", padding: "14px 18px 18px",
            }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
              <span className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>Keyboard</span>
              <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
                everything this editor binds, in one place
              </span>
              <span style={{ flex: 1 }} />
              <Button variant="ghost" size="xs" onClick={() => setOpen(false)} aria-label="Close">
                <Icon name="close" size={13} />
              </Button>
            </div>
            {groups(mod).map(g => (
              <div key={g.title} style={{ marginTop: 14 }}>
                <div className="aug-label" style={{ marginBottom: 4 }}>{g.title}</div>
                {g.keys.map(([k, what]) => (
                  <div key={k} style={{ display: "flex", gap: 12, padding: "3px 0", alignItems: "baseline" }}>
                    <kbd style={{
                      flexShrink: 0, minWidth: 92, fontFamily: "var(--font-mono)",
                      color: "var(--t1)", background: "var(--bg-3)", border: "1px solid var(--b1)",
                      borderRadius: "var(--r1)", padding: "1px 6px", textAlign: "center",
                    }}>{k}</kbd>
                    <span style={{ color: "var(--t3)" }}>{what}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}
