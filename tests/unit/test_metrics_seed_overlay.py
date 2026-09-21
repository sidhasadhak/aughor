"""The metrics catalogue as a seed with an instance over it.

`data/metrics.json` was shipped content AND each install's catalogue, so every used install
carried a modified tracked file, and git refuses to fast-forward over one the moment upstream
edits it too (#514 did). The seed now ships at `data/shipped/metrics.json`, the app writes an
ignored instance file, and the pre-overlay file is frozen and read once, to convert.

Every test here builds its own four files in tmp and points the module at them, so none can
reach a developer's `data/`: `_LEGACY_PATH` and `_LEGACY_BASELINE` are repointed BEFORE any
env var is removed.
"""
from __future__ import annotations

import hashlib
import json
import threading

import pytest

from aughor.semantic import metrics as m
from aughor.semantic.metrics import MetricDefinition, MetricsStoreError


def row(name, conn="samples", sql="SUM(x)", **extra):
    """A sparse row, the shape the shipped file uses."""
    return {"name": name, "connection": conn, "label": name.title(), "sql": sql, **extra}


BASELINE = [row("revenue"), row("aov", sql="AVG(x)")]


@pytest.fixture
def layers(tmp_path, monkeypatch):
    """Seed, frozen baseline, legacy file and instance path, all in tmp. The instance is
    reached through AUGHOR_METRICS_PATH unless a test takes the env-unset route."""
    seed, base, legacy = tmp_path / "seed.json", tmp_path / "legacy.base.json", tmp_path / "metrics.json"
    inst = tmp_path / "metrics.instance.json"
    seed.write_text(json.dumps(BASELINE))
    base.write_text(json.dumps(BASELINE))
    legacy.write_text(json.dumps(BASELINE))
    monkeypatch.setattr(m, "_LEGACY_PATH", legacy)
    monkeypatch.setattr(m, "_LEGACY_BASELINE", base)
    monkeypatch.setattr(m, "_DEFAULT_PATH", inst)
    monkeypatch.setenv("AUGHOR_HOME", str(tmp_path / "home"))        # no marker: nothing rehomes
    monkeypatch.setenv("AUGHOR_METRICS_SEED_PATH", str(seed))
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(inst))

    class L:
        pass
    ns = L()
    ns.seed, ns.base, ns.legacy, ns.inst = seed, base, legacy, inst
    ns.unset = lambda: monkeypatch.delenv("AUGHOR_METRICS_PATH")   # the production route: derive from legacy
    return ns


def names(rows):
    return [(r["connection"] if isinstance(r, dict) else r.connection,
             r["name"] if isinstance(r, dict) else r.name) for r in rows]


def by_key(rows):
    out = {}
    for r in rows:
        d = r if isinstance(r, dict) else r.model_dump()
        out.setdefault((d.get("connection") or "*", d["name"]), []).append(
            {k: v for k, v in d.items() if v not in (None, [], "")})
    return out


# ── M1 · the differential: the overlay answers what the single file answered ─────────────────

OPS = [
    ("save", MetricDefinition(name="units", connection="c1", label="Units", sql="SUM(q)")),
    ("save", MetricDefinition(name="revenue", connection="c1", label="Rev c1", sql="SUM(y)")),
    ("save", MetricDefinition(name="revenue", connection="samples", label="Rev edited", sql="SUM(z)")),
    ("delete", dict(name="aov", connection_id="samples")),
    ("delete", dict(name="aov", connection_id="samples")),                  # nothing left: False both
    ("save", MetricDefinition(name="aov", connection="samples", label="AOV again", sql="AVG(z)")),
    ("delete", dict(name="revenue")),                                       # unscoped: every connection
    ("delete", dict(name="units", sql="SUM(nope)")),                        # wrong grain: False both
    ("delete", dict(name="units", sql="SUM(q)")),
]


def test_M1_every_write_leaves_the_same_catalogue_as_the_single_file_store(layers, tmp_path):
    """The oracle is today's store — one file, read and written whole — started from the same
    rows. After every operation both must hold the same rows per key, and report the same
    True/False. Kills: concatenating the layers, a delete that leaves no hidden key (the seed row
    comes back), a re-create that stays hidden, a writer that writes the seed."""
    oracle = tmp_path / "oracle.json"
    oracle.write_text(json.dumps(BASELINE))
    seed_before = layers.seed.read_bytes()
    for op, arg in OPS:
        if op == "save":
            m.save_metric(arg)
            m.save_metric(arg, path=oracle)
        else:
            got, want = m.delete_metric(**arg), m.delete_metric(**arg, path=oracle)
            assert got == want, (op, arg)
        assert by_key(m.list_metrics()) == by_key(m.list_metrics(path=oracle)), (op, arg)
    assert layers.seed.read_bytes() == seed_before, "a writer wrote the shipped seed"


