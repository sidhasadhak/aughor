"use client";

/**
 * DS-4 · which key of an open-set outcome fills this field.
 *
 * A declared-action step publishes whatever its own action's outcome carries, so
 * `PUBLISHED_KEYS` declares that set OPEN (`null`) and `validate_chain` accepts a binding
 * onto it unchecked rather than wrongly refusing one. The canvas used to close that gap
 * with `window.prompt`: homely, and blind — a typo produced an edge that draws correctly
 * and is skipped at 09:00, which is the exact failure B1 existed to end one field over.
 *
 * So the drop parks the connection and this asks, offering **the keys the step has
 * actually been seen to publish** (the server already computes `produced` from the real
 * outcomes) with a typed tail for the ones it has not. The tail is not a cop-out: the set
 * is open by declaration and the executor's dispatcher is injectable, so a key nobody has
 * observed is a legitimate thing to bind.
 *
 * Its own component, not inline on the canvas, for the reason `AutomationRows` was
 * extracted: what a test must be able to drive should not require mounting a canvas that
 * jsdom cannot measure.
 */
import React from "react";

import { Button } from "@/components/ui/button";

export interface OutcomeKeyPickerProps {
  /** The step whose outcome is being read — its alias, as the binding will name it. */
  from: string;
  /** The field on the downstream step the key will fill. */
  field: string;
  /** Keys this step has been seen to publish. `null` while that is still being looked
   *  up, `[]` when it has never run — two different sentences, never one. */
  candidates: string[] | null;
  onPick: (key: string) => void;
  onCancel: () => void;
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "6px 9px", borderRadius: "var(--r2)",
  border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
};

export function OutcomeKeyPicker({
  from, field, candidates, onPick, onCancel,
}: OutcomeKeyPickerProps) {
  const [typed, setTyped] = React.useState("");
  const offered = candidates ?? [];

  const commit = (key: string) => {
    const trimmed = key.trim();
    if (trimmed) onPick(trimmed);
  };

  return (
    <div
      data-testid="outcome-key-picker"
      style={{
        background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: 8,
        padding: "10px 12px", maxWidth: 340, boxShadow: "0 8px 24px rgba(0,0,0,.28)",
      }}
    >
      <div className="aug-fs-sm" style={{ color: "var(--t1)", marginBottom: 7 }}>
        Which key of <strong>{from}</strong>’s outcome fills <strong>{field}</strong>?
      </div>

      {offered.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 7 }}>
          {offered.map(key => (
            <Button key={key} variant="secondary" size="xs"
              onClick={() => commit(key)}>
              {key}
            </Button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 4 }}>
        <input
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); commit(typed); }
            if (e.key === "Escape") { e.preventDefault(); onCancel(); }
          }}
          placeholder="or type a key"
          aria-label="Outcome key"
          style={{ ...inputStyle, flex: 1 }}
        />
        <Button variant="default" size="xs" disabled={!typed.trim()}
          onClick={() => commit(typed)}>
          Bind
        </Button>
        <Button variant="ghost" size="xs" onClick={onCancel}>Cancel</Button>
      </div>

      <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 6 }}>
        {candidates === null
          ? "looking up what this step has published…"
          : offered.length
            ? "keys it published on its last run — a declared action may carry others"
            : "this step has not run here yet, so its keys are not known — type the one "
              + "the action returns"}
      </div>
    </div>
  );
}

export default OutcomeKeyPicker;
