# Droid statusline — Windows (PowerShell).
#
# One line, same shape as the bash version and the Claude Code rich statusline:
#
#   📊 Context: ▓░░░░░░░░░ 9% (36k/400k) │ 5h: ██▓░░░░░░░ 28% (2h32m) │
#   7d: ▓░░░░░░░░░ 6% (2d10h) │ Month: ▓░░░░░░░░░ 5% (25d4h) │ 📁 web-business
#
# Context and the working directory come from the JSON Droid pipes in on every
# tick. The Factory plan numbers do not — they need the billing limits API, so
# this script refreshes a cache file in a detached child process and otherwise
# only reads it.
#
# Needs Windows Terminal (or any host with VT / 24-bit color), and PowerShell 5.1+.
# No jq needed — ConvertFrom-Json is built in. The Factory plan numbers come from
# a small Node worker (fetch-usage.mjs) spawned in the background; without Node
# the line still renders context and directory. That is deliberate: the credential
# file is AES-GCM with a 16-byte nonce, and .NET's AesGcm accepts only 12, so a
# native PowerShell decrypt is not possible. One Node path serves every platform
# and keeps the numbers identical.
#
# Invoke with -RefreshOnly to refresh the usage cache and exit.

[CmdletBinding()]
param(
    [switch]$RefreshOnly
)

$ErrorActionPreference = 'Stop'

# Make sure we emit UTF-8 so the block characters and emoji render correctly.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$FactoryDir = if ($env:FACTORY_HOME) { $env:FACTORY_HOME } else { Join-Path $HOME '.factory' }
$CachePath  = Join-Path $FactoryDir 'statusline-usage.json'
$LockPath   = Join-Path $FactoryDir 'statusline-usage.lock'
$LogPath    = Join-Path $FactoryDir 'statusline-usage.log'
$RefreshScript = Join-Path $FactoryDir 'statusline-fetch-usage.mjs'

$FreshSeconds  = 60    # cache younger than this: render as-is, no refresh
$UsableSeconds = 900   # cache older than this: drop the usage segments
$LockMaxAge    = 30    # ignore a lock older than this (a refresh that died)

# ---------------------------------------------------------------------------
# Usage cache refresh
# ---------------------------------------------------------------------------

function Write-Log([string]$Message) {
    try {
        $stamp = [DateTime]::UtcNow.ToString('o')
        Add-Content -LiteralPath $LogPath -Value "$stamp $Message" -ErrorAction SilentlyContinue
    } catch {
        # A status line must never fail loudly.
    }
}

function Find-Node {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    # Standard install locations, checked only when the base directory exists.
    # Join-Path throws on a null base, and ProgramFiles(x86) is absent on ARM
    # Windows, so each candidate is guarded rather than assumed.
    $candidates = @()
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($base) { $candidates += (Join-Path $base 'nodejs\node.exe') }
        if ($base) { $candidates += (Join-Path $base 'Programs\nodejs\node.exe') }
    }
    $candidates += @('/opt/homebrew/bin/node', '/usr/local/bin/node', '/usr/bin/node')

    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    return $null
}

