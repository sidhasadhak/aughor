# Aughor installer for Windows.
#
#   install.cmd                install everything Aughor needs, start it, open it in a browser
#   install.cmd --no-start     install only
#   install.cmd --help         every option
#
# install.cmd runs this file without changing PowerShell's execution policy. From PowerShell:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Or without cloning first (Aughor is downloaded into .\aughor):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/sidhasadhak/aughor/main/install.ps1 | iex"
#
# Run it again whenever you like: it only redoes what changed.
#
# Like install.sh, this only finds the checkout and gets uv, then hands over to
# `python -m aughor.installer`, which runs the same steps on every OS.
# Keep this file ASCII: Windows PowerShell 5.1 reads a script without a BOM as ANSI, so any
# other character here would be garbled.

# AUGHOR_REPO_URL installs from a fork (or a local clone) instead.
$RepoUrl = if ($env:AUGHOR_REPO_URL) { $env:AUGHOR_REPO_URL } else { 'https://github.com/sidhasadhak/aughor.git' }
$PythonVersion = '3.11'  # aughor/installer.py PYTHON_VERSION

function Write-Ok([string]$Text) {
    Write-Host '  + ' -ForegroundColor Green -NoNewline
    Write-Host $Text
}

function Write-Failure([string]$Text, [string]$Hint) {
    Write-Host ''
    Write-Host "  x $Text" -ForegroundColor Red
    if ($Hint) { Write-Host "  $Hint" }
    Write-Host ''
}

function Test-Checkout([string]$Dir) {
    if (-not $Dir) { return $false }
    $pyproject = Join-Path $Dir 'pyproject.toml'
    if (-not (Test-Path -LiteralPath $pyproject)) { return $false }
    if (-not (Test-Path -LiteralPath (Join-Path $Dir 'web\package.json'))) { return $false }
    return [bool](Select-String -LiteralPath $pyproject -Pattern '^name = "aughor"' -Quiet)
}

function Find-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @((Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
                             (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'))) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

# The result goes in $script:ExitCode, never through `return`: a PowerShell function returns
# everything it outputs, so capturing it would also capture the installer's live output and
# nothing would reach the screen until the end. And never `exit` in here: under `irm | iex`
# this runs inside the user's own PowerShell session, whose window `exit` would close.
$script:ExitCode = 0

function Install-Aughor([string[]]$Arguments) {
    Write-Host ''
    Write-Host '  Aughor installer'
    Write-Host ''

    # -- Find the checkout (or download one) --
    if (Test-Checkout $PSScriptRoot) {
        $root = $PSScriptRoot
    } elseif (Test-Checkout (Get-Location).Path) {
        $root = (Get-Location).Path
    } else {
        $root = if ($env:AUGHOR_DIR) { $env:AUGHOR_DIR } else { Join-Path (Get-Location).Path 'aughor' }
        if (-not (Test-Checkout $root)) {
            if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
                Write-Failure 'Git is needed to download Aughor.' 'Install Git (https://git-scm.com/download/win), then run this again.'
                $script:ExitCode = 1; return
            }
            Write-Host "  Downloading Aughor into $root..."
            & git clone --quiet $RepoUrl $root
            if ($LASTEXITCODE -ne 0) {
                Write-Failure 'Could not download Aughor.' 'Check your internet connection, then run this again.'
                $script:ExitCode = 1; return
            }
            Write-Ok 'Aughor downloaded'
        }
    }

    $logs = Join-Path $root '.aughor\logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null

    # -- Get uv, the one tool the rest cannot install through itself --
    $uv = Find-Uv
    if (-not $uv) {
        Write-Host '  Installing uv, the Python package manager Aughor uses...'
        $log = Join-Path $logs 'uv-install.log'
        $command = '[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://astral.sh/uv/install.ps1 | iex'
        Start-Process -FilePath 'powershell.exe' -Wait -NoNewWindow `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $command) `
            -RedirectStandardOutput $log -RedirectStandardError "$log.err"
        $uv = Find-Uv
        if (-not $uv) {
            Write-Failure 'Could not install uv.' "Check your internet connection, then run this again. Log: $log"
            $script:ExitCode = 1; return
        }
        Write-Ok 'uv installed'
        $env:AUGHOR_UV_INSTALLED = '1'
    }
    $env:Path = (Split-Path -Parent $uv) + ';' + $env:Path

    $uvVersion = ((& $uv --version) -split ' ')[1]
    if ($uvVersion -match '^0\.[0-7](\.|$)') {
        Write-Failure "uv $uvVersion is too old for Aughor." 'Update it (uv self update), then run this again.'
        $script:ExitCode = 1; return
    }

    # The hint for next time has to name the checkout when this terminal is not in it.
    $checkoutElsewhere = $root -ne (Get-Location).Path
    Push-Location $root
    try {
        if ($checkoutElsewhere) { $env:AUGHOR_CHECKOUT_DIR = $root }
        & $uv python find $PythonVersion *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Installing Python $PythonVersion..."
            $log = Join-Path $logs 'python-install.log'
            & $uv python install $PythonVersion *> $log
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "Could not install Python $PythonVersion." "Check your internet connection, then run this again. Log: $log"
                $script:ExitCode = 1; return
            }
            Write-Ok "Python $PythonVersion installed"
        }

        # -- Hand over: every remaining step is the same on every OS --
        # --isolated --no-project: a throwaway environment, never the project's .venv, which
        # the first step may have to rebuild (and which Windows locks while it runs).
        $env:AUGHOR_BOOTSTRAP = '1'
        & $uv run --quiet --no-project --isolated --python $PythonVersion python -m aughor.installer @Arguments
        $script:ExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
        Remove-Item Env:\AUGHOR_BOOTSTRAP -ErrorAction SilentlyContinue
        Remove-Item Env:\AUGHOR_UV_INSTALLED -ErrorAction SilentlyContinue
        Remove-Item Env:\AUGHOR_CHECKOUT_DIR -ErrorAction SilentlyContinue
    }
}

Install-Aughor $args
if ($PSCommandPath) { exit $script:ExitCode }  # run as a file (install.cmd): hand the result back
