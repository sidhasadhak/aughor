"use client";

/**
 * SE-5a — Quick Fix: a proposed repair, shown as a diff, applied only on request.
 *
 * The agent's repair loop earns its safety by EXECUTING its candidate and keeping it only
 * if the run improved. This path has no such check, so the review is the user's — which
 * is why the proposal arrives as a diff rather than as new editor contents. Three rules
 * follow from that and none of them are negotiable:
 *
 *   • Never auto-apply. The button is the consent.
 *   • Never run the proposal. The server does not either.
 *   • "No change" is shown as no change, not as an empty diff with an Apply button.
 *
 * The diff is `@codemirror/merge` for the same reason the version rail uses it: the user
 * is comparing two statements, and a prose summary of a SQL edit is a summary of the
 * thing they need to read literally.
 */
import { useEffect, useRef, useState } from "react";
import { MergeView } from "@codemirror/merge";
import { EditorState } from "@codemirror/state";
import { Button } from "@/components/ui/button";
import { aughorEditorTheme, aughorSyntaxHighlighting } from "@/components/query/editor/theme";
import { quickFixSql, type QuickFix } from "@/lib/api";

export function QuickFixPanel({
  connId,
  sql,
  error,
  onApply,
}: {
  connId: string;
  sql: string;
  error: string;
  /** Replace the editor's contents with the proposal. Called ONLY from Apply. */
  onApply: (proposed: string) => void;
}) {
  const [state, setState] = useState<"idle" | "loading" | "ready" | "none" | "failed">("idle");
  const [fix, setFix] = useState<QuickFix | null>(null);
  const [message, setMessage] = useState("");
  const host = useRef<HTMLDivElement | null>(null);
  const merge = useRef<MergeView | null>(null);

  // A new error means the previous proposal is about a statement that is no longer on
  // screen. Keeping it would offer to "fix" the last error against the current SQL.
  useEffect(() => { setState("idle"); setFix(null); }, [sql, error]);

  useEffect(() => {
    merge.current?.destroy();
    merge.current = null;
    if (state !== "ready" || !fix?.proposed_sql || !host.current) return;
    merge.current = new MergeView({
      a: { doc: sql, extensions: [EditorState.readOnly.of(true), aughorEditorTheme, aughorSyntaxHighlighting] },
      b: { doc: fix.proposed_sql, extensions: [EditorState.readOnly.of(true), aughorEditorTheme, aughorSyntaxHighlighting] },
      parent: host.current,
      collapseUnchanged: { margin: 2, minSize: 4 },
      orientation: "a-b",
      gutter: false,
      highlightChanges: true,
    });
    return () => { merge.current?.destroy(); merge.current = null; };
  }, [state, fix, sql]);

  useEffect(() => () => { merge.current?.destroy(); }, []);

  async function request() {
    setState("loading");
    try {
      const res = await quickFixSql(connId, sql, error);
      if (!res.changed || !res.proposed_sql) {
        setState("none");
        setMessage(res.diagnosis
          ? `No change proposed. ${res.diagnosis}`
          : "No change proposed — the repair model did not find a fix for this.");
        return;
      }
      setFix(res);
      setState("ready");
    } catch (e) {
      setState("failed");
      setMessage(e instanceof Error ? e.message : "Quick fix failed");
    }
  }

  if (state === "idle") {
    return (
      <Button
        variant="ghost" size="xs" className="aug-fs-ui"
        onClick={() => void request()}
        title="Ask for a proposed repair. It is shown as a diff and never applied on its own."
      >
        Quick fix
      </Button>
    );
  }

  if (state === "loading") {
    return <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>Proposing a fix…</span>;
  }

  if (state === "none" || state === "failed") {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          className="aug-fs-ui"
          style={{ color: state === "failed" ? "var(--red4)" : "var(--t3)" }}
        >
          {message}
        </span>
        <Button variant="ghost" size="xs" className="aug-fs-ui" onClick={() => setState("idle")}>
          Dismiss
        </Button>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex", flexDirection: "column", gap: 6, marginTop: 10,
        border: "1px solid var(--b1)", borderRadius: "var(--r2)", overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px" }}>
        <span className="aug-label" style={{ color: "var(--t3)" }}>Proposed fix</span>
        <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>{fix?.rationale}</span>
        <div style={{ flex: 1 }} />
        <Button
          variant="ghost" size="xs" className="aug-fs-ui"
          title="Replace the editor's contents with the proposal. It still will not run until you run it."
          onClick={() => { if (fix?.proposed_sql) onApply(fix.proposed_sql); setState("idle"); }}
        >
          Apply
        </Button>
        <Button variant="ghost" size="xs" className="aug-fs-ui" onClick={() => setState("idle")}>
          Reject
        </Button>
      </div>
      <div ref={host} style={{ maxHeight: 220, overflow: "auto" }} />
    </div>
  );
}
