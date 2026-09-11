"use client";

/**
 * ON-3 — the Standard Object View (ROADMAP §3.15): one object, read live through its backing.
 *
 * Zero configuration: everything on the page is what the object's type already declares and what
 * the warehouse answers now — its properties; its links, a to-one link opening the linked object
 * and a to-many link counted and listed a page at a time; the verified metrics compiled with this
 * object as the filter; the findings and answers whose SQL names its key; the notes on its row;
 * and the declared actions that take it, the key filled in. Nothing is inferred: a link the
 * compiler refuses says why and is not followed, a refused metric shows no number, and an action
 * is OFFERED here, never run from here (acting on objects is ON-4).
 */
import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { SqlResultTable } from "@/components/AugTable";
import { objectLinkRender, useObjectColumnLinks, useObjectKeyColumns } from "@/components/objects/objectColumnLinks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { SkeletonRows } from "@/components/ui/motion";
import { displayCellValue, formatCount, formatMetricValue, relTime } from "@/lib/format";
import { declaredActionsHref, objectHref } from "@/lib/objectLinks";
import {
  getLinkedObjects,
  getObjectPage,
  type LinkedObjectsPage,
  type ObjectAction,
  type ObjectCitation,
  type ObjectLink,
  type ObjectMetric,
  type ObjectMissing,
  type ObjectNote,
  type ObjectPage,
  type ObjectRefusal,
} from "@/lib/objects";

interface Scope {
  connectionId?: string;
  schemaName?: string;
}

const LINKED_PAGE = 25;
const NO_COLUMNS: string[] = [];
const RISK_TAG: Record<string, string> = { low: "aug-tag-green", medium: "aug-tag-amber", high: "aug-tag-red" };

const ROW_RULE = "1px solid var(--b1)";
const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function cellText(value: unknown): string {
  return value == null ? "—" : displayCellValue(value);
}

/** "a customer", "an order" — the noun as a sentence reads it. */
function withArticle(noun: string): string {
  return `${/^[aeiou]/i.test(noun) ? "an" : "a"} ${noun}`;
}

/** ON-3b — which property titles this page, and on what warrant: a person's declaration, a proposal from the
 *  profile, or the key when nothing else names the object (a refuted proposal says so on hover). */
function DisplayChip({ display }: { display: NonNullable<ObjectPage["display"]> }) {
  const warrant = display.source === "human" ? "declared" : display.source === "proposed" ? "proposed" : "the key";
  const measured = display.verified === true ? "measured: it names objects"
    : display.verified === false ? "measured: it does not name objects" : "not yet measured";
  const detail = [`Titled by ${display.property} — ${warrant}${display.source === "key" ? "" : `, ${measured}`}`, display.note]
    .filter(Boolean).join(". ");
  return (
    <span className="aug-tag aug-tag-gray" title={detail} data-testid="object-display-property"
      style={{ whiteSpace: "nowrap" }}>
      named by <span style={MONO}>{display.source === "key" ? "its key" : display.property}</span>
    </span>
  );
}

