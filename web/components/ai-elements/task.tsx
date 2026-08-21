"use client";
/**
 * B3 (Track B, roadmap 2026-08-01) — `Task`, hand-vendored.
 *
 * Mirrors the component API of Vercel AI Elements' Task family (Task /
 * TaskTrigger / TaskContent / TaskItem / TaskItemFile) on OUR substrate:
 * @base-ui/react Collapsible + the repo's design tokens. NEVER
 * `npx ai-elements add`.
 *
 * The organ this upgrades: PlanGateCard's phase list and the scattered
 * "N of M" progress rows — a unit of agent work with a status glyph, a
 * collapsible detail list, and file/entity chips.
 */
import * as React from "react";
import { Collapsible } from "@base-ui/react/collapsible";

import { cn } from "@/lib/utils";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Icon } from "@/components/ui/icon";

export type TaskStatus = "pending" | "in_progress" | "completed" | "error";

function StatusGlyph({ status }: { status: TaskStatus }) {
  if (status === "completed") {
    return (
      <span className="shrink-0 inline-flex" style={{ color: "var(--grn2)" }}><Icon name="check" size={12} /></span>
    );
  }
  if (status === "error") {
    return (
      <span className="shrink-0 inline-flex" style={{ color: "var(--red2)" }}><Icon name="close" size={12} /></span>
    );
  }
  if (status === "in_progress") {
    return (
      <span className="shrink-0 inline-flex" style={{ color: "var(--t3)" }}>
        <Icon name="spinner" size={12} className="aug-anim-spin" />
      </span>
    );
  }
  return (
    <span className="flex h-3 w-3 shrink-0 items-center justify-center">
      <span className="block h-1.5 w-1.5 rounded-[var(--r-pill)]" style={{ background: "var(--bg-3)" }} />
    </span>
  );
}

export function Task({
  className,
  defaultOpen = false,
  children,
}: {
  className?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Collapsible.Root defaultOpen={defaultOpen} className={cn("not-prose", className)}>
      {children}
    </Collapsible.Root>
  );
}

export function TaskTrigger({
  title,
  status = "pending",
  className,
}: {
  title: React.ReactNode;
  status?: TaskStatus;
  className?: string;
}) {
  return (
    <Collapsible.Trigger
      className={cn(
        "group/task flex w-full items-center gap-2 py-1 text-left",
        "aug-fs-xs cursor-pointer select-none aug-pressable",
        className,
      )}
      style={{ color: "var(--t3)" }}
    >
      <StatusGlyph status={status} />
      {status === "in_progress" ? <Shimmer>{title}</Shimmer> : <span className="truncate">{title}</span>}
      <span className="ml-auto shrink-0 inline-flex" style={{ color: "var(--t4)" }}>
        <Icon name="chevd" size={12}
          className="transition-transform group-data-[panel-open]/task:rotate-180" />
      </span>
    </Collapsible.Trigger>
  );
}

export function TaskContent({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Collapsible.Panel className={cn("overflow-hidden", className)}>
      <div
        className="ml-1.5 flex flex-col gap-0.5 border-l pl-3.5 py-1"
        style={{ borderColor: "var(--b1)" }}
      >
        {children}
      </div>
    </Collapsible.Panel>
  );
}

export function TaskItem({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("aug-fs-xs leading-snug aug-anim-fade", className)} style={{ color: "var(--t4)" }}>
      {children}
    </div>
  );
}

/** An inline file/entity chip inside a TaskItem sentence. */
export function TaskItemFile({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn("inline-flex max-w-full items-center gap-1 truncate rounded-[var(--r2)] px-1 py-px aug-fs-xs align-middle", className)}
      style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t3)" }}
    >
      {children}
    </span>
  );
}
