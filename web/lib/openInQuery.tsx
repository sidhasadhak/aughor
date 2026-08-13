"use client";

/**
 * SE-2 PR E — the app-wide "open this SQL in the Query surface" channel.
 *
 * Generalises `openInBuilder`, which could only ever mean the VISUAL builder because
 * that was the only place SQL could land. Now that the workbench has two modes, the
 * caller says which one it wants: a generated query from a finding is usually best
 * read as SQL, while a query the user will reshape belongs in the composer.
 *
 * `mode` is optional and defaults to undefined — meaning "the workbench's own
 * default" rather than a silent "visual". Callers that genuinely do not care should
 * not be forced to pick, and the workbench's default is the one place that decision
 * belongs.
 *
 * The context shape is unchanged in spirit: leaves call the hook rather than having a
 * handler prop-drilled through IntelligenceWorkspace / ChatMessage / HistoryDetailPanel.
 */
import { createContext, useContext } from "react";

export type QueryTargetMode = "visual" | "sql";

export interface OpenInQueryRequest {
  sql: string;
  /** Defaults to the currently selected connection — the one the finding ran against. */
  connId?: string;
  /** Which workbench mode to land in. Omit to take the workbench's default. */
  mode?: QueryTargetMode;
}

export type OpenInQuery = (req: OpenInQueryRequest) => void;

const OpenInQueryCtx = createContext<OpenInQuery | null>(null);

export const OpenInQueryProvider = OpenInQueryCtx.Provider;

/** The open-in-Query handler, or null when no provider is mounted. */
export function useOpenInQuery(): OpenInQuery | null {
  return useContext(OpenInQueryCtx);
}