export function ObjectView({ objectType, pk, connectionId, schemaName }: {
  objectType: string;
  pk: string;
  connectionId?: string;
  schemaName?: string;
}) {
  const [loaded, setLoaded] = useState<ObjectPage | ObjectRefusal | ObjectMissing | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setLoaded(null);
    setError("");
    getObjectPage(objectType, pk, connectionId, schemaName)
      .then((page) => { if (live) setLoaded(page); })
      .catch((e: unknown) => { if (live) setError(errorText(e)); });
    return () => { live = false; };
  }, [objectType, pk, connectionId, schemaName, attempt]);

  useEffect(() => {
    if (loaded?.path === "object") document.title = `${loaded.type_name} ${loaded.title ?? loaded.pk} · Aughor`;
  }, [loaded]);

  const workbench = connectionId ? `/?conn=${encodeURIComponent(connectionId)}` : "/";
  const toWorkbench = (
    <Link href={workbench}><Button variant="outline" size="sm">Open the workbench</Button></Link>
  );

  let body: React.ReactNode;
  if (error) {
    body = (
      <EmptyState icon="alert" title="This object could not be read"
        action={<Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>}>
        {error}
      </EmptyState>
    );
  } else if (!loaded) {
    body = <div style={{ maxWidth: 1180, margin: "0 auto", padding: 24 }}><SkeletonRows rows={8} /></div>;
  } else if (loaded.path === "missing") {
    body = <EmptyState icon="search" title={`No ${objectType} ${pk}`} action={toWorkbench}>{loaded.detail}</EmptyState>;
  } else if (loaded.path === "refused") {
    body = (
      <EmptyState icon="info" title={`No object type “${objectType}” here`} action={toWorkbench}>
        {loaded.refused}
        {loaded.available.length > 0 && <> Object types: {loaded.available.join(", ")}.</>}
      </EmptyState>
    );
  } else {
    body = <ObjectBody page={loaded} scope={{ connectionId, schemaName }} />;
  }

  return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column", background: "var(--bg-0)", overflow: "hidden" }}>
      <div className="aug-content-header" style={{ minWidth: 0, overflow: "hidden" }}>
        <Link href={workbench} title="Back to the workbench">
          <Button variant="ghost" size="xs"><Icon name="back" size={14} />Workbench</Button>
        </Link>
        {loaded?.path === "object" ? (
          <>
            <span className="aug-tag aug-tag-blue">{loaded.type_name}</span>
            <span className="aug-fs-ui"
              style={{ color: "var(--t1)", fontWeight: 600, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {loaded.title ?? loaded.pk}
            </span>
            <span className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", whiteSpace: "nowrap" }}>
              {loaded.key} = {loaded.pk}
            </span>
            {loaded.display && <DisplayChip display={loaded.display} />}
          </>
        ) : (
          <span className="aug-fs-ui" style={{ color: "var(--t2)" }}>{objectType} {pk}</span>
        )}
        <div style={{ flex: 1 }} />
        {loaded && loaded.path !== "missing" && loaded.schema_name && (
          <span className="aug-fs-xs" style={{ color: "var(--t4)", whiteSpace: "nowrap" }}>{loaded.schema_name}</span>
        )}
      </div>
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>{body}</div>
    </div>
  );
}

function ObjectBody({ page, scope }: { page: ObjectPage; scope: Scope }) {
  const { related } = page;
  return (
    <div style={{ maxWidth: 1180, margin: "0 auto", padding: "20px 24px 40px" }}>
      {page.caveats.length > 0 && (
        <div className="aug-fs-sm"
          style={{ marginBottom: 16, padding: "8px 12px", borderRadius: "var(--r3)", border: "1px solid var(--amb2)",
                   background: "var(--amb1)", color: "var(--amb5)" }}>
          {page.caveats.map((caveat) => <div key={caveat}>{caveat}</div>)}
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(300px,2fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <PropertiesCard page={page} scope={scope} />
          <LinksCard page={page} scope={scope} />
          <CitationsCard page={page} citations={related.findings} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <ActionsCard page={page} actions={related.actions} scope={scope} />
          <MetricsCard page={page} metrics={related.metrics} />
          <NotesCard notes={related.notes} />
        </div>
      </div>
    </div>
  );
}

function Section({ title, description, children }: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-col">{children}</CardContent>
    </Card>
  );
}

/** What the card reads from the backing, from further bindings, and what accepted actions set on top — never one count. */
function propertiesSummary(page: ObjectPage): string {
  const set = page.properties.filter((p) => p.overlay).length;
  const bound = page.properties.filter((p) => p.binding);
  const through = [...new Set(bound.map((p) => p.binding?.name ?? ""))];
  const read = page.properties.length - set - bound.length;
  return `Read live through the ${page.type_name} backing — ${formatCount(read)} columns`
    + (bound.length ? `, ${formatCount(bound.length)} through the ${through.length === 1 ? "binding" : "bindings"} ${through.join(", ")}` : "")
    + (set ? `, and ${formatCount(set)} set by accepted actions.` : ".");
}

function PropertiesCard({ page, scope }: { page: ObjectPage; scope: Scope }) {
  // A property that names another object — an order's customer_id — opens that object.
  const objectColumns = useObjectKeyColumns(scope.connectionId);
  return (
    <Section title="Properties"
      description={propertiesSummary(page)}>
      <dl style={{ display: "grid", gridTemplateColumns: "minmax(120px, max-content) minmax(0, 1fr)", columnGap: 16, rowGap: 6, margin: 0 }}>
        {page.properties.map((p) => {
          const isKey = p.name.toLowerCase() === page.key.toLowerCase();
          const named = !isKey && p.value != null && p.value !== "" ? objectColumns.get(p.name.toLowerCase()) : undefined;
          return (
            <React.Fragment key={p.name}>
              <dt className="aug-fs-xs" title={p.description || p.name}
                style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 4 }}>
                {isKey && <Icon name="key" size={12} label="Key" />}
                {p.overlay && <Icon name="edit" size={12} label="Set by an accepted action" />}
                {p.display_name}
              </dt>
              <dd className="aug-fs-sm"
                style={{ margin: 0, overflowWrap: "anywhere", color: p.value == null ? "var(--t4)" : "var(--t1)",
                         ...(isKey ? MONO : {}) }}>
                {named ? (
                  <Link href={objectHref(named, String(p.value), scope.connectionId, scope.schemaName)}
                    style={{ ...MONO, color: "var(--blue3)" }} title={`Open ${named} ${String(p.value)}`}>
                    {String(p.value)}
                  </Link>
                ) : cellText(p.value)}
                {p.unit && p.value != null && <span style={{ color: "var(--t4)" }}> {p.unit}</span>}
                {p.overlay && (
                  <span className="aug-fs-xs" style={{ display: "block", color: "var(--t4)" }}>
                    {p.overlay.provenance}{p.overlay.note ? ` — ${p.overlay.note}` : ""}
                  </span>
                )}
                {p.binding && (
                  <span className="aug-fs-xs" style={{ ...MONO, display: "block", color: "var(--t4)" }}
                    title={`Read through the ${p.binding.kind} binding ${p.binding.name}, on the ${page.type_name} key`}>
                    {p.binding.source}.{p.binding.column}
                  </span>
                )}
              </dd>
            </React.Fragment>
          );
        })}
      </dl>
    </Section>
  );
}

