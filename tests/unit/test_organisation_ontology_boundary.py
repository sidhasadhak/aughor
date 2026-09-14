"""An organisation's ontology is edited by people only, and the explorer does not look beyond its connection — the
user's two rules (2026-09-14), held by the shape of the import graph.

* An organisation's ontology (`aughor.ontology.domains`) is served and edited through the doors that take ``?domain=``,
  so exactly the ontology and object routers import it. A tool, an agent, the explorer or a scheduler that imported it
  could read the organisation's declarations into a prompt, or write one without a person.
* Its tree is written by `overrides.save_organisation_override` and `delete_organisation_override` alone — every other
  writer refuses its scope — and those are imported by the module that declares into it and the doors that withdraw
  from it, nothing else.
* The explorer — the autonomous data explorer (`aughor/explorer/`) and the drafting explorer
  (`aughor/ontology/explorer.py`, `aughor/ontology/drafts.py`) — imports none of what reads beyond one connection: the
  organisation's ontology, the source law that spans connections, the keyed read across them, the batched cross-source
  join, the federated planner and the connection selector.

Same mechanics as `test_ontology_llm_boundary`: stdlib `ast` over every source file (`ast.walk`, so a function-local
import counts), and EXACT equality for the importer lists — an importer added fails, and one removed but still listed
fails too, so a list moves only with the code.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUGHOR = REPO / "aughor"

#: Who imports the organisation's ontology: its doors.
DOMAIN_IMPORTERS = {"aughor/routers/ontology.py", "aughor/routers/objects.py"}
#: The organisation's own writer, and who imports it: the module that declares into it, and the doors that withdraw.
ORGANISATION_WRITERS = {"save_organisation_override", "delete_organisation_override"}
ORGANISATION_WRITER_IMPORTERS = {"aughor/ontology/domains.py", "aughor/routers/ontology.py"}
#: What reads beyond one connection. The explorer imports none of it.
BEYOND_ONE_CONNECTION = (
    "aughor.ontology.domains",
    "aughor.ontology.sources",
    "aughor.semantic.cross_source",
    "aughor.connectors.remote_join",
    "aughor.agent.federated_planner",
    "aughor.agent.connection_selector",
)


def _sources(root: Path):
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def _imports(path: Path) -> set[tuple[str, str]]:
    """Every ``(module, name)`` the file imports; ``name`` is "" for a bare ``import module``."""
    found: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found |= {(node.module, alias.name) for alias in node.names}
        elif isinstance(node, ast.Import):
            found |= {(alias.name, "") for alias in node.names}
    return found


def _reaches(imports: set[tuple[str, str]], module: str) -> bool:
    """``from aughor.ontology import domains`` reaches the module as surely as ``from aughor.ontology.domains import x``."""
    parent, _, leaf = module.rpartition(".")
    return any(m == module or m.startswith(module + ".") or (m == parent and n == leaf) for m, n in imports)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO))


def _explorer_files() -> list[Path]:
    return [*_sources(AUGHOR / "explorer"), AUGHOR / "ontology" / "explorer.py", AUGHOR / "ontology" / "drafts.py"]


def test_only_the_doors_import_the_organisations_ontology():
    found = {_rel(p) for p in _sources(AUGHOR) if _reaches(_imports(p), "aughor.ontology.domains")}
    found.discard("aughor/ontology/domains.py")
    assert found == DOMAIN_IMPORTERS, (
        f"added: {sorted(found - DOMAIN_IMPORTERS)} · no longer importing: {sorted(DOMAIN_IMPORTERS - found)} — an "
        "organisation's ontology is read and edited by people, through the doors that take ?domain=")


def test_only_the_declaring_module_and_the_withdrawing_doors_import_the_organisations_writer():
    found = {_rel(p) for p in _sources(AUGHOR)
             if any(m == "aughor.ontology.overrides" and n in ORGANISATION_WRITERS for m, n in _imports(p))}
    assert found == ORGANISATION_WRITER_IMPORTERS, (
        f"added: {sorted(found - ORGANISATION_WRITER_IMPORTERS)} · no longer importing: "
        f"{sorted(ORGANISATION_WRITER_IMPORTERS - found)} — an organisation's ontology is edited by people only")


def test_the_explorer_imports_nothing_that_reads_beyond_one_connection():
    files = _explorer_files()
    assert len(files) > 20 and all(f.exists() for f in files)     # the population is found on disk, not listed
    crossing = {_rel(f): [m for m in BEYOND_ONE_CONNECTION if _reaches(_imports(f), m)] for f in files}
    crossing = {f: modules for f, modules in crossing.items() if modules}
    assert not crossing, f"the explorer does not look beyond its connection (the user's rule, 2026-09-14): {crossing}"


def _calls(path: Path, name: str) -> list[ast.Call]:
    return [node for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
            if isinstance(node, ast.Call) and name in (getattr(node.func, "id", None), getattr(node.func, "attr", None))]


def test_the_explorer_ranks_the_playbook_by_relevance_alone():
    calls = [(f, c) for f in _explorer_files() for c in _calls(f, "retrieve_for_metric_and_phases")]
    assert calls, "the explorer no longer reads the playbook — retire this guard with the read"
    by_rate = [f"{_rel(f)}:{c.lineno}" for f, c in calls
               if not any(k.arg == "learned_rates" and isinstance(k.value, ast.Constant) and k.value.value is False
                          for k in c.keywords)]
    assert not by_rate, f"a playbook success rate is learned from outcomes on every connection: {by_rate}"


def test_every_read_of_the_glossary_for_a_prompt_names_its_connection():
    reads = [(p, c) for p in _sources(AUGHOR) if _rel(p) != "aughor/semantic/glossary.py"
             for name in ("load_merged_glossary", "apply_glossary") for c in _calls(p, name)]
    assert len(reads) >= 6                                            # the population is found, not listed
    unscoped = [f"{_rel(p)}:{c.lineno}" for p, c in reads if not any(k.arg == "connection_id" for k in c.keywords)]
    assert not unscoped, ("a glossary read that names no connection reads a model's words written for any connection "
                          f"(the user's rule, 2026-09-14): {unscoped}")


def test_the_scanner_can_actually_fire(tmp_path):
    """A scanner that sees nothing passes every assertion above — it must see both import forms, function-local ones
    included, and name the writer it imports."""
    probe = tmp_path / "probe.py"
    probe.write_text("import aughor.semantic.cross_source\n"
                     "def later():\n"
                     "    from aughor.ontology import domains\n"
                     "    from aughor.ontology.overrides import save_organisation_override\n")
    seen = _imports(probe)
    assert _reaches(seen, "aughor.semantic.cross_source") and _reaches(seen, "aughor.ontology.domains")
    assert ("aughor.ontology.overrides", "save_organisation_override") in seen
    assert not _reaches(seen, "aughor.connectors.remote_join")
