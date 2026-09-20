"""IN-2 — the README's install section says only what is true, and stays that way.

Written after the first draft of that section claimed CI installs on three operating systems
"every commit". It does not: `.github/workflows/install.yml` is `pull_request` + `push` to
main, both filtered to the paths that affect installing. The claim was corrected before it
landed, and these tests exist so the next one is caught by a run rather than by a reader.

The shape is deliberate: every command the section shows must RESOLVE, and every flag it
documents must exist. A page that tells a person to run something that is not there is the
same defect as a roadmap entry that describes a feature nobody built.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "README.md").read_text(encoding="utf-8")


def _section() -> str:
    start = README.index("### What it installs, and where")
    end = README.index("## Pick your models")
    return README[start:end]


class TestEveryCommandResolves:
    def test_the_aughor_subcommands_it_shows_exist(self):
        from aughor.cli import cli
        shown = set(re.findall(r"^aughor ([a-z-]+)", _section(), re.M))
        assert shown, "probe failed: the section shows no aughor commands"
        available = set(cli.commands)
        assert shown <= available, {"documented but absent": sorted(shown - available)}

    def test_the_installer_flags_it_documents_exist(self):
        """Parsed in `installer.py`'s argparse — `install.sh` only forwards them, which is why
        the first version of this test looked in the wrong file and failed."""
        parser_source = (REPO / "aughor" / "installer.py").read_text(encoding="utf-8")
        for flag in ("--industries", "--no-start"):
            assert f'"{flag}"' in parser_source, (
                f"{flag} is documented in the README and is not an installer argument")

    def test_the_env_vars_it_documents_are_read_somewhere(self):
        script = (REPO / "install.sh").read_text(encoding="utf-8")
        assert "AUGHOR_DIR" in script
        assert "AUGHOR_INDUSTRIES" in script or "AUGHOR_INDUSTRIES" in (
            REPO / "aughor" / "installer.py").read_text(encoding="utf-8")


class TestItClaimsOnlyWhatIsMeasured:
    def test_it_does_not_assert_wsl2_works(self):
        """§6 item 25(e): measure the installer there first, then say so. Nobody has."""
        section = _section().lower()
        assert "wsl2" in section, "WSL2 should be addressed, not silently omitted"
        assert "does not claim it" in section, "WSL2 must be named as unmeasured"

    def test_the_ci_claim_matches_the_workflow(self):
        """The overclaim this file was written for."""
        workflow = (REPO / ".github" / "workflows" / "install.yml").read_text(encoding="utf-8")
        assert "windows-latest" in workflow and "macos-latest" in workflow
        assert "paths:" in workflow, "the workflow is path-filtered"
        assert "every commit" not in _section(), (
            "the section claims CI runs on every commit; install.yml is path-filtered")

    def test_the_node_major_it_names_is_the_one_installed(self):
        from aughor.installer import NODE_LTS_MAJOR
        assert f"Node {NODE_LTS_MAJOR}" in _section()

    def test_the_proxy_variables_match_the_installers_own_hint(self):
        from aughor.installer import _PROXY_HINT
        for var in ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS"):
            assert var in _section() and var in _PROXY_HINT