function LinksCard({ page, scope }: { page: ObjectPage; scope: Scope }) {
  const [open, setOpen] = useState<string | null>(null);
  if (page.links.length === 0) {
    return (
      <Section title="Links">
        <EmptyState variant="inline" title={`No measured link reaches out from ${page.type_name}.`} />
      </Section>
    );
  }
  return (
    <Section title="Links"
      description="A to-one link opens the linked object; a to-many link lists its objects. A link the compiler refuses says why and is not followed.">
      {page.links.map((link, i) => (
        <div key={link.name} style={{ padding: "8px 0", borderTop: i ? ROW_RULE : undefined }}>
          <LinkRow link={link} scope={scope} open={open === link.name}
            onToggle={() => setOpen(open === link.name ? null : link.name)} />
          {open === link.name && <LinkedObjects page={page} link={link} scope={scope} />}
        </div>
      ))}
    </Section>
  );
}

function LinkRow({ link, scope, open, onToggle }: {
  link: ObjectLink;
  scope: Scope;
  open: boolean;
  onToggle: () => void;
}) {
  let value: React.ReactNode;
  if (!link.usable) {
    value = <span className="aug-fs-xs" style={{ color: "var(--t4)", textAlign: "right" }}>{link.why_not}</span>;
  } else if (link.kind === "to-one") {
    value = link.pk ? (
      <Link href={objectHref(link.to, link.pk, scope.connectionId, scope.schemaName)} className="aug-fs-sm"
        style={{ ...MONO, color: "var(--blue3)" }} title={`Open ${link.to_type} ${link.pk}`}>
        {link.pk}
      </Link>
    ) : <span className="aug-fs-sm" style={{ color: "var(--t4)" }}>none</span>;
  } else if ((link.count ?? 0) > 0) {
    const count = link.count ?? 0;
    value = (
      <Button variant="ghost" size="xs" onClick={onToggle} aria-expanded={open}>
        <Icon name={open ? "chevd" : "chevr"} size={14} />
        {formatCount(count)} {count === 1 ? "object" : "objects"}
      </Button>
    );
  } else {
    value = <span className="aug-fs-sm" style={{ color: "var(--t4)" }}>none</span>;
  }
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
      <span style={{ color: link.usable ? "var(--t3)" : "var(--t4)", display: "inline-flex" }}><Icon name="link" size={14} /></span>
      <span className="aug-fs-sm" style={{ color: link.usable ? "var(--t1)" : "var(--t3)", fontWeight: 500 }}>{link.to_type}</span>
      <span className="aug-fs-xs" style={{ ...MONO, color: "var(--t4)", whiteSpace: "nowrap" }} title={link.on}>
        {link.name} · {link.cardinality}
      </span>
      <div style={{ flex: 1 }} />
      {value}
    </div>
  );
}

