# Aughor installer for Windows.
#
# On a computer without Aughor, one line does everything, typed in Command Prompt or PowerShell:
# downloads Aughor into the aughor folder in your home folder, installs what it needs, starts it
# and opens it in the browser. Nothing has to be installed first, not even Git:
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/sidhasadhak/aughor/main/install.ps1 | iex"
#
# Inside a checkout:
#   install.cmd                install everything Aughor needs, start it, open it in a browser
#   install.cmd --no-start     install only
#   install.cmd --help         every option
#
# install.cmd runs this file without changing PowerShell's execution policy.
# Run it again whenever you like: it only redoes what changed.
#
# Like install.sh, this only finds the checkout (or downloads one) and gets uv, then hands over
# to `python -m aughor.installer`, which runs the same steps on every OS.
# Keep this file ASCII: Windows PowerShell 5.1 reads a script without a BOM as ANSI, so any
# other character here would be garbled.

# AUGHOR_REPO_URL and AUGHOR_ARCHIVE_URL install from a fork (or a local copy) instead.
$RepoUrl = if ($env:AUGHOR_REPO_URL) { $env:AUGHOR_REPO_URL } else { 'https://github.com/sidhasadhak/aughor.git' }
$ArchiveUrl = if ($env:AUGHOR_ARCHIVE_URL) { $env:AUGHOR_ARCHIVE_URL } else { 'https://github.com/sidhasadhak/aughor/archive/refs/heads/main.zip' }
$PythonVersion = '3.11'  # aughor/installer.py PYTHON_VERSION

function Write-Status([string]$Text) {
    Write-Host "  $Text"
    $script:Blank = $false
}

function Write-Ok([string]$Text) {
    Write-Host '  + ' -ForegroundColor Green -NoNewline
    Write-Host $Text
    $script:Blank = $false
}

function Write-Failure([string]$Text, [string]$Hint) {
    if (-not $script:Blank) { Write-Host '' }  # one blank line before a failure, never two
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

# A clone when this computer has Git, so the checkout can `git pull` later; otherwise the same
# code as a snapshot, so a fresh Windows (which has no Git) needs nothing installed first.
# Throws when neither way works.
# IN-3 — a preflight, so an unreachable network is named in a second rather than discovered
# three retries into the first slow step. Reachability only, short timeout, and it NEVER
# blocks: a probe that cannot run must not stop an install that would have worked.
function Test-Reachable([string]$HostName) {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072
        $null = Invoke-WebRequest -UseBasicParsing -Uri "https://$HostName" -Method Head -TimeoutSec 8 -ErrorAction Stop
    } catch {
        Write-Status ''
        Write-Status "Warning: $HostName did not answer. The next step downloads from it."
        Write-Status 'If this is a corporate network, a proxy or its certificate is the usual reason.'
        if (Test-CertificateFailure $_) { Show-ProxyHint }
    }
}

# IN-3 — one attempt is not an answer on a hostile network. Three tries, doubling from a
# second, matching install.sh's `fetch`. Its twin must not be the platform where a dropped
# connection still ends the install.
function Invoke-WithRetries([scriptblock]$Operation, [string]$What, [string]$Log) {
    $wait = 1
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            & $Operation
            return
        } catch {
            if (Test-CertificateFailure $_) { throw }     # not transient: fail now, with the hint
            if ($attempt -eq 3) { throw }
            "attempt $attempt for $What failed; retrying in ${wait}s" | Out-File -FilePath $Log -Append
            Start-Sleep -Seconds $wait
            $wait = $wait * 2
        }
    }
}

# IN-3 — a TLS-inspecting proxy re-signs the connection, and .NET's message names the
# certificate rather than the cause. Retrying it three times buys a slower identical failure.
function Test-CertificateFailure($ErrorRecord) {
    $text = "$ErrorRecord"
    return $text -match 'certificate|SSL|secure channel|trust relationship'
}

function Show-ProxyHint {
    Write-Status 'This looks like a TLS-inspecting proxy re-signing the connection.'
    Write-Status "Point PowerShell, Python and Node at your organisation's CA bundle, then run this again:"
    Write-Status '  $env:SSL_CERT_FILE = "C:\path\to\ca-bundle.pem"'
    Write-Status '  $env:NODE_EXTRA_CA_CERTS = "C:\path\to\ca-bundle.pem"'
}

