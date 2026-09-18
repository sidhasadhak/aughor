"""Anything a report CARRIES must reach a surface, or say in place why it does not.

The generalisation of 2026-09-18. Four separate defects that day shared one shape — a
correct producer, and a consumer that did not read it:

  * `export/document.py` set `tag=<stat_note>` on every FINDING block, and both exporters
    rendered `block.tag` only in their PROSE branch. 630 stored findings carried a
    statistical verdict; not one could reach a PDF or a deck. The user's own report lost
    "September 2026 holds 21 of 30 days (70%) — its total is not comparable to a full
    month" and then quoted that partial month as a trend point;
  * the intake window guards sat inside `if intake is not None:`, skipped in the one case
    they were written for;
  * the chart vocabulary was spliced into the quick path's prompt only;
  * a trust check fired and only decorated the report it should have stopped.

Each got its own test. None of those tests could have caught any of the others, because
each guards one leg. This one guards the JOIN: for every (block kind, field) the document
builder populates, every exporter's branch for that kind must READ it — or a comment must
name what it drops and why.

## Why this can fail

A guard whose population is hand-listed beside its expectation cannot fail: whatever you
forget to list is exactly what it will not catch. So nothing here is listed. The population
is discovered by walking `document.py`'s own `Block(...)` constructions, and the
expectation by walking each renderer's `kind ==` branches. Add `Block("finding",
footnote=…)` tomorrow and this goes red until a renderer reads it or a comment says why not.

The escape hatch is deliberately cheap and deliberately visible: name the field (or the
kind) in a comment in the renderer. Three real omissions are documented that way today —
the PDF draws no caption under a chart because the figure titles itself, PPTX has no vector
surface so it rasterizes rather than reading `svg`, and code blocks live in the PDF
appendix rather than a slide. An omission anyone can justify in one line is fine; an
omission nobody noticed is what shipped the dropped verdict.
"""
import ast
import collections
import io
import pathlib
import tokenize

import pytest

DOC = "aughor/export/document.py"
RENDERERS = ("aughor/export/pdf.py", "aughor/export/slides.py")
REPO = pathlib.Path(__file__).resolve().parents[2]


def _src(rel: str) -> str:
    return (REPO / rel).read_text()


