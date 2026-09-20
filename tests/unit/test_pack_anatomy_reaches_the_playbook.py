"""IP — the plays an industry package DECLARES reach the playbook store.

Measured before this wave, on `5e6b9df8`: the agent runtime consumed no part of a package's
anatomy. `playbooks/*.yaml` had five readers — `gate3`, `gate4`, `validate`, the packs API and
the `list_packs` tool — and every one of them is a gate or a surface. The steering path could
not reach them by construction: `PackManifest.steers` is False for every knowledge layer, and
`intake.active_packs` (the pool `inject` renders from) filters on `steers`. So airline's eight
bound plays and banking's fifty-one reproduced FDIC figures sharpened no answer.

These tests pin the four properties that make the seam honest rather than merely present:
the plays arrive, they are ATTRIBUTED to their industry, a DRAFT package's plays do not arrive,
and a data-quality play stays a rule-out instead of becoming a recommendation.
"""
from __future__ import annotations

import json

from aughor.packs.knowledge import entry_industry, pack_play_source
from aughor.playbook.builder import _load_all_pack_plays, _pack_play_entry, seed_from_packs
from aughor.playbook.models import DATA_QUALITY_TAG
from aughor.playbook.retriever import is_data_quality
from aughor.playbook.store import list_entries


def _empty(tmp_path):
    p = tmp_path / "playbook.json"
    p.write_text("[]")
    return p


class TestThePlaysArrive:
    def test_airlines_declared_plays_reach_the_store(self, tmp_path):
        path = _empty(tmp_path)
        counts = seed_from_packs(path)
        ids = {e.id for e in list_entries(path)}
        # A specific play, named — a bare `added > 0` would pass for any pack that happened to
        # be active, and this suite exists because a thing that looked present was absent.
        assert any("cancellations_split_by_cause" in i for i in ids), sorted(ids)
        assert counts["added"] == len(ids) > 0

    def test_the_source_id_round_trips_through_its_one_writer(self, tmp_path):
        path = _empty(tmp_path)
        seed_from_packs(path)
        rows = [e for e in list_entries(path) if "cancellations_split_by_cause" in e.id]
        assert rows, "the play under test is not in the store"
        assert rows[0].source_kb_id == pack_play_source("airline", "cancellations-split-by-cause")


class TestAttribution:
    """The leak this seam could have introduced: `entry_industry` returns "" for an id it does
    not know, and "" means EVERY industry may read the row. An airline play offered on a retail
    connection would be the failure, and it would look like success."""

    def test_a_pack_play_is_owned_by_its_packages_industry(self, tmp_path):
        path = _empty(tmp_path)
        seed_from_packs(path)
        owners = {entry_industry(e.source_kb_id) for e in list_entries(path)}
        assert owners == {"airline"}, owners

    def test_no_seeded_play_is_readable_by_every_industry(self, tmp_path):
        path = _empty(tmp_path)
        seed_from_packs(path)
        shared = [e.id for e in list_entries(path) if entry_industry(e.source_kb_id) == ""]
        assert shared == [], f"these would be offered on every connection: {shared}"


class TestGateSix:
    def test_a_draft_packages_plays_are_not_seeded(self, tmp_path):
        """`packs/banking` ships `status: draft`, and gate 6's rule is that no agent reads a
        package until a person activates it. Sourcing through `knowledge_index()` honours that
        by construction rather than by a second status check that could drift."""
        path = _empty(tmp_path)
        seed_from_packs(path)
        banking = [e.id for e in list_entries(path) if "banking" in e.id]
        assert banking == [], banking
        assert "banking" not in {pack_id for pack_id, _ in _load_all_pack_plays()}


class TestADataQualityPlayStaysARuleOut:
    def test_airlines_rule_out_arrives_as_a_rule_out(self, tmp_path):
        """End to end on the real pack. NOTE this does NOT exercise the kind -> tag mapping:
        `cancellation-without-a-reason.yaml` already carries a literal `data quality` tag, so
        this passes whether or not `_pack_play_entry` derives one. Measured by mutation — the
        test below is the one that holds the mapping."""
        path = _empty(tmp_path)
        seed_from_packs(path)
        rows = {e.id: e for e in list_entries(path)}
        dq = [e for e in rows.values() if is_data_quality(e)]
        assert any("cancellation_without_a_reason" in e.id for e in dq), sorted(rows)

    def test_kind_data_quality_derives_the_tag_when_the_pack_omits_it(self):
        """The mapping itself, on a play that declares the kind and NO tag — gate 3 does not
        require the two to agree, so a pack may say `kind: data_quality` and tag nothing, and
        such a play must still reach the Verifier as a rule-out rather than a recommendation."""
        class _Untagged:
            id = "silent-rule-out"
            recommendation = "check the column before trusting the number"
            kind = "data_quality"
            tags: list = []
        entry = _pack_play_entry("airline", _Untagged())
        assert entry is not None
        assert DATA_QUALITY_TAG in entry.tags
        assert is_data_quality(entry)

    def test_a_practice_play_is_not_marked_data_quality(self, tmp_path):
        path = _empty(tmp_path)
        seed_from_packs(path)
        rows = [e for e in list_entries(path) if "cancellations_split_by_cause" in e.id]
        assert rows and not is_data_quality(rows[0])


class TestOwnerRoleComesFromThePack:
    """`_build_entries_for_kb` hardcodes "Data Analyst" on all three of its constructors, which
    is why the live store reads "Data Analyst" on all 878 rows — a column that looks like
    information and carries none. A pack names a real owner; do not default it away."""

    def test_the_pack_names_more_than_one_owner(self, tmp_path):
        path = _empty(tmp_path)
        seed_from_packs(path)
        roles = {e.owner_role for e in list_entries(path)}
        assert "Operations Control" in roles, roles
        assert len(roles) > 1, roles


class TestManners:
    def test_seeding_twice_adds_nothing_the_second_time(self, tmp_path):
        path = _empty(tmp_path)
        first = seed_from_packs(path)
        before = len(list_entries(path))
        second = seed_from_packs(path)
        assert first["added"] == before > 0
        assert second["added"] == 0
        assert len(list_entries(path)) == before

    def test_a_play_a_person_deleted_stays_deleted(self, tmp_path):
        path = _empty(tmp_path)
        seed_from_packs(path)
        rows = list_entries(path)
        dropped = rows[0]
        path.write_text(json.dumps([e.model_dump() for e in rows[1:]], default=str))
        counts = seed_from_packs(path)
        assert counts["kept_deleted"] >= 1
        assert dropped.id not in {e.id for e in list_entries(path)}

    def test_an_incomplete_play_is_skipped_not_raised(self):
        class _Bare:
            id = ""
            recommendation = "something"
        assert _pack_play_entry("airline", _Bare()) is None

    def test_an_unknown_trigger_operator_becomes_any(self):
        class _Odd:
            id = "x"
            recommendation = "do the thing"
            trigger_operator = "ABOVE"
            trigger_metric = "otp"
        entry = _pack_play_entry("airline", _Odd())
        assert entry is not None and entry.trigger_operator == "any"