function Start-UsageRefresh {
    if (-not (Test-Path -LiteralPath $RefreshScript)) {
        Write-Log "worker not found at $RefreshScript; skipping refresh"
        return
    }

    $node = Find-Node
    if (-not $node) {
        Write-Log 'node not found; skipping refresh'
        return
    }

    try {
        # Detached: the status line must not wait on a network round trip.
        Start-Process -FilePath $node -WindowStyle Hidden -ArgumentList @(
            "`"$RefreshScript`""
        ) | Out-Null
    } catch {
        Write-Log "background refresh spawn failed ($($_.Exception.Message))"
    }
}

if ($RefreshOnly) {
    # Foreground, so a person debugging can see the outcome.
    if (-not (Test-Path -LiteralPath $RefreshScript)) {
        Write-Host "worker not found at $RefreshScript"
        exit 1
    }
    $node = Find-Node
    if (-not $node) {
        Write-Host 'node not found on PATH'
        exit 1
    }
    & $node $RefreshScript
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

function Format-K([double]$n) {
    if ($n -ge 1000000) { return ('{0:N1}M' -f ($n / 1000000)) }
    if ($n -ge 1000)    { return ('{0:N0}k' -f [math]::Round($n / 1000)) }
    return "$([int]$n)"
}

# Rounded whole percent, but never "0%" for a real, tiny amount of usage.
function Format-Percent([double]$p) {
    if ($p -gt 0 -and $p -lt 0.5) { return '<1' }
    return "$([int][math]::Round($p))"
}

# 10-cell bar with half-cell ▓ resolution. Color is a smooth truecolor gradient
# from green (0%) → yellow (50%) → red (100%), so the bar's hue itself encodes
# severity — you can read the line peripherally without parsing the numbers.
function Render-Bar([double]$p) {
    if ($p -lt 0)   { $p = 0 }
    if ($p -gt 100) { $p = 100 }

    $cells = 10
    $full  = [int][math]::Floor($p / 10)
    $rem   = $p - $full * 10
    $half  = ($rem -ge 5) -and ($full -lt $cells)

    if ($p -le 50) { $r = [int][math]::Round($p / 50.0 * 255); $g = 255 }
    else           { $r = 255; $g = [int][math]::Round((100 - $p) / 50.0 * 255) }

    $sb = [System.Text.StringBuilder]::new()
    for ($i = 0; $i -lt $full; $i++) { [void]$sb.Append([char]0x2588) }      # █
    if ($half) { [void]$sb.Append([char]0x2593); $full++ }                   # ▓
    for ($i = $full; $i -lt $cells; $i++) { [void]$sb.Append([char]0x2591) } # ░

    $esc = [char]27
    return "$esc[38;2;$r;$g;0m$($sb.ToString())$esc[0m"
}

# Coarsest useful unit, so a month-long window reads "25d" not "600h".
function Format-Countdown([double]$Seconds) {
    if ($Seconds -le 0) { return 'now' }
    $secs  = [int]$Seconds
    $days  = [int][math]::Floor($secs / 86400)
    $hours = [int][math]::Floor(($secs % 86400) / 3600)
    $mins  = [int][math]::Floor(($secs % 3600) / 60)

    if ($days -ge 1) {
        if ($hours -gt 0) { return "${days}d${hours}h" }
        return "${days}d"
    }
    if ($hours -ge 1) {
        if ($mins -gt 0) { return "${hours}h${mins}m" }
        return "${hours}h"
    }
    return "${mins}m"
}

# --- read the payload ------------------------------------------------------

if ([Console]::IsInputRedirected) {
    $rawInput = [Console]::In.ReadToEnd()
} else {
    $rawInput = ''
}

if ([string]::IsNullOrWhiteSpace($rawInput)) {
    [Console]::Out.Write('')
    return
}

$payload = $rawInput | ConvertFrom-Json

$cwd      = if ($payload.cwd) { $payload.cwd }
            elseif ($payload.workspace.current_dir) { $payload.workspace.current_dir }
            else { '.' }
$ctxPct   = $payload.context.percentage
$ctxUsed  = $payload.context.adjusted_tokens
$ctxTotal = $payload.context.adjusted_limit

$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

$segments = [System.Collections.Generic.List[string]]::new()

# --- context window --------------------------------------------------------
if ($null -ne $ctxPct) {
    $ctxLabel = Format-Percent ([double]$ctxPct)
    $bar = Render-Bar ([double]$ctxPct)
    if ($null -ne $ctxUsed -and $null -ne $ctxTotal) {
        $segments.Add("📊 Context: $bar $ctxLabel% ($(Format-K ([double]$ctxUsed))/$(Format-K ([double]$ctxTotal)))")
    } else {
        $segments.Add("📊 Context: $bar $ctxLabel%")
    }
}

# --- Factory plan usage (from the cache) -----------------------------------

$cacheAge = -1
if (Test-Path -LiteralPath $CachePath) {
    try {
        $cache = Get-Content -LiteralPath $CachePath -Raw | ConvertFrom-Json
        if ($cache.fetched_at) { $cacheAge = $now - [int64]$cache.fetched_at }
    } catch {
        $cacheAge = -1
    }
}

if ($cacheAge -ge 0 -and $cacheAge -lt $UsableSeconds) {
    # Older than FreshSeconds but still usable: mark the number so stale data is obvious.
    $suffix = ''
    if ($cacheAge -ge $FreshSeconds) { $suffix = '~' }

    foreach ($w in @(
        @{ key = 'fiveHour'; label = '5h' },
        @{ key = 'weekly';   label = '7d' },
        @{ key = 'monthly';  label = 'Month' }
    )) {
        $entry = $cache.($w.key)
        if ($null -eq $entry -or $null -eq $entry.usedPercent) { continue }

        $pct      = [double]$entry.usedPercent
        $pctLabel = Format-Percent $pct
        $bar      = Render-Bar $pct

        if ($entry.windowEnd) {
            $remaining = Format-Countdown ([int64]$entry.windowEnd - $now)
            $segments.Add("$($w.label): $bar $pctLabel%$suffix ($remaining)")
        } else {
            $segments.Add("$($w.label): $bar $pctLabel%$suffix")
        }
    }
}

# --- working directory -----------------------------------------------------
$dirName = Split-Path -Path $cwd -Leaf
if ([string]::IsNullOrWhiteSpace($dirName)) { $dirName = $cwd }
$segments.Add("📁 $dirName")

[Console]::Out.Write(($segments -join ' │ '))

# --- refresh the cache in the background when it goes stale -----------------

if (($cacheAge -lt 0 -or $cacheAge -ge $FreshSeconds)) {
    $lockAge = 9999
    if (Test-Path -LiteralPath $LockPath) {
        try {
            $lockAge = $now - [DateTimeOffset]::new(
                (Get-Item -LiteralPath $LockPath).LastWriteTimeUtc).ToUnixTimeSeconds()
        } catch {
            $lockAge = 9999
        }
    }

    if ($lockAge -ge $LockMaxAge) {
        try {
            Set-Content -LiteralPath $LockPath -Value $PID -ErrorAction SilentlyContinue
            Start-UsageRefresh
        } catch {
            Write-Log "background refresh spawn failed ($($_.Exception.Message))"
        }
    }
}