def blocks_written(rel: str) -> dict[str, set[str]]:
    """kind -> the fields the builder populates on it. Discovered, never listed."""
    out: dict[str, set[str]] = collections.defaultdict(set)
    for n in ast.walk(ast.parse(_src(rel))):
        if not (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Block"):
            continue
        kind = n.args[0].value if (n.args and isinstance(n.args[0], ast.Constant)) else None
        for kw in n.keywords:
            if kw.arg == "kind" and isinstance(kw.value, ast.Constant):
                kind = kw.value.value
        if kind is None:
            continue                      # a computed kind cannot be attributed statically
        for kw in n.keywords:
            if kw.arg and kw.arg != "kind":
                out[kind].add(kw.arg)
    return dict(out)


def _kind_of(test) -> str | None:
    """The literal in `<x>.kind == "literal"`, including inside an `and` chain."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
        left, right = test.left, test.comparators[0]
        if isinstance(left, ast.Attribute) and left.attr == "kind" and isinstance(right, ast.Constant):
            return right.value
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        for v in test.values:
            if (k := _kind_of(v)):
                return k
    return None


def _comments(src: str, lo: int, hi: int) -> str:
    try:
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        return " ".join(t.string for t in toks
                        if t.type == tokenize.COMMENT and lo <= t.start[0] <= hi)
    except tokenize.TokenError:
        return ""


def branches_read(rel: str) -> tuple[dict[str, set[str]], dict[str, str], str]:
    """(kind -> fields READ, kind -> that branch's own comments, the module's comments).

    Comments are kept SEPARATE from reads on purpose. Folding them together let an
    unrelated comment anywhere in the module excuse a real drop: `slides.code.text` passed
    because some comment about a text frame contained the word "text". Right answer, wrong
    reason — which is the failure mode a ratchet exists to not have."""
    src = _src(rel)
    reads: dict[str, set[str]] = collections.defaultdict(set)
    notes: dict[str, str] = collections.defaultdict(str)
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.If) or not (kind := _kind_of(n.test)):
            continue
        # From the `if`/`elif` line, so a comment leading the body is inside the range.
        lo = n.lineno
        hi = max((getattr(x, "end_lineno", None) or getattr(x, "lineno", lo))
                 for x in ast.walk(n.body[-1]))
        reads[kind] |= {a.attr for stmt in n.body for a in ast.walk(stmt)
                        if isinstance(a, ast.Attribute)}
        notes[kind] += " " + _comments(src, lo, hi)
    return dict(reads), dict(notes), _comments(src, 1, len(src.splitlines()))


WRITTEN = blocks_written(DOC)
CASES = sorted((r, k, f) for r in RENDERERS for k, fs in WRITTEN.items() for f in fs)


def test_the_population_is_real():
    """Vacuous-pass guard. If the walk breaks, every assertion below passes on an empty
    set — the failure mode this whole file exists to prevent, one level up."""
    assert len(WRITTEN) >= 6, f"only {len(WRITTEN)} block kinds discovered — the walk broke"
    assert "finding" in WRITTEN and "tag" in WRITTEN["finding"], (
        "the finding/tag pair that started this is no longer discovered")
    assert len(CASES) >= 20, f"only {len(CASES)} producer/renderer pairs — too few to be real"


@pytest.mark.parametrize("renderer,kind,field", CASES,
                         ids=[f"{r.split('/')[-1][:-3]}:{k}.{f}" for r, k, f in CASES])
def test_every_populated_field_reaches_the_surface(renderer, kind, field):
    reads, notes, module_comments = branches_read(renderer)

    # No branch at all — the whole kind is dropped. Documented BESIDE the chain, since
    # there is no body to put a comment in ("code blocks are omitted from slides").
    if kind not in reads:
        assert kind in module_comments, (
            f"{renderer} has NO branch for {kind!r}: every {kind} block the builder "
            f"produces vanishes from this surface, and nothing says so")
        return

    if field in reads[kind]:
        return

    # The branch exists but skips this field. The excuse must live in THAT branch and name
    # THIS field — a module-wide search would let any passing mention of a common word
    # ("text", "rows") wave a real drop through.
    assert field in notes.get(kind, ""), (
        f"{renderer} never reads {kind}.{field} — the builder sets it and this renderer "
        f"drops it silently. Read it, or name {field!r} in a comment INSIDE the {kind!r} "
        f"branch saying why not. This is exactly how every finding's stat_note was lost: "
        f"document.py set it, no renderer read it, and no test looked at the join.")


# ── The web is the third surface ──────────────────────────────────────────────
# The PDF and the deck are not the only place a finding is read. `InvestigationReport.tsx`
# declares its OWN interface for a finding, and the same defect lives there in the same
# shape: a field declared and read by nobody.
#
# It is not hypothetical. `stat_note` is declared on that interface and never read anywhere
# under `web/` — and `SignificanceBadge`, the component written to show it, is imported by
# nothing. The web has a deliberate policy for that one ("the significance verdict + stat
# note are VERIFICATION machinery — they live in the Trust Receipt / Details, never in the
# body"), which this accepts as the same kind of in-place excuse the renderers use. What it
# will not accept is a field with neither a reader nor a word about it.
#
# The precedent is in that file already: "The trust advisory was declared in this interface
# since the trust battery shipped but rendered NOWHERE in web — only the CLI showed it.
# Both ends of a feature existed while the feature did not."

WEB = REPO / "web"
REPORT_TSX = WEB / "components" / "InvestigationReport.tsx"

#: Structural fields — plumbing every renderer threads through rather than shows. A reader
#: never "sees" `finding_id`; excluding them keeps the signal about CONTENT.
_STRUCTURAL = {"finding_id", "sql", "columns", "rows", "row_count", "error", "chart_type",
               "exhibit", "column_units"}


def _web_finding_fields() -> list[str]:
    src = REPORT_TSX.read_text()
    body = src.split("interface InvestigationFinding {", 1)[1].split("\n}", 1)[0]
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        name = line.split(":", 1)[0].rstrip("?").strip()
        if name.isidentifier() and name not in _STRUCTURAL:
            out.append(name)
    return out


WEB_FIELDS = _web_finding_fields()


def test_the_web_population_is_real():
    assert len(WEB_FIELDS) >= 5, f"only {WEB_FIELDS} parsed — the interface walk broke"
    assert "stat_note" in WEB_FIELDS, "the field that started this is no longer discovered"


@pytest.mark.parametrize("field", WEB_FIELDS)
def test_every_declared_finding_field_is_read_or_explained(field):
    """Declared on the finding and read by no component = the CLI-only trust advisory,
    again. Either something reads it, or a comment in the report says why not."""
    sources = [p for p in (WEB / "components").rglob("*.tsx")
               if ".test." not in p.name] + \
              [p for p in (WEB / "components").rglob("*.ts") if ".test." not in p.name]
    read = any(f".{field}" in p.read_text() and f"{field}?:" not in p.read_text().split(f".{field}")[0][-40:]
               for p in sources)
    if read:
        return
    # Prose names a field the way a person writes it ("stat note", not "stat_note"), so
    # underscores and spaces are the same character here.
    tsx = REPORT_TSX.read_text()
    wanted = field.replace("_", " ")
    commented = any(wanted in ln.replace("_", " ")
                    for ln in tsx.splitlines()
                    if ln.strip().startswith(("//", "*", "/*", "{/*")))
    #
    # LIMIT OF THIS CHECK, stated so nobody reads more into a green run than is there: it
    # verifies a reason was WRITTEN, not that the reason is TRUE. `stat_note` passes today
    # on the policy "they live in the Trust Receipt / Details" — and measured 2026-09-18,
    # nothing under web/ reads `stat_note` at all, so that destination is empty. A written
    # excuse is checkable by a machine; a truthful one is not.
    assert commented, (
        f"InvestigationReport declares `{field}` on a finding and nothing under web/ reads "
        f"it. Render it, or say in a comment where it goes instead — this is how "
        f"`stat_note` and, before it, `trust_caveat` were declared for months while no "
        f"reader ever saw them.")