function LinkedObjects({ page, link, scope }: { page: ObjectPage; link: ObjectLink; scope: Scope }) {
  const [head, setHead] = useState<LinkedObjectsPage | null>(null);
  const [rows, setRows] = useState<unknown[][]>([]);
  const [problem, setProblem] = useState("");
  const [loading, setLoading] = useState(false);
  // Every column that names an object opens it in place — a ticket's order_id opens its order.
  const columnLinks = useObjectColumnLinks(head?.columns ?? NO_COLUMNS, scope.connectionId,
                                           { schemaName: scope.schemaName, newTab: false });

  const load = useCallback((offset: number) => {
    setLoading(true);
    getLinkedObjects(page.object_type, page.pk, link.name, scope.connectionId, scope.schemaName,
                     { limit: LINKED_PAGE, offset })
      .then((res) => {
        if (res.path === "links") {
          setHead(res);
          setRows((prev) => (offset === 0 ? res.rows : [...prev, ...res.rows]));
        } else {
          setProblem(res.path === "refused" ? res.refused : res.detail);
        }
      })
      .catch((e: unknown) => setProblem(errorText(e)))
      .finally(() => setLoading(false));
  }, [page.object_type, page.pk, link.name, scope.connectionId, scope.schemaName]);

  useEffect(() => { load(0); }, [load]);

  if (problem) return <div className="aug-fs-xs" style={{ color: "var(--t3)", paddingTop: 8 }}>{problem}</div>;
  if (!head) return <div style={{ paddingTop: 8 }}><SkeletonRows rows={3} /></div>;
  const keyColumn = head.columns.find((c) => c.toLowerCase() === head.key.toLowerCase());
  // The list's own key links even before the catalog arrives, or without one.
  const overrides = keyColumn
    ? { ...columnLinks, [keyColumn]: { render: objectLinkRender(head.object_type, { ...scope, newTab: false }) } }
    : columnLinks;
  return (
    <div style={{ paddingTop: 8 }}>
      <SqlResultTable columns={head.columns} rows={rows} maxHeight={300} totals={false} columnOverrides={overrides} />
      {head.has_more && (
        <Button variant="ghost" size="xs" disabled={loading} onClick={() => load(rows.length)} style={{ marginTop: 6 }}>
          {loading ? "Loading…" : `Show the next ${LINKED_PAGE}`}
        </Button>
      )}
    </div>
  );
}

