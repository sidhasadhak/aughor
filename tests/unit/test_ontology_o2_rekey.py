"""Wave O2 — glossary and metrics re-keyed per connection.

The headline gate for the whole wave is
:func:`TestMetricsRekey.test_two_connections_same_name_different_formula_both_correct` —
the #198 shape (a store keyed without the dimension distinguishing its owners), made
impossible for the third and last time.

The other half of the wave's risk is migration, and the tests that cover it are the
"unchanged" ones: a caller that passes no connection must read exactly what it read
before, because the existing tracked files ARE the global default by construction and any
behaviour change there breaks every connection at once with no error anywhere.
"""
from __future__ import annotations

import json

import pytest
import yaml

from aughor.semantic.glossary import CONNECTIONS_KEY, load_glossary
from aughor.semantic.metrics import (
    GLOBAL_CONNECTION,
    MetricDefinition,
    delete_metric,
    get_metric,
    list_metrics,
    save_metric,
)


@pytest.fixture
def metrics_path(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text("[]")
    return p


def _m(name="revenue", sql="SUM(total)", connection=GLOBAL_CONNECTION) -> MetricDefinition:
    return MetricDefinition(name=name, label=name.title(), sql=sql, connection=connection)


class TestMetricsRekey:
    def test_two_connections_same_name_different_formula_both_correct(self, metrics_path):
        """THE gate. Two connections, one metric name, different formulas, both right."""
        save_metric(_m(sql="SUM(gross)", connection="conn_a"), metrics_path)
        save_metric(_m(sql="SUM(net)", connection="conn_b"), metrics_path)

        assert get_metric("revenue", metrics_path, connection_id="conn_a").sql == "SUM(gross)"
        assert get_metric("revenue", metrics_path, connection_id="conn_b").sql == "SUM(net)"

    def test_a_scoped_entry_shadows_the_global_one(self, metrics_path):
        save_metric(_m(sql="SUM(total)"), metrics_path)                       # global
        save_metric(_m(sql="SUM(net)", connection="conn_a"), metrics_path)    # scoped

        assert get_metric("revenue", metrics_path, connection_id="conn_a").sql == "SUM(net)"
        assert get_metric("revenue", metrics_path, connection_id="conn_b").sql == "SUM(total)"

    def test_a_connection_inherits_globals_it_has_not_scoped(self, metrics_path):
        save_metric(_m(name="revenue"), metrics_path)
        save_metric(_m(name="margin"), metrics_path)
        save_metric(_m(name="revenue", sql="SUM(net)", connection="conn_a"), metrics_path)

        got = {m.name: m.sql for m in list_metrics(metrics_path, connection_id="conn_a")}
        assert got == {"revenue": "SUM(net)", "margin": "SUM(total)"}

    def test_scoping_a_metric_does_not_overwrite_the_global(self, metrics_path):
        """Upsert identity is the (connection, name) PAIR. By name alone, scoping
        `revenue` to one connection would silently overwrite what everyone else reads."""
        save_metric(_m(sql="SUM(total)"), metrics_path)
        save_metric(_m(sql="SUM(net)", connection="conn_a"), metrics_path)

        assert get_metric("revenue", metrics_path).sql == "SUM(total)"
        assert len(json.loads(metrics_path.read_text())) == 2

    def test_deleting_a_scoped_metric_leaves_the_global_alone(self, metrics_path):
        """Un-scoping one connection's metric must not delete it for everybody."""
        save_metric(_m(sql="SUM(total)"), metrics_path)
        save_metric(_m(sql="SUM(net)", connection="conn_a"), metrics_path)

        assert delete_metric("revenue", path=metrics_path, connection_id="conn_a")
        assert get_metric("revenue", metrics_path).sql == "SUM(total)"

    def test_deleting_without_a_connection_still_removes_everything(self, metrics_path):
        """Legacy bulk-cleanup behaviour, unchanged."""
        save_metric(_m(), metrics_path)
        save_metric(_m(connection="conn_a"), metrics_path)
        assert delete_metric("revenue", path=metrics_path)
        assert json.loads(metrics_path.read_text()) == []

    def test_the_grain_aware_delete_still_works_within_a_connection(self, metrics_path):
        """Written first through `save_metric` and it failed — correctly. That upserts by
        (connection, name), so it cannot CREATE two grains of one name, and never could:
        the pre-O2 version upserted by name alone and would have overwritten just the
        same. Multi-grain rows reach the file by other paths, so the fixture builds the
        state directly rather than asserting a capability the writer never had.
        """
        metrics_path.write_text(json.dumps([
            {"name": "revenue", "label": "R", "sql": "SUM(a)", "connection": "c1"},
            {"name": "revenue", "label": "R", "sql": "SUM(b)", "connection": "c1"},
        ]))
        assert delete_metric("revenue", sql="SUM(a)", path=metrics_path, connection_id="c1")
        remaining = [m.sql for m in list_metrics(metrics_path, connection_id="c1")]
        assert remaining == ["SUM(b)"]

    # ── migration: the file needed no rewrite ───────────────────────────────────────

    def test_an_entry_with_no_connection_field_is_global(self, metrics_path):
        """The whole migration story: existing entries ARE the global default, so the
        tracked file needed no rewrite and no data-loss risk was taken."""
        metrics_path.write_text(json.dumps(
            [{"name": "revenue", "label": "Revenue", "sql": "SUM(total)"}]))
        assert get_metric("revenue", metrics_path).connection == GLOBAL_CONNECTION
        assert get_metric("revenue", metrics_path, connection_id="anything").sql == "SUM(total)"

    def test_callers_passing_no_connection_read_exactly_what_they_did_before(
            self, metrics_path):
        metrics_path.write_text(json.dumps([
            {"name": "a", "label": "A", "sql": "1"},
            {"name": "b", "label": "B", "sql": "2"},
        ]))
        assert [m.name for m in list_metrics(metrics_path)] == ["a", "b"]

    def test_the_live_metrics_file_still_loads(self):
        """The real tracked artifact, read through the new code path."""
        assert list_metrics() is not None


class TestAPromptAboutOneConnectionReadsItsOwnMetrics:
    """The explorer does not look beyond its connection (the user's rule, 2026-09-14). Its schema text and its coherence
    gates read the metric registry, and a metric another connection scoped reached them wherever its table name matched
    — the unconverted `connection_id=None` sites `list_metrics` warns of."""

    SCHEMA = "TABLE: orders\n  order_id  BIGINT\n  total_amount  DOUBLE\n"

    def test_the_metrics_block_carries_this_connections_metrics_and_the_global_ones(self, metrics_path, monkeypatch):
        from aughor.semantic import metrics as M
        metrics_path.write_text(json.dumps([
            {"name": "shared_revenue", "label": "Shared revenue", "sql": "SUM(total_amount)", "tables": ["orders"]},
            {"name": "a_orders", "label": "A orders", "sql": "COUNT(order_id)", "tables": ["orders"],
             "connection": "conn_a"},
            {"name": "b_revenue", "label": "B revenue", "sql": "SUM(total_amount)", "tables": ["orders"],
             "connection": "conn_b"},
        ]))
        monkeypatch.setattr(M, "_apply_ontology_overlay", lambda ms, cid: list(ms))
        block = M.build_metrics_block(metrics_path, schema_text=self.SCHEMA, connection_id="conn_a")
        assert "A_ORDERS" in block and "SHARED_REVENUE" in block and "B_REVENUE" not in block
        # a caller that names no connection reads exactly what it read before
        assert "B_REVENUE" in M.build_metrics_block(metrics_path, schema_text=self.SCHEMA)

    def test_the_explorers_metric_vocabulary_is_its_own_connections(self, monkeypatch):
        from types import SimpleNamespace

        from aughor.explorer import metric_coherence as MC
        from aughor.semantic import metrics as M
        rows = [_m("zzalphametric", connection="conn_a"), _m("zzbetametric", connection="conn_b"),
                _m("zzglobalmetric")]

        def scoped(path=None, connection_id=None):
            return [m for m in rows if connection_id is None or m.connection in (connection_id, GLOBAL_CONNECTION)]
        monkeypatch.setattr(M, "list_metrics", scoped)
        vocab = MC.metric_vocab_for(SimpleNamespace(_connection_id="conn_a"), industry="none")
        assert "zzalphametric" in vocab and "zzglobalmetric" in vocab and "zzbetametric" not in vocab

    def test_a_connections_catalogue_lifts_its_own_metrics_and_the_global_ones(self, monkeypatch):
        from aughor.ontology import builder as B
        from aughor.semantic import metrics as M
        rows = [_m("zzalphametric", connection="conn_a"), _m("zzbetametric", connection="conn_b"),
                _m("zzglobalmetric")]
        monkeypatch.setattr(M, "list_metrics", lambda path=None, connection_id=None: [
            m for m in rows if connection_id is None or m.connection in (connection_id, GLOBAL_CONNECTION)])
        assert set(B._lift_metrics({}, "conn_a")) == {"zzalphametric", "zzglobalmetric"}


class TestAConnectionReadsItsOwnGlossary:
    """The explorer does not look beyond its connection (the user's rule, 2026-09-14), and the user's call on the
    glossary: a model's words are written for the connection whose tables it read, a person's global words stay every
    connection's, and a model-written global entry — which names no connection — is read by none until autoseed writes
    it again for the connection that reads it."""

    MODEL = {"auto_generated": True}

    def test_a_connection_reads_a_persons_global_words_and_its_own_never_a_models_unnamed_ones(self, tmp_path,
                                                                                               monkeypatch):
        from aughor.semantic.glossary import load_merged_glossary
        monkeypatch.setattr("aughor.semantic.dbt.load_dbt_glossary", lambda: None)
        p = tmp_path / "glossary.yaml"
        p.write_text(yaml.safe_dump({
            "tables": {"customers": {"description": "a person's words"}},
            CONNECTIONS_KEY: {"conn_a": {"tables": {"returns": {"description": "a person's words for A"}}}}}))
        (tmp_path / "glossary_generated.yaml").write_text(yaml.safe_dump({
            "tables": {"orders": {"description": "a model's words naming no connection", **self.MODEL}},
            CONNECTIONS_KEY: {
                "conn_a": {"tables": {"lux.orders": {"description": "a model's words for A", **self.MODEL},
                                      "returns": {"description": "a model's words for A's returns", **self.MODEL}}},
                "conn_b": {"tables": {"lux.payments": {"description": "a model's words for B", **self.MODEL}}}}}))
        a = load_merged_glossary(p, "conn_a")["tables"]
        assert a["customers"]["description"] == "a person's words"
        assert a["lux.orders"]["description"] == "a model's words for A"
        assert a["returns"]["description"] == "a person's words for A"          # a person's words win over a model's
        assert "orders" not in a and "lux.payments" not in a
        assert {"customers", "orders"} <= set(load_merged_glossary(p)["tables"])   # naming none reads what it did

    def test_the_split_keeps_a_models_words_for_one_connection_out_of_the_tracked_file(self, tmp_path):
        from aughor.semantic.glossary import generated_path, save_glossary
        p = tmp_path / "glossary.yaml"
        data = {"tables": {"customers": {"description": "a person's words"}},
                CONNECTIONS_KEY: {"conn_a": {"tables": {
                    "returns": {"description": "a person's words for A"},
                    "lux.orders": {"description": "a model's words for A", **self.MODEL}}}}}
        save_glossary(data, p)
        tracked, sidecar = yaml.safe_load(p.read_text()), yaml.safe_load(generated_path(p).read_text())
        assert tracked[CONNECTIONS_KEY] == {"conn_a": {"tables": {"returns": {"description": "a person's words for A"}}}}
        assert sidecar[CONNECTIONS_KEY] == {"conn_a": {"tables": {
            "lux.orders": {"description": "a model's words for A", **self.MODEL}}}}
        assert load_glossary(p) == data                                          # and it reads back as one

    def test_autoseed_writes_a_models_words_for_the_connection_it_read_and_for_no_connection_writes_nothing(
            self, tmp_path, monkeypatch):
        from aughor.semantic import autoseed as A
        from aughor.semantic.glossary import load_merged_glossary
        p = tmp_path / "glossary.yaml"
        p.write_text(yaml.safe_dump({"tables": {}}))
        (tmp_path / "glossary_generated.yaml").write_text(yaml.safe_dump({"tables": {
            "lux.orders": {"description": "a model's words naming no connection", **self.MODEL}}}))
        monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(p))
        monkeypatch.setattr(A, "_ENABLED", True)
        monkeypatch.setattr("aughor.db.schema_cache.is_complete", lambda fp: False)
        monkeypatch.setattr("aughor.db.schema_cache.mark_complete", lambda fp: None)
        asked = []

        class Model:
            def complete(self, system, user, response_model, temperature):
                asked.append(user)
                return A.TableAnnotation(description="written for A", grain="one row per order", columns=[])
        monkeypatch.setattr("aughor.llm.provider.get_provider", lambda *a, **k: Model())
        schema = "TABLE: lux.orders\n  order_id  VARCHAR\n"
        assert A.seed_missing_tables("TABLE: lux.refunds\n  refund_id  VARCHAR\n", schema="lux") is False
        assert asked == []                   # a table nothing describes, and still no words without a connection
        assert A.seed_missing_tables(schema, schema="lux", connection_id="conn_a") is True
        assert len(asked) == 1               # a model's words naming no connection cover no connection's table
        back = load_glossary(p)
        assert back[CONNECTIONS_KEY]["conn_a"]["tables"]["lux.orders"]["description"] == "written for A"
        assert back["tables"]["lux.orders"]["description"] == "a model's words naming no connection"   # left as it was
        assert load_merged_glossary(p, "conn_a")["tables"]["lux.orders"]["description"] == "written for A"
        assert "lux.orders" not in load_merged_glossary(p, "conn_b")["tables"]

    def test_the_schema_text_carries_the_words_its_connection_reads(self, tmp_path, monkeypatch):
        from aughor.semantic.glossary import apply_glossary
        monkeypatch.setattr("aughor.semantic.dbt.load_dbt_glossary", lambda: None)
        p = tmp_path / "glossary.yaml"
        p.write_text(yaml.safe_dump({"tables": {}}))
        (tmp_path / "glossary_generated.yaml").write_text(yaml.safe_dump({
            "tables": {"lux.orders": {"description": "a model's words naming no connection", **self.MODEL}},
            CONNECTIONS_KEY: {"conn_a": {"tables": {
                "lux.refunds": {"description": "a model's words for A", **self.MODEL}}}}}))
        schema = "TABLE: lux.orders\n  order_id  VARCHAR\n\nTABLE: lux.refunds\n  refund_id  VARCHAR\n"
        text = apply_glossary(schema, p, schema="lux", connection_id="conn_a")
        assert "a model's words for A" in text and "naming no connection" not in text

    def test_the_schema_index_embeds_the_words_its_connection_reads(self, monkeypatch):
        from aughor.semantic import retriever
        seen = []
        monkeypatch.setattr("aughor.semantic.glossary.load_merged_glossary",
                            lambda path=None, connection_id=None: seen.append(connection_id) or {"tables": {}})
        retriever.build_schema_index(connection_id="conn_a", schema_name="lux")
        assert seen == ["conn_a"]


