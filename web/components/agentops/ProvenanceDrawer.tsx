"use client";

/**
 * "Where this number comes from" — a right-hand drawer, opened by clicking any figure.
 *
 * A drawer rather than a modal, deliberately: the table and the chart the number came from
 * stay on screen beside it, which is the context a reader needs to judge what they are
 * being shown. A modal discards exactly that.
 *
 * Each panel supplies four things, and all four are load-bearing:
 *   definition  — what is counted, in the reader's words
 *   denominator — what it is out of (an error RATE with no base is not a measurement)
 *   coverage    — what fraction of the population could even have carried the fact
 *   the list    — the rows whose count equals this figure
 *
 * The last one is the promise the surface makes: every number is a door. A tile showing 24
 * that opens a list of 31 is worse than no tile, so the parity is a backend test, not a
 * hope (`test_agent_ops_endpoints.py::test_runs_tile_equals_the_agent_jobs_it_links_to`).
 */
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";

export type Provenance = {
  eyebrow: string;
  title: string;
  value: ReactNode;
  definition: string;
  denominator?: string;
  coverage?: string;
  window?: string;
  /** Extra rows rendered under the definition list. */
  facts?: Array<[string, ReactNode]>;
  /** The list this figure opens, and what it is. */
  open?: { label: string; hint: string; onOpen: () => void };
  /** A closing note — a caveat, a pointer, the reason a number is missing. */
  note?: string;
};

export function ProvenanceDrawer({ open, data, onClose }: {
  open: boolean;
  data: Provenance | null;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <aside role="dialog" aria-label="Where this number comes from" aria-hidden={!open}
      // `inert` keeps a closed drawer out of the tab order — a keyboard user should not
      // walk through a panel that is translated off screen.
      {...(!open ? { inert: "" as unknown as boolean } : {})}
      style={{
        position: "absolute", top: 0, right: 0, bottom: 0, width: 372, zIndex: 9,
        background: "var(--bg-1)", borderLeft: "1px solid var(--b2)",
        transform: open ? "none" : "translateX(100%)",
        transition: "transform var(--dur-norm) var(--ease-out)",
        display: "flex", flexDirection: "column",
        boxShadow: open ? "-20px 0 50px -30px rgba(0,0,0,.7)" : "none",
      }}>
      {data && (
        <>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "flex-start",
            gap: 10, padding: "14px 16px 10px", borderBottom: "1px solid var(--b1)",
          }}>
            <div style={{ minWidth: 0 }}>
              <div className="aug-label" style={{ color: "var(--t2)", marginBottom: 3 }}>{data.eyebrow}</div>
              <h4 className="aug-text-h3" style={{ margin: 0 }}>{data.title}</h4>
            </div>
            <Button ref={closeRef} variant="ghost" size="sm" onClick={onClose} aria-label="Close"
              style={{ height: 24, width: 24, padding: 0, color: "var(--t2)" }}>×</Button>
          </div>

          <div style={{ padding: "14px 16px", overflow: "auto", display: "flex",
                        flexDirection: "column", gap: 14 }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, lineHeight: 1,
                          color: "var(--t1)" }}>
              {data.value}
            </div>

            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "5px 12px",
                         margin: 0 }}>
              {data.window && <><Dt>Window</Dt><Dd mono>{data.window}</Dd></>}
              <Dt>Definition</Dt><Dd>{data.definition}</Dd>
              {data.denominator && <><Dt>Out of</Dt><Dd mono>{data.denominator}</Dd></>}
              {data.coverage && <><Dt>Coverage</Dt><Dd mono>{data.coverage}</Dd></>}
              {(data.facts ?? []).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}><Dt>{k}</Dt><Dd>{v}</Dd></span>
              ))}
            </dl>

            {data.open && (
              <Button variant="ghost" onClick={data.open.onOpen}
                style={{
                  display: "block", width: "100%", height: "auto", textAlign: "left",
                  background: "var(--blue1)", border: "1px solid var(--blue2)",
                  borderRadius: "var(--r3)", padding: "9px 11px", color: "var(--blue5)",
                  whiteSpace: "normal",
                }}>
                <span className="aug-fs-sm">{data.open.label}</span>
                <span className="aug-fs-xs" style={{ display: "block", color: "var(--blue4)", marginTop: 3 }}>
                  {data.open.hint}
                </span>
              </Button>
            )}

            {data.note && (
              <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: 0, lineHeight: 1.45 }}>
                {data.note}
              </p>
            )}
          </div>
        </>
      )}
    </aside>
  );
}

function Dt({ children }: { children: ReactNode }) {
  return <dt className="aug-fs-sm" style={{ color: "var(--t2)", margin: 0 }}>{children}</dt>;
}

function Dd({ children, mono }: { children: ReactNode; mono?: boolean }) {
  return (
    <dd className="aug-fs-sm" style={{
      margin: 0, color: "var(--t1)",
      fontFamily: mono ? "var(--font-mono)" : undefined,
    }}>{children}</dd>
  );
}
