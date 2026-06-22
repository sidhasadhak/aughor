"""Per-dataset domain-pass construction — the "every dataset gets understood"
guarantee. Extracted from explorer/agent._phase8_domain_intelligence so the
dataset-split algorithm is unit-testable on its own.

Origin: on a multi-dataset connection a domain's entities can span unrelated
uploaded datasets; keeping only the dominant dataset's entities silently dropped
the rest, so a single-table catalog like ``netflix.netflix_titles`` got ZERO
exploration and ZERO briefing (it just vanished). Splitting into one pass per
dataset must drop nothing.
"""
from aughor.explorer.agent import _build_domain_passes


def test_single_dataset_one_pass_per_domain():
    de = {"Commerce": ["e1", "e2"], "Finance": ["e3"]}
    passes, splits = _build_domain_passes(de, multi_dataset=False, entity_ds=lambda e: "unused")
    assert passes == [("Commerce", "Commerce", ["e1", "e2"]), ("Finance", "Finance", ["e3"])]
    assert splits == []


def test_multi_dataset_single_dataset_domain_kept_whole():
    de = {"Finance": ["f1", "f2"]}
    passes, splits = _build_domain_passes(de, True, lambda e: "ecommerce")
    assert passes == [("Finance", "Finance", ["f1", "f2"])]
    assert splits == []


def test_multi_dataset_domain_splits_one_pass_per_dataset():
    ds_of = {"m1": "bakehouse", "m2": "bakehouse", "m3": "netflix"}
    passes, splits = _build_domain_passes({"Marketing": ["m1", "m2", "m3"]}, True, lambda e: ds_of[e])
    assert ("Marketing · bakehouse", "Marketing", ["m1", "m2"]) in passes
    assert ("Marketing · netflix", "Marketing", ["m3"]) in passes
    assert splits == [("Marketing", ["bakehouse", "netflix"])]


def test_minority_single_table_dataset_is_not_dropped():
    # netflix (1 entity) loses the dominance contest to ecommerce (3) — but must
    # still get its OWN pass, not vanish. This is the regression the split fixed.
    ds_of = {"o1": "ecommerce", "o2": "ecommerce", "o3": "ecommerce", "nf": "netflix"}
    passes, _ = _build_domain_passes({"Content": ["o1", "o2", "o3", "nf"]}, True, lambda e: ds_of[e])
    labels = [p[0] for p in passes]
    assert "Content · netflix" in labels
    nf_pass = next(p for p in passes if p[0] == "Content · netflix")
    assert nf_pass[2] == ["nf"]


def test_unknown_dataset_entities_ride_with_primary():
    # An entity whose dataset can't be determined ('') must not be dropped — it
    # rides with the largest (primary) group.
    ds_of = {"a": "ds1", "b": "ds1", "c": "ds2", "u": ""}
    passes, _ = _build_domain_passes({"D": ["a", "b", "c", "u"]}, True, lambda e: ds_of[e])
    ds1_pass = next(p for p in passes if p[0] == "D · ds1")
    assert set(ds1_pass[2]) == {"a", "b", "u"}      # unknown rode with the primary
    ds2_pass = next(p for p in passes if p[0] == "D · ds2")
    assert ds2_pass[2] == ["c"]
