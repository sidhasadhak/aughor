# Report-style study — adopt the Genie presentation (R16)

Side-by-side of the SAME question ("Where are we losing money?") on the SAME airline
dataset: Databricks' 3-page report vs Aughor's 7-page report (2026-07-16, both PDFs +
trace screenshots). Aughor's *content* honesty wins (data-gaps, confidence, feasibility
verdicts — keep all of it); Databricks' *presentation* wins. This doc is the adoption
spec.

## What Databricks does that we should adopt

| # | Property | Databricks | Aughor today |
|---|---|---|---|
| 1 | **Title is the verdict** | "Where You're Losing Money: Long-Haul Capacity Underutilization" | ✅ already have ("No segment is underperforming — …") — keep |
| 2 | **Numbers live in prose** | Every figure is bold inline in a claim sentence ("74.5% capacity vs 77.2%") | Rows of BIG stat tiles under every section (3 per dimension × 6 sections) |
| 3 | **One exhibit per claim** | Exactly one chart OR one table per numbered section | chart + full data table + stat tiles for EVERY finding |
| 4 | **No degenerate exhibits** | — | We shipped a 1-bar chart (Europe = 100%) and a single-point scatter (one period) |
| 5 | **Claim-led section titles** | "1. Underperforming Long-Haul Routes" | Machinery names: "Question Intake", "Cross-Sectional Scan", "Temporal Trend — When" |
| 6 | **Named entities with IDs** | "GVA-DEL: 65.2% load factor (168K CHF per flight)" as compact bullets | Prose names segments but rarely bullet-lists ranked entities |
| 7 | **Machinery stays out of the body** | No spec dump | "Investigation Specification" paragraph + field/value table printed in full |
| 8 | **Financial Impact section** | gap × volume opportunity math in prose | R15 computes exactly this — surface it as its own section |
| 9 | **Trace: plain structured tree** | Monochrome, tree-lines, narrative beats interleaved with query titles, collapsible "Thinking complete" | Purple AGENT TRACE, progress bar, phase checkmarks — color-fancy |
| 10 | **Length discipline** | ~700 words, 3 charts, 1 table, 3 pages | ~7 pages, 7 charts, 7 tables, 12 stat tiles |

**Keep (ours, better than theirs):** the verdict title, Data gaps, Confidence with reasoning,
Recommendations with impact/owner/timeline, the honesty guards. The fix is FORM, not content.

## The R16 plan

### P1 — deterministic composition rules (no LLM; the big visual win)
1. **Exhibit selection:** per finding render chart XOR table — table only when the table IS
   the point (≤6 rows × ≥3 informative cols, or the model asked for one); NEVER both. The
   full data grid moves behind the existing drill/receipt surface.
2. **Degenerate-exhibit suppression:** <2 informative rows (or 1 group / 1 period) → no
   chart; the sentence carries it. Deterministic rule at render + PDF export.
3. **Stat-tile demotion:** kill the per-section key-number tile rows; at most ONE headline
   stat tile for the whole report. Key numbers render bold inline in the section prose
   (they're already in `key_numbers` — the renderer inlines instead of tiling).
4. **Machinery out of the body:** Question Intake / Investigation Specification move to the
   collapsed "Methodology & details" (web) and OUT of the PDF body (a one-line "How this
   was measured" stays). Trust Receipt remains the full-detail home.
5. **Financial Impact:** when the R15 opportunity key-number exists, render it as its own
   short section before Recommendations.

### P2 — argument-style prose (synthesis prompt)
Section titles must BE findings ("1. <what's wrong where>"), numbers bold inline, ranked
entities as compact `**ID**: value (context)` bullets (R15's named-outlier shape), 2-4
sentences per section. Recommendations: numbered, bold-led, one line + the impact/owner/
timeline sub-line we already have.

### P3 — trace restyle (web)
The AGENT TRACE panel → Databricks' shape: monochrome text tree (tree-line connectors),
narrative beats as top-level bullets with their queries indented beneath, collapsed by
default behind "Thinking complete", no progress bar/phase chrome/purple. Traces are already
SAVED structurally (progress events + task_history); this is presentation only.

Flag: `report.argument_style` gates P1+P2 (default-off, byte-identical); P3 is a pure
restyle (design-review, no flag).

Sequencing: P1 → P3 → P2 (P1 is deterministic and the biggest visual delta; P2 changes LLM
prose and needs a live eval pass).