function CitationsCard({ page, citations }: { page: ObjectPage; citations: ObjectCitation[] }) {
  return (
    <Section title="Findings and answers that name it"
      description={<>Cited only where the SQL filters <span style={MONO}>{page.key}</span>, or a column joined to it, by this exact value.</>}>
      {citations.length === 0 ? (
        <EmptyState variant="inline" title={`No finding or answer names this ${page.type_name.toLowerCase()} yet.`} />
      ) : citations.map((c, i) => (
        <div key={`${c.kind}:${c.id}`} style={{ padding: "8px 0", borderTop: i ? ROW_RULE : undefined }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span className={`aug-tag ${c.kind === "answer" ? "aug-tag-blue" : "aug-tag-violet"}`}>{c.kind}</span>
            {typeof c.at === "string" && <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{relTime(c.at)}</span>}
            <div style={{ flex: 1 }} />
            <span className="aug-fs-xs"
              style={{ ...MONO, color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {c.matched}
            </span>
          </div>
          <div className="aug-fs-sm" style={{ color: "var(--t1)", marginTop: 4, lineHeight: 1.5 }}>{c.text || c.question}</div>
        </div>
      ))}
    </Section>
  );
}

function MetricsCard({ page, metrics }: { page: ObjectPage; metrics: ObjectMetric[] }) {
  return (
    <Section title="Metrics" description={`Verified metrics, compiled with this ${page.type_name.toLowerCase()} as the filter.`}>
      {metrics.length === 0 ? (
        <EmptyState variant="inline" title="No verified metric reaches this object." />
      ) : metrics.map((m, i) => (
        <div key={`${m.metric}:${m.via}`} title={m.sql}
          style={{ display: "flex", alignItems: "baseline", gap: 10, padding: "7px 0", borderTop: i ? ROW_RULE : undefined }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="aug-fs-sm" style={{ color: "var(--t1)" }}>{m.display_name}</div>
            <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>{m.via ? `across ${m.on} · ${m.via}` : `on this ${m.on}`}</div>
          </div>
          <MetricValue metric={m} />
        </div>
      ))}
    </Section>
  );
}

function MetricValue({ metric }: { metric: ObjectMetric }) {
  if (metric.refused || metric.error) {
    return (
      <span className="aug-fs-xs"
        style={{ color: metric.error ? "var(--red5)" : "var(--t4)", maxWidth: 200, textAlign: "right" }}>
        {metric.refused || metric.error}
      </span>
    );
  }
  const n = typeof metric.value === "number" ? metric.value : Number(metric.value);
  const text = metric.value == null || metric.value === "" ? "—" : Number.isFinite(n) ? formatMetricValue(n) : cellText(metric.value);
  return (
    <span className="aug-fs-ui" style={{ ...MONO, color: "var(--t1)", fontWeight: 600, whiteSpace: "nowrap" }}>
      {text}
      {metric.unit && <span className="aug-fs-xs" style={{ color: "var(--t4)", fontWeight: 400 }}> {metric.unit}</span>}
    </span>
  );
}

function ActionsCard({ page, actions, scope }: { page: ObjectPage; actions: ObjectAction[]; scope: Scope }) {
  const actionsTab = declaredActionsHref(scope.connectionId);
  const noun = page.type_name.toLowerCase();
  return (
    <Section title="Actions"
      description={`Declared actions that take this ${noun}, its key filled in. Offered here; proposing and approving happen in Actions.`}>
      {actions.length === 0 ? (
        <EmptyState variant="inline" title={`No declared action takes ${withArticle(noun)}.`}
          action={<Link href={actionsTab}><Button variant="outline" size="xs">Open Actions</Button></Link>} />
      ) : (
        <div className="flex flex-col gap-3">
          {actions.map((a) => <ActionOffer key={a.id} action={a} href={actionsTab} />)}
        </div>
      )}
    </Section>
  );
}

function ActionOffer({ action, href }: { action: ObjectAction; href: string }) {
  return (
    <div className="aug-panel" style={{ padding: "10px 12px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <span style={{ color: "var(--t3)", display: "inline-flex" }}><Icon name="bolt" size={14} /></span>
        <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600 }}>{action.display_name}</span>
        {action.risk && <span className={`aug-tag ${RISK_TAG[action.risk] ?? "aug-tag-gray"}`}>{action.risk}</span>}
        {action.kind && <span className="aug-tag aug-tag-gray">{action.kind}</span>}
        <div style={{ flex: 1 }} />
        <span className="aug-fs-xs" style={{ color: "var(--t4)", whiteSpace: "nowrap" }}>{action.why}</span>
      </div>
      {action.description && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4, lineHeight: 1.5 }}>{action.description}</div>
      )}
      {action.params.length > 0 && (
        <dl style={{ display: "grid", gridTemplateColumns: "max-content minmax(0, 1fr)", columnGap: 12, rowGap: 4, margin: "8px 0 0" }}>
          {action.params.map((p) => {
            const filled = action.prefilled.includes(p.name);
            return (
              <React.Fragment key={p.name}>
                <dt className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)" }} title={p.description || undefined}>
                  {p.name}{p.required ? " *" : ""}
                </dt>
                <dd className="aug-fs-xs"
                  style={{ ...MONO, margin: 0, display: "flex", alignItems: "center", gap: 4, overflowWrap: "anywhere",
                           color: filled ? "var(--blue5)" : p.value == null ? "var(--t4)" : "var(--t1)" }}>
                  {filled && <Icon name="check" size={12} label="Filled from this object" />}
                  {p.value == null ? "to be filled" : cellText(p.value)}
                </dd>
              </React.Fragment>
            );
          })}
        </dl>
      )}
      <div style={{ marginTop: 8 }}>
        <Link href={href}><Button variant="outline" size="xs">Open in Actions</Button></Link>
      </div>
    </div>
  );
}

function NotesCard({ notes }: { notes: ObjectNote[] }) {
  return (
    <Section title="Notes" description="Edits kept beside the data on this row; the source is never written.">
      {notes.length === 0 ? (
        <EmptyState variant="inline" title="No notes on this row." />
      ) : notes.map((n, i) => (
        <div key={`${n.column}:${n.at}:${i}`} style={{ padding: "7px 0", borderTop: i ? ROW_RULE : undefined }}>
          <div className="aug-fs-sm" style={{ color: "var(--t1)", lineHeight: 1.5 }}>{n.body}</div>
          <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 2 }}>
            {[n.column, n.kind, n.source, typeof n.at === "string" ? relTime(n.at) : ""].filter(Boolean).join(" · ")}
          </div>
        </div>
      ))}
    </Section>
  );
}