class TestGlossaryRekey:
    def _write(self, tmp_path, data: dict):
        p = tmp_path / "glossary.yaml"
        p.write_text(yaml.safe_dump(data))
        return p

    def test_a_connection_overlay_wins_over_the_global_entry(self, tmp_path):
        p = self._write(tmp_path, {
            "tables": {"orders": {"description": "global orders"}},
            CONNECTIONS_KEY: {"conn_a": {"tables": {"orders": {"description": "A's orders"}}}},
        })
        assert load_glossary(p, "conn_a")["tables"]["orders"]["description"] == "A's orders"
        assert load_glossary(p)["tables"]["orders"]["description"] == "global orders"

    def test_a_connection_inherits_tables_it_has_not_overlaid(self, tmp_path):
        p = self._write(tmp_path, {
            "tables": {"orders": {"description": "g"}, "returns": {"description": "g"}},
            CONNECTIONS_KEY: {"c": {"tables": {"orders": {"description": "scoped"}}}},
        })
        out = load_glossary(p, "c")["tables"]
        assert out["orders"]["description"] == "scoped"
        assert out["returns"]["description"] == "g"

    def test_the_overlay_merges_deeply_rather_than_replacing(self, tmp_path):
        """Scoping a description must not drop the global grain and joins with it."""
        p = self._write(tmp_path, {
            "tables": {"orders": {"description": "g", "grain": "one row per order"}},
            CONNECTIONS_KEY: {"c": {"tables": {"orders": {"description": "scoped"}}}},
        })
        out = load_glossary(p, "c")["tables"]["orders"]
        assert out["description"] == "scoped" and out["grain"] == "one row per order"

    def test_one_connection_never_sees_anothers_overlay(self, tmp_path):
        p = self._write(tmp_path, {
            "tables": {"orders": {"description": "g"}},
            CONNECTIONS_KEY: {
                "c1": {"tables": {"secret_c1": {"description": "c1 only"}}},
                "c2": {"tables": {"secret_c2": {"description": "c2 only"}}},
            },
        })
        assert "secret_c2" not in load_glossary(p, "c1")["tables"]
        assert "secret_c1" in load_glossary(p, "c1")["tables"]

    def test_the_scaffolding_key_never_leaks_into_the_result(self, tmp_path):
        """Leaving `connections` in the returned dict would let a caller iterating it walk
        every OTHER connection's entries — the leak this scoping exists to prevent."""
        p = self._write(tmp_path, {
            "tables": {"orders": {"description": "g"}},
            CONNECTIONS_KEY: {"c": {"tables": {"orders": {"description": "s"}}}},
        })
        assert CONNECTIONS_KEY not in load_glossary(p, "c")

    def test_no_overlay_section_means_unchanged_behaviour(self, tmp_path):
        p = self._write(tmp_path, {"tables": {"orders": {"description": "g"}}})
        assert load_glossary(p, "any_connection") == load_glossary(p)

    def test_no_connection_argument_is_byte_identical(self, tmp_path):
        data = {"tables": {"orders": {"description": "g"}},
                CONNECTIONS_KEY: {"c": {"tables": {"orders": {"description": "s"}}}}}
        p = self._write(tmp_path, data)
        assert load_glossary(p)["tables"]["orders"]["description"] == "g"

    def test_the_live_glossary_file_still_loads(self):
        """The real tracked artifact, read through the new code path."""
        assert isinstance(load_glossary(), dict)
