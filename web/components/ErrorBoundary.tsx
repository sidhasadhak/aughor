"use client";
import { ErrorState } from "@/components/ui/states";

import React from "react";

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
      const label = this.props.label ?? "This panel";
      const message = this.state.error.message || "An unexpected error occurred while rendering.";
      // The universal error state: what failed, what it means, what to do — and Reload is not
      // the only door, because the message is what a ticket needs.
      return (
        <ErrorState
          kind="Render failed"
          what={`${label} could not be drawn.`}
          means={message}
          doors={[
            { label: "Reload", onClick: this.reset, primary: true },
            { label: "Copy the error", onClick: () => { void navigator.clipboard?.writeText(`${label}: ${message}`); } },
          ]}
          style={{ margin: 8 }}
        />
      );
    }
    return this.props.children;
  }
}