# ── M2 / M4 · keys this install never touched follow the seed ────────────────────────────────

def test_M2_an_untouched_seed_key_follows_an_upstream_edit(layers):
    """Kills: a writer that loads the MERGED view and writes it to the instance — that would pin
    every seed row as this install's and no seed edit would ever arrive."""
    m.save_metric(MetricDefinition(name="units", connection="c1", label="Units", sql="SUM(q)"))
    layers.seed.write_text(json.dumps([row("revenue", sql="SUM(new)"), row("aov", sql="AVG(x)")]))
    got = {r.name: r.sql for r in m.list_metrics(connection_id="samples")}
    assert got["revenue"] == "SUM(new)"
    assert not m.get_metric("units", connection_id="samples")


def test_M4_a_fresh_install_reads_the_seed_exactly(layers):
    """Legacy file == what it shipped as: every row is an echo, so the view is the CURRENT seed —
    an edited key, an added key and a removed key all arrive. Kills: treating the legacy file as
    instance data, and judging echoes against the current seed instead of the frozen baseline."""
    layers.unset()
    new_seed = [row("revenue", sql="SUM(new)"), row("margin", sql="SUM(m)")]
    layers.seed.write_text(json.dumps(new_seed))
    assert m._load_raw() == new_seed
    assert not layers.inst.exists(), "a read wrote the instance file"


# ── M3 · a used install reads exactly what it read before ─────────────────────────────────────

def test_M3_the_builders_install_reads_the_same_catalogue_after_the_update(layers):
    """The shape measured on the builder's install: four connection-scoped rows, and BOTH shipped
    `samples` rows deleted at the operator's request. Kills: a derive that hides nothing (the two
    deleted rows come back), and a conversion that runs on READ."""
    live = [row("revenue", "8233e4fd"), row("units_sold", "8233e4fd"),
            row("return_rate", "8233e4fd"), row("average_csat_score", "914df862")]
    layers.legacy.write_text(json.dumps(live))
    layers.unset()
    assert m._load_raw() == live
    assert m.get_metric("revenue", connection_id="samples") is None
    assert not layers.inst.exists(), "a read wrote the instance file"


def test_M3_an_edited_shipped_row_stays_edited_and_in_place(layers):
    edited = [row("revenue", sql="SUM(mine)"), row("aov", sql="AVG(x)"), row("units", "c1")]
    layers.legacy.write_text(json.dumps(edited))
    layers.seed.write_text(json.dumps([row("revenue", sql="SUM(upstream)"), row("aov", sql="AVG(x)")]))
    layers.unset()
    assert m._load_raw() == edited                       # the install's edit beats the seed's


# ── M5 / M6 · the one-time conversion ─────────────────────────────────────────────────────────

