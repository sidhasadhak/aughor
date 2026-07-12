"use client";

import React from "react";
import { Button } from "@/components/ui/button";

interface Props {
  children: React.ReactNode;
  /** What failed, e.g. "This panel" / "This answer" — used in the fallback copy. */
  label?: string;
  /** Ran after the user clicks Reload (in addition to clearing the boundary). */
  onReset?: () => void;
}

interface State {
  error: Error | null;
}

/**
 * WP-2 — a render-time error in any single panel or chat turn used to white-screen the
 * whole SPA (there was no boundary anywhere). This isolates a throw to its own subtree:
 * the rest of the app keeps working, and the user can retry the failed piece. React error
 * boundaries must be class components (no hook equivalent for componentDidCatch).
 */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Never swallow silently — a boundary that hides the cause is its own bug.
    console.error("[ErrorBoundary] render failure:", error, info?.componentStack);
  }

  private reset = (): void => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            alignItems: "flex-start",
            margin: 8,
            padding: "12px 14px",
            borderRadius: 8,
            border: "1px solid var(--red3)",
            background: "var(--bg-1)",
            color: "var(--t1)",
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600 }}>
            {this.props.label ?? "Something went wrong"}
          </div>
          <div style={{ fontSize: 12, color: "var(--t2)", wordBreak: "break-word" }}>
            {this.state.error.message || "An unexpected error occurred while rendering."}
          </div>
          <Button variant="outline" size="sm" onClick={this.reset}>
            Reload
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
