"use client";
/**
 * B2 (Track B, roadmap 2026-08-01) — `ChainOfThought`, hand-vendored.
 *
 * Mirrors the component API of Vercel AI Elements' ChainOfThought family
 * (ChainOfThought / Header / Content / Step / SearchResults / SearchResult) on
 * OUR substrate: @base-ui/react Collapsible + the repo's design tokens. NEVER
 * `npx ai-elements add` — stock Elements is Radix + fails the css-var, token
 * and raw-element gates.
 *
 * This is the surface A4's `guard_receipt` frames render into (B2): each silent
 * correction the backend makes — a defanned join, a preflight rewrite, a pareto
 * trim, a grounded headline — becomes a visible step, which is how "restriction
 * becomes visible direction". The existing ThinkingTrace keeps owning the deep
 * investigation tree; this component is the lighter chat-turn organ.
 */
import * as React from "react";
import { Collapsible } from "@base-ui/react/collapsible";

import { cn } from "@/lib/utils";
import { Shimmer } from "@/components/ai-elements/shimmer";

// ── Root ─────────────────────────────────────────────────────────────────────

export function ChainOfThought({
  className,
  defaultOpen = false,
  open,
  onOpenChange,
  children,
}: {
  className?: string;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <Collapsible.Root
      defaultOpen={defaultOpen}
      open={open}
      onOpenChange={onOpenChange}
      className={cn("not-prose", className)}
    >
      {children}
    </Collapsible.Root>
  );
}

// ── Header (the trigger) ─────────────────────────────────────────────────────

export function ChainOfThoughtHeader({
  children = "Chain of thought",
  streaming = false,
  className,
}: {
  children?: React.ReactNode;
  /** While true the label shimmers — the "thinking" affordance. */
  streaming?: boolean;
  className?: string;
}) {
  return (
    <Collapsible.Trigger
      className={cn(
        "group/cot flex w-full items-center gap-1.5 py-1 text-left",
        "aug-fs-xs cursor-pointer select-none aug-pressable",
        className,
      )}
      style={{ color: "var(--t3)" }}
    >
      <svg
        viewBox="0 0 12 12"
        aria-hidden
        className="h-3 w-3 shrink-0 transition-transform group-data-[panel-open]/cot:rotate-90"
        style={{ color: "var(--t4)" }}
      >
        <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5"
              strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <Shimmer active={streaming}>{children}</Shimmer>
    </Collapsible.Trigger>
  );
}

// ── Content (the panel) ──────────────────────────────────────────────────────

export function ChainOfThoughtContent({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Collapsible.Panel
      className={cn("overflow-hidden pl-1", className)}
    >
      <div
        className="ml-1 flex flex-col gap-0.5 border-l pl-3 py-1"
        style={{ borderColor: "var(--b1)" }}
      >
        {children}
      </div>
    </Collapsible.Panel>
  );
}

// ── Step ─────────────────────────────────────────────────────────────────────

export type ChainOfThoughtStepStatus = "complete" | "active" | "pending";

export function ChainOfThoughtStep({
  label,
  description,
  status = "complete",
  icon,
  children,
  className,
}: {
  label: React.ReactNode;
  description?: React.ReactNode;
  status?: ChainOfThoughtStepStatus;
  /** Optional leading glyph; the status dot renders when absent. */
  icon?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start gap-2 py-0.5 aug-anim-fade", className)}>
      <span className="mt-1 flex h-3 w-3 shrink-0 items-center justify-center">
        {icon ?? (
          <span
            className={cn("block h-1.5 w-1.5 rounded-[var(--r-pill)]",
                          status === "active" && "aug-anim-blink")}
            style={{
              background: status === "complete" ? "var(--grn2)"
                : status === "active" ? "var(--t2)" : "var(--bg-3)",
            }}
          />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="aug-fs-xs leading-snug"
             style={{ color: status === "pending" ? "var(--t4)" : "var(--t2)" }}>
          {status === "active" ? <Shimmer>{label}</Shimmer> : label}
        </div>
        {description && (
          <div className="aug-fs-xs leading-snug" style={{ color: "var(--t4)" }}>
            {description}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

// ── Search-result chips (Elements parity; also fits guard-receipt evidence) ──

export function ChainOfThoughtSearchResults({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("mt-1 flex flex-wrap items-center gap-1", className)}>
      {children}
    </div>
  );
}

export function ChainOfThoughtSearchResult({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn("inline-flex max-w-full items-center gap-1 truncate rounded-[var(--r2)] px-1.5 py-0.5 aug-fs-xs", className)}
      style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t3)" }}
    >
      {children}
    </span>
  );
}