function Get-Aughor([string]$Target, [string]$Log) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        & git clone --quiet $RepoUrl $Target *> $Log
        if ($LASTEXITCODE -eq 0) { return }
        # A failed clone's leftovers: the caller refused a folder with anything else in it.
        Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction SilentlyContinue
        # IN-3 — a throttled GitHub fails a full clone long before a blobless one, which
        # fetches far less to reach the same working tree. Then the snapshot path below, so a
        # hostile network degrades rather than stops.
        "full clone failed; trying a blobless clone" | Out-File -FilePath $Log -Append
        & git clone --quiet --filter=blob:none $RepoUrl $Target *>> $Log
        if ($LASTEXITCODE -eq 0) { return }
        Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction SilentlyContinue
    }
    $parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Force -Path $parent -ErrorAction Stop | Out-Null
    $staging = Join-Path $parent ('.aughor-download-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $previousProgress = $ProgressPreference
    try {
        New-Item -ItemType Directory -Path $staging -ErrorAction Stop | Out-Null
        $zip = Join-Path $staging 'aughor.zip'
        # Windows PowerShell draws Invoke-WebRequest's progress bar so slowly that it multiplies
        # the download time; nothing here needs it.
        $ProgressPreference = 'SilentlyContinue'
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072
        # A partial file from a cut-off attempt must never reach Expand-Archive: it would
        # surface as a corrupt archive rather than as a network problem.
        Invoke-WithRetries -What $ArchiveUrl -Log $Log -Operation {
            Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
            Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $zip -ErrorAction Stop
        }
        Expand-Archive -LiteralPath $zip -DestinationPath $staging -Force -ErrorAction Stop
        $unpacked = Get-ChildItem -LiteralPath $staging -Directory |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'pyproject.toml') } |
            Select-Object -First 1
        if (-not $unpacked) { throw 'The downloaded archive holds no Aughor checkout.' }
        Move-Item -LiteralPath $unpacked.FullName -Destination $Target -ErrorAction Stop
    } finally {
        $ProgressPreference = $previousProgress
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# The result goes in $script:ExitCode, never through `return`: a PowerShell function returns
# everything it outputs, so capturing it would also capture the installer's live output and
# nothing would reach the screen until the end. And never `exit` in here: under `irm | iex`
# this runs inside the user's own PowerShell session, whose window `exit` would close.
$script:ExitCode = 0
$script:Blank = $false

function Install-Aughor([string[]]$Arguments) {
    Write-Host ''
    Write-Host '  Aughor installer'
    Write-Host ''
    $script:Blank = $true  # the header ends with a blank line

    # -- Find the checkout (or download one) --
    if (Test-Checkout $PSScriptRoot) {
        $root = $PSScriptRoot
    } elseif (Test-Checkout (Get-Location).Path) {
        $root = (Get-Location).Path
    } else {
        $root = if ($env:AUGHOR_DIR) { $env:AUGHOR_DIR } else { Join-Path $HOME 'aughor' }
        if (-not (Test-Checkout $root)) {
            # Never write into a folder that holds anything else: a failed download is cleaned
            # up by deleting the folder, and that must only ever meet what the download put there.
            if ((Test-Path -LiteralPath $root) -and (Get-ChildItem -LiteralPath $root -Force | Select-Object -First 1)) {
                Write-Failure "$root already exists, and it isn't Aughor." 'Move it out of the way, or pick another folder by setting AUGHOR_DIR, then run this again.'
                $script:ExitCode = 1; return
            }
            Test-Reachable 'github.com'
            Write-Status "Downloading Aughor into $root..."
            $downloadLog = Join-Path $env:TEMP 'aughor-download.log'
            try {
                Get-Aughor $root $downloadLog
            } catch {
                Add-Content -LiteralPath $downloadLog -Value $_.Exception.Message -ErrorAction SilentlyContinue
                if (Test-CertificateFailure $_) { Show-ProxyHint }
                Write-Failure 'Could not download Aughor.' "Check your internet connection, then run this again. Log: $downloadLog"
                $script:ExitCode = 1; return
            }
            Write-Ok 'Aughor downloaded'
        }
        $root = (Resolve-Path -LiteralPath $root).Path
    }

    $logs = Join-Path $root '.aughor\logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null

    # -- Get uv, the one tool the rest cannot install through itself --
    $uv = Find-Uv
    if (-not $uv) {
        Write-Status 'Installing uv, the Python package manager Aughor uses...'
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
            Write-Status "Installing Python $PythonVersion..."
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
