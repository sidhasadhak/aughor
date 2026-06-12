"use client";

/**
 * A tiny app-wide channel for "Open in Query Builder".
 *
 * Insights and Deep Analysis render a generated query's chart/table deep inside
 * their own component trees (DomainIntelPanel via IntelligenceWorkspace, the ADA
 * report via ChatMessage / HistoryDetailPanel). Rather than prop-drill a handler
 * through every layer, the app root provides one function via context; any leaf
 * calls useOpenInBuilder()(sql, connId?) to hand a query off to the builder.
 *
 * connId is optional — when omitted the handler defaults to the currently selected
 * connection (which is the one the insight/investigation was produced against).
 */

import { createContext, useContext } from "react";

export type OpenInBuilder = (sql: string, connId?: string) => void;

const OpenInBuilderCtx = createContext<OpenInBuilder | null>(null);

export const OpenInBuilderProvider = OpenInBuilderCtx.Provider;

/** Returns the open-in-builder handler, or null when no provider is mounted. */
export function useOpenInBuilder(): OpenInBuilder | null {
  return useContext(OpenInBuilderCtx);
}
