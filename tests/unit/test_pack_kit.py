"""Phase 7 of the 2027 study, P7-3 — the pack kit (`aughor/packs/kit.py`) and a pack's measured record
(`aughor/packs/record.py`).

What these hold: the kit refuses what is not a pack of declarations (no manifest, a path outside the
pack, a code file), runs the static gate without writing, and writes a passing pack as a draft under the
imported root with its provenance; an upload cannot shadow an authored pack; the guide is read from the
models; a pack's record counts what installs found of its claims; a demotion is refused when the record
does not call for it and forced only with a reason; the listing is the record.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.packs import kit as KIT
from aughor.packs import record as PR
from aughor.packs.loader import load_pack
from aughor.routers import packs as R


def _files(pack_id: str, **extra) -> dict[str, str]:
    files = {"pack.yaml": f"id: {pack_id}\nname: Test pack\nversion: 1\nstatus: active\ndomains: [testing]\n",
             "monitors/return_rate.yaml": "id: return_rate\nmetric: return_rate\nunmeasured: true\n",
             "missions/hold.yaml": "id: hold\nname: Hold the line\ncadence: monthly\nobjective: {metric: return_rate, direction: down}\n"}
    files.update(extra)
    return files


@pytest.fixture(autouse=True)
def _imported_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path / "imported"))


def test_the_kit_refuses_what_is_not_a_pack_of_declarations():
    assert KIT.path_problems({}) == ["no files"]
    problems = KIT.path_problems({"metrics/x.yaml": "name: x", "../escape.yaml": "a: 1", "run.py": "print(1)"})
    assert any("no pack.yaml" in p for p in problems) and any("stays inside the pack" in p for p in problems)
    assert any("never code" in p for p in problems)
    out = KIT.check({"pack.yaml": "id: t\nname: t\n", "x.py": "1"})
    assert out["ok"] is False and any("never code" in e for e in out["errors"])
    bare = KIT.check(_files("t-" + uuid.uuid4().hex[:4], **{"monitors/nim.yaml": "id: nim\nmetric: nim\nlow: 0.02\nhigh: 0.09\n"}))
    assert bare["ok"] is False and any("measured_on" in e for e in bare["errors"])
    with pytest.raises(KIT.KitRefused, match="did not pass the static gate"):
        KIT.upload({"pack.yaml": "id: t\nname: t\n", "x.py": "1"}, by="user:ana")
    with pytest.raises(KIT.KitRefused, match="named principal"):
        KIT.upload(_files("t-" + uuid.uuid4().hex[:4]), by="")


def test_a_passing_pack_is_checked_without_writing_and_uploaded_as_a_draft_with_its_provenance():
    from aughor.packs.roots import imported_root
    pid = "acme-" + uuid.uuid4().hex[:6]
    verdict = KIT.check(_files(pid))
    assert verdict["ok"] and verdict["pack_id"] == pid and verdict["declares"]["monitors"] == 1 and verdict["declares"]["missions"] == 1
    assert not (imported_root() / pid).exists()
    out = KIT.upload(_files(pid), by="user:ana", source_url="https://example.com/acme-pack")
    assert out["status"] == "draft" and out["written_to"].endswith(pid) and "activates it" in out["next"]
    pack = load_pack(imported_root() / pid)
    assert pack.manifest.status == "draft" and pack.manifest.source == "upload" and pack.manifest.source_url == "https://example.com/acme-pack"
    raw = (imported_root() / pid / "pack.yaml").read_text()
    assert "uploaded_by: user:ana" in raw and "uploaded_at:" in raw
    from aughor.packs.roots import all_pack_ids
    assert pid in all_pack_ids()
    with pytest.raises(KIT.KitRefused, match="already exists"):
        KIT.upload(_files(pid), by="user:ana")
    again = KIT.upload(_files(pid, **{"monitors/second.yaml": "id: second\nmetric: s\nunmeasured: true\n"}), by="user:bo", overwrite=True)
    assert again["declares"]["monitors"] == 2
    with pytest.raises(KIT.KitRefused, match="cannot shadow"):
        KIT.upload(_files("core-ecommerce"), by="user:ana")
    # the door
    from fastapi import HTTPException
    checked = R.post_pack_check(R.PackFilesIn(files=_files("door-" + uuid.uuid4().hex[:4])))
    assert checked["ok"]
    with pytest.raises(HTTPException) as e:
        R.post_pack_upload(R.PackFilesIn(files={"pack.yaml": "id: t\nname: t\n", "x.py": "1"}), request=type("Rq", (), {"state": type("S", (), {"principal": None})()})())
    assert e.value.status_code == 422


def test_the_guide_is_read_from_the_models_and_names_the_gates():
    g = KIT.guide()
    files = {a["file"] for a in g["anatomy"]}
    assert {"pack.yaml", "ontology.yaml", "monitors/*.yaml", "missions/*.yaml", "scenarios/*.yaml", "datasets/*.yaml"} <= files
    manifest = next(a for a in g["anatomy"] if a["file"] == "pack.yaml")
    assert "id" in manifest["schema"]["required"] and "status" in manifest["schema"]["fields"]
    monitor = next(a for a in g["anatomy"] if a["file"] == "monitors/*.yaml")
    assert {"metric", "low", "high", "measured_on", "unmeasured"} <= set(monitor["schema"]["fields"])
    assert {"static validation", "gate 3", "the priors' rule", "activation by evals", "gate 4", "the measured record"} <= {x["gate"] for x in g["gates"]}
    assert "never code" in g["principle"] and g["limits"]["files"] == KIT.MAX_FILES and R.get_pack_kit()["version"] == g["version"]


def test_a_packs_record_counts_what_installs_found_and_demotes_only_on_the_record():
    from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyRelationship
    from aughor.packs.ontology_map import apply_core_claims, record_claims, resolve_ontology
    pid = "rec-" + uuid.uuid4().hex[:6]
    KIT.upload(_files(pid, **{"ontology.yaml": ("objects:\n  - {name: Order, aliases: [orders]}\n  - {name: Customer, aliases: [customers]}\n"
                                                "  - {name: Ghost, aliases: [ghosts]}\nlinks:\n"
                                                "  - {from_object: Order, to_object: Customer, cardinality: '1:1', via: customer_id}\n")}), by="user:ana")
    empty = PR.measured_record(pid)
    assert empty["claims"]["measured"] == 0 and "no install has measured" in empty["claims"]["note"] and empty["demotion"]["due"] is False
    assert any(j["kind"] == "pack.uploaded" for j in empty["journal"])
    conn = "conn-" + uuid.uuid4().hex[:6]
    g = OntologyGraph(connection_id=conn, schema_name="s", schema_fingerprint="fp")
    g.entities["Order"] = OntologyEntity(id="Order", display_name="Order", source_tables=["s.orders"], identity_key="id", grain_verified=True)
    g.entities["Customer"] = OntologyEntity(id="Customer", display_name="Customer", source_tables=["s.customers"], identity_key="id", grain_verified=True)
    g.relationships["oc"] = OntologyRelationship(id="oc", from_entity="Order", to_entity="Customer", cardinality="N:1", join_sql="x",
                                                 from_table="s.orders", from_col="customer_id", to_table="s.customers", to_col="id",
                                                 measured_cardinality="N:1")
    report = apply_core_claims(g, resolve_ontology(pid), pid, None)
    record_claims(report, g, conn, "s")
    rec = PR.measured_record(pid)
    assert rec["claims"]["supported"] == 2 and rec["claims"]["refuted"] == 1 and rec["claims"]["open"] == 1
    assert rec["claims"]["measured"] == 3 and rec["claims"]["held_share"] == 0.667 and rec["claims"]["connections"] == 1
    assert rec["demotion"]["due"] is False and "10 or more" in rec["demotion"]["why"]
    assert PR.demotion_verdict({"measured": 12, "refuted": 7})["due"] is True
    assert PR.demotion_verdict({"measured": 12, "refuted": 3})["due"] is False
    with pytest.raises(ValueError, match="does not call for a demotion"):
        PR.demote(pid, by="user:ana")
    with pytest.raises(ValueError, match="says why"):
        PR.demote(pid, by="user:ana", force=True)
    out = PR.demote(pid, by="user:ana", force=True, why="the author withdrew it")
    assert out["status"] == "deprecated" and out["demoted"] and any(j["kind"] == "pack.demoted" and j.get("forced") for j in out["journal"])
    listed = {p["id"]: p for p in PR.listing()}
    assert listed[pid]["status"] == "deprecated" and listed[pid]["claims"]["measured"] == 3 and "core-ecommerce" in listed
    door = R.get_pack_listing()
    assert any(p["id"] == pid for p in door["packs"]) and "demoted by the same record" in door["rule"]
    assert R.get_pack_record(pid)["claims"]["refuted"] == 1