def test_M5_the_first_write_converts_verifies_and_never_touches_the_legacy_file(layers):
    """Kills: materializing from the seed (the install's rows vanish), writing the legacy file."""
    live = [row("revenue", "8233e4fd"), row("aov", sql="AVG(x)")]         # revenue/samples deleted here
    layers.legacy.write_text(json.dumps(live))
    before = layers.legacy.read_bytes()
    layers.unset()
    m.save_metric(MetricDefinition(name="units", connection="c1", label="Units", sql="SUM(q)"))
    assert layers.legacy.read_bytes() == before
    doc = json.loads(layers.inst.read_text())
    assert doc["format"] == m.INSTANCE_FORMAT
    assert doc["converted_from"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert {"connection": "samples", "name": "revenue"} in doc["hidden"]
    assert names(m.list_metrics()) == [("samples", "aov"), ("8233e4fd", "revenue"), ("c1", "units")]


def test_M5_a_conversion_that_would_change_the_catalogue_writes_nothing(layers, monkeypatch):
    """The verifier is independent of `derive`: break derive, and the conversion must refuse.
    Kills: a verifier that reuses derive (it would approve its own defect)."""
    layers.legacy.write_text(json.dumps([row("units", "c1")]))
    layers.unset()
    monkeypatch.setattr(m, "derive", lambda legacy, baseline: m._Instance())   # loses the install's row
    with pytest.raises(MetricsStoreError, match="units"):
        m.save_metric(MetricDefinition(name="x", connection="c1", label="X", sql="SUM(x)"))
    assert not layers.inst.exists()


def test_M6_an_instance_file_that_appears_mid_conversion_is_kept_not_replaced(layers, monkeypatch):
    """Another process converts between our existence check and our write. Kills: creating the
    file with os.replace, which would silently overwrite the other process's conversion."""
    layers.legacy.write_text(json.dumps([row("units", "c1")]))
    layers.unset()
    theirs = {"format": m.INSTANCE_FORMAT, "rows": [row("theirs", "c9")], "hidden": []}
    real = m._unconverted

    def racing(*a, **k):
        if not layers.inst.exists():
            layers.inst.write_text(json.dumps(theirs))
        return real(*a, **k)

    monkeypatch.setattr(m, "_unconverted", racing)
    got = m.materialize()
    assert json.loads(layers.inst.read_text()) == theirs
    assert names(got.rows) == [("c9", "theirs")]


def test_M6_a_writer_that_replaces_our_file_mid_check_is_never_deleted(layers, monkeypatch):
    """A second process's first write lands between our create and our read-back: its file carries
    a row our conversion never saw, so the read-back disagrees — and the file is THEIRS now.
    Kills: unlinking the instance on any read-back mismatch, which deleted a saved metric."""
    layers.legacy.write_text(json.dumps([row("units", "c1")]))
    layers.unset()
    real = m._create_if_absent

    def then_theirs(p, text):
        ino = real(p, text)
        doc = json.loads(p.read_text())
        doc["rows"].append(row("ltv", "c2"))
        other = p.with_name("other.tmp")
        other.write_text(json.dumps(doc))
        other.replace(p)                                   # a new inode, as os.replace gives
        return ino

    monkeypatch.setattr(m, "_create_if_absent", then_theirs)
    got = m.materialize()
    assert layers.inst.exists(), "another process's saved metric was deleted"
    assert ("c2", "ltv") in names(got.rows)


def test_M6_a_filesystem_without_hard_links_still_converts(layers, monkeypatch):
    """exFAT, FAT, some network and FUSE mounts refuse link(2). Kills: letting that OSError reach
    the route — every metric write on such an install would fail, forever."""
    import errno

    def no_links(*a, **k):
        raise OSError(errno.ENOTSUP, "Operation not supported")

    layers.legacy.write_text(json.dumps([row("units", "c1")]))
    layers.unset()
    monkeypatch.setattr(m.os, "link", no_links)
    m.save_metric(MetricDefinition(name="x", connection="c1", label="X", sql="SUM(x)"))
    assert {("c1", "units"), ("c1", "x")} <= set(names(m.list_metrics()))
    assert json.loads(layers.inst.read_text())["converted_from"]


def test_a_missing_instance_after_conversion_is_an_error_not_a_quiet_reread(layers):
    """After the first write the frozen file is stale. If the instance then goes missing (moved
    aside, a bad restore), re-deriving from it would drop every metric saved since and bring
    deleted ones back — silently, and the next write would make that permanent.
    Kills: deriving whenever the instance is absent."""
    layers.legacy.write_text(json.dumps(BASELINE))
    layers.unset()
    m.save_metric(MetricDefinition(name="nps", connection="c1", label="NPS", sql="AVG(n)"))
    assert m.delete_metric("aov", connection_id="samples")
    layers.inst.rename(layers.inst.with_name("aside.json"))
    with pytest.raises(MetricsStoreError, match="Restore it from a backup"):
        m.list_metrics()
    with pytest.raises(MetricsStoreError):
        m.save_metric(MetricDefinition(name="y", connection="c1", label="Y", sql="SUM(y)"))
    assert not layers.inst.exists(), "a write re-converted from the stale frozen file"


# ── M7 · grains ───────────────────────────────────────────────────────────────────────────────

TWO_GRAINS = [row("revenue", sql="SUM(orders.t)"), row("revenue", sql="SUM(items.p)")]


def test_M7_saving_one_grain_of_a_shipped_key_keeps_the_other(layers):
    """The instance shadows a key WHOLE, so a save must copy the seed's rows for it up first.
    Kills: a save without the copy-up — the untouched grain vanishes on the first edit."""
    layers.seed.write_text(json.dumps(TWO_GRAINS))
    m.save_metric(MetricDefinition(name="revenue", connection="samples", label="R", sql="SUM(orders.t2)"))
    assert [r.sql for r in m.list_metrics()] == ["SUM(orders.t2)", "SUM(items.p)"]


def test_M7_deleting_one_grain_of_a_shipped_key_keeps_the_other(layers):
    """Kills: a delete without the copy-up, or one that hides the whole key."""
    layers.seed.write_text(json.dumps(TWO_GRAINS))
    assert m.delete_metric("revenue", sql="SUM(items.p)", connection_id="samples")
    assert [r.sql for r in m.list_metrics()] == ["SUM(orders.t)"]


# ── M8 · delete, then re-create ───────────────────────────────────────────────────────────────

def test_M8_a_deleted_shipped_row_stays_gone_and_can_be_made_again(layers):
    assert m.delete_metric("aov", connection_id="samples")
    assert m.get_metric("aov", connection_id="samples") is None
    layers.seed.write_text(json.dumps(BASELINE + [row("margin")]))       # upstream moves on
    assert m.get_metric("aov", connection_id="samples") is None           # still hidden
    m.save_metric(MetricDefinition(name="aov", connection="samples", label="AOV", sql="AVG(y)"))
    assert m.get_metric("aov", connection_id="samples").sql == "AVG(y)"
    assert json.loads(layers.inst.read_text())["hidden"] == []


# ── M9 / M11 · reads that must not quietly answer less ────────────────────────────────────────

@pytest.mark.parametrize("body", ["{not json", json.dumps({"format": "something/else", "rows": []}),
                                  json.dumps("a string")])
def test_M9_an_unreadable_instance_is_an_error_never_an_emptier_catalogue(layers, body):
    """Kills: falling back to [] or to the seed alone — several readers swallow exceptions, and a
    catalogue with this install's rows missing reads as a healthy one."""
    layers.inst.write_text(body)
    with pytest.raises(MetricsStoreError):
        m.list_metrics()
    with pytest.raises(MetricsStoreError):
        m.save_metric(MetricDefinition(name="x", connection="c1", label="X", sql="SUM(x)"))
    assert layers.inst.read_text() == body, "an unreadable instance file was overwritten"


def test_M11_a_named_instance_path_never_reads_the_checkouts_file(layers):
    """The hermeticity hole the design review found: a test that names an absent instance file
    must not fall through to the checkout's `data/metrics.json` — on a developer's machine that is
    their live catalogue. Kills: deriving from the legacy file while AUGHOR_METRICS_PATH is set."""
    layers.legacy.write_text(json.dumps([row("live_only", "8233e4fd")]))
    assert ("8233e4fd", "live_only") not in names(m.list_metrics())
    m.save_metric(MetricDefinition(name="x", connection="c1", label="X", sql="SUM(x)"))
    assert "converted_from" not in json.loads(layers.inst.read_text())


def test_a_bare_list_is_a_whole_catalogue_and_reads_as_it_did_alone(layers):
    """What a pre-overlay AUGHOR_METRICS_PATH file (an operator's per-store path) and every test's
    own registry hold. A shipped key it lacks was deleted there and stays gone; only a key shipped
    SINCE arrives. Kills: reading a bare list with no hidden keys — the review found the operator's
    deleted `samples` rows coming back."""
    layers.inst.write_text(json.dumps([row("revenue", sql="SUM(mine)")]))
    layers.seed.write_text(json.dumps(BASELINE + [row("margin", sql="SUM(m)")]))
    assert [(r.name, r.sql) for r in m.list_metrics(connection_id="samples")] == [
        ("revenue", "SUM(mine)"), ("margin", "SUM(m)")]


def test_the_shipped_files_are_never_a_write_target(layers, monkeypatch):
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(layers.seed))
    with pytest.raises(MetricsStoreError, match="shipped"):
        m.save_metric(MetricDefinition(name="x", connection="c1", label="X", sql="SUM(x)"))
    with pytest.raises(MetricsStoreError, match="shipped"):
        m._save_raw([], layers.legacy)


# ── M10 · concurrent writers in one process ──────────────────────────────────────────────────

def test_M10_concurrent_saves_lose_nothing(layers):
    def save(i):
        m.save_metric(MetricDefinition(name=f"m{i}", connection="c1", label=f"M{i}", sql="SUM(x)"))
    threads = [threading.Thread(target=save, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {f"m{i}" for i in range(24)} <= {r.name for r in m.list_metrics(connection_id="c1")}


# ── M12 · the schema linker reads the layered catalogue ──────────────────────────────────────

def test_M12_the_schema_linker_sees_what_this_install_wrote(layers):
    """It read `data/metrics.json` directly — past the test isolation and, after the overlay,
    past everything an install writes. Kills: restoring the direct file read."""
    from aughor.tools import schema_linker as sl
    m.save_metric(MetricDefinition(name="zorblax", connection="c1", label="Zorblax",
                                   sql="SUM(quuxcol)", tables=["frobtable"]))
    sl.invalidate_hints()
    table_hints, col_hints, _ = sl.build_connection_hints("c1")
    assert "frobtable" in table_hints.get("zorblax", [])
    assert "quuxcol" in col_hints.get("zorblax", [])
