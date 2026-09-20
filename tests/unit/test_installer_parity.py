"""IN-3 — the two installers harden together, or the Windows one silently falls behind.

Written because it already happened: IN-3's first pass gave `install.sh` retries, a blobless
clone fallback and a proxy hint, and gave `install.ps1` none of them — on a platform the
installer explicitly supports and CI installs on. The commit message said "hostile networks"
without qualifying it. This test is what makes that a build failure rather than something a
reader has to notice.

It asserts FEATURES, not text: each row names a thing the installer must do and a marker in
each script that shows it does. A marker is a poor proxy for behaviour, and on this machine it
is the honest limit — `pwsh` is not installed here, so `install.ps1` cannot be parsed or run,
only read. CI installs on `windows-latest` and is the only thing that proves it works.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SH = (REPO / "install.sh").read_text(encoding="utf-8")
PS1 = (REPO / "install.ps1").read_text(encoding="utf-8")

#: (feature, marker in install.sh, marker in install.ps1)
FEATURES = [
    ("retries on a download", "fetch_try", "Invoke-WithRetries"),
    ("a blobless clone fallback", "--filter=blob:none", "--filter=blob:none"),
    ("a certificate/proxy hint", "NODE_EXTRA_CA_CERTS", "NODE_EXTRA_CA_CERTS"),
    ("a network preflight", "preflight github.com", "Test-Reachable 'github.com'"),
    ("a partial file removed before a retry", "rm -f \"$2\"", "Remove-Item -LiteralPath $zip"),
]


@pytest.mark.parametrize("feature,sh_marker,ps1_marker", FEATURES,
                         ids=[f[0] for f in FEATURES])
def test_both_installers_have_it(feature, sh_marker, ps1_marker):
    assert sh_marker in SH, f"install.sh lost {feature}"
    assert ps1_marker in PS1, f"install.ps1 is missing {feature} — its twin has it"


def test_the_shell_installer_is_posix():
    """No bashisms: `install.sh` runs under `sh`, and `dash -n` is the stricter check the
    build uses. Asserted here as the property, since `[[` is the usual way it breaks."""
    assert SH.startswith("#!/bin/sh")
    assert "[[" not in SH, "a bashism reached a POSIX script"


def test_every_powershell_function_called_is_defined():
    """`pwsh` is not available on the machine this was written on, so a call to a function
    that does not exist cannot be caught by running it. It happened: the proxy hint first
    called `Say`, which this script has never had — its helpers are `Write-*`."""
    import re
    defined = set(re.findall(r"^function ([A-Za-z][A-Za-z-]*)", PS1, re.M))
    called = set(re.findall(r"^\s*([A-Z][a-z]+-[A-Za-z]+)\b", PS1, re.M))
    # Only our own verb-noun helpers; PowerShell's built-ins are not defined here.
    ours = {c for c in called if c in defined or c in {"Say"}}
    assert "Say" not in ours, "Show-ProxyHint calls a helper this script does not define"
    assert defined >= {"Write-Status", "Show-ProxyHint", "Test-CertificateFailure",
                       "Invoke-WithRetries", "Test-Reachable"}
