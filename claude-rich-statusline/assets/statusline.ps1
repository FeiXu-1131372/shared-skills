# Claude Code statusline — PowerShell / Windows.
# Reads JSON from stdin, prints one colored line:
#   📊 Context: ▓░░░░░░░░░ 9% (90k/1000k) │ 5h: ██▓░░░░░░░ 28% (2h32m) │ 7d: ▓░░░░░░░░░ 6% (2d10h) │ Session: 6m │ Model: Opus 4.7 │ Branch: main
# Bar color is a smooth truecolor gradient: green (0%) → yellow (50%) → red (100%).
# Requires Windows Terminal (or any host with VT / 24-bit color enabled).
# Compatible with Windows PowerShell 5.1+ and PowerShell 7+. No external deps —
# uses built-in ConvertFrom-Json (no jq needed).

$ErrorActionPreference = 'Stop'

# Make sure we emit UTF-8 so the block characters and emoji render correctly.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

# Read JSON from stdin. Claude Code always pipes stdin in, so this is safe.
if ([Console]::IsInputRedirected) {
    $inputJson = [Console]::In.ReadToEnd()
} else {
    $inputJson = ''
}

if ([string]::IsNullOrWhiteSpace($inputJson)) {
    [Console]::Out.Write('')
    return
}

$j = $inputJson | ConvertFrom-Json

# --- Pull fields with the same fallbacks as the bash version -----------------

function Get-Path($obj, [string[]]$path, $default = $null) {
    $cur = $obj
    foreach ($p in $path) {
        if ($null -eq $cur) { return $default }
        $prop = $cur.PSObject.Properties[$p]
        if ($null -eq $prop) { return $default }
        $cur = $prop.Value
    }
    if ($null -eq $cur) { return $default }
    return $cur
}

$model      = Get-Path $j @('model','display_name')
if (-not $model) { $model = Get-Path $j @('model','id') }
if (-not $model) { $model = '?' }

$pct        = [double](Get-Path $j @('context_window','used_percentage') 0)
$ctxSize    = [int]   (Get-Path $j @('context_window','context_window_size') 200000)
$durationMs = [int64] (Get-Path $j @('cost','total_duration_ms') 0)
$cwd        = [string](Get-Path $j @('workspace','current_dir') '.')

$fivePct    = Get-Path $j @('rate_limits','five_hour','used_percentage')
$fiveReset  = Get-Path $j @('rate_limits','five_hour','resets_at')
$sevenPct   = Get-Path $j @('rate_limits','seven_day','used_percentage')
$sevenReset = Get-Path $j @('rate_limits','seven_day','resets_at')

$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

$pctInt     = [int][math]::Round($pct)
$tokensUsed = [int]($pct * $ctxSize / 100)

# --- Helpers -----------------------------------------------------------------

function Format-K([int]$n) {
    if ($n -ge 1000) { return ('{0:N0}k' -f [math]::Round($n / 1000)) }
    return "$n"
}

function Render-Bar([int]$p) {
    if ($p -lt 0)   { $p = 0 }
    if ($p -gt 100) { $p = 100 }
    $cells = 10
    $full  = [int][math]::Floor($p / 10)
    $rem   = $p - $full * 10
    $half  = ($rem -ge 5) -and ($full -lt $cells)

    if ($p -le 50) { $r = [int][math]::Round($p / 50.0 * 255); $g = 255 }
    else           { $r = 255; $g = [int][math]::Round((100 - $p) / 50.0 * 255) }
    $b = 0

    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $full; $i++) { [void]$sb.Append([char]0x2588) }   # █
    if ($half) { [void]$sb.Append([char]0x2593); $full++ }                # ▓
    for ($i = $full; $i -lt $cells; $i++) { [void]$sb.Append([char]0x2591) } # ░

    $esc = [char]27
    return "$esc[38;2;$r;$g;${b}m$($sb.ToString())$esc[0m"
}

function Format-Countdown([int]$secs) {
    if ($secs -le 0) { return 'now' }
    $days  = [int][math]::Floor($secs / 86400)
    $hours = [int][math]::Floor(($secs % 86400) / 3600)
    $mins  = [int][math]::Floor(($secs % 3600) / 60)
    if ($days -ge 1) {
        if ($hours -gt 0) { return "${days}d${hours}h" } else { return "${days}d" }
    }
    if ($hours -ge 1) {
        if ($mins -gt 0) { return "${hours}h${mins}m" } else { return "${hours}h" }
    }
    return "${mins}m"
}

# --- Session duration (already-elapsed time) ---------------------------------

$totalMins = [int][math]::Floor($durationMs / 60000)
if ($totalMins -lt 60) {
    $session = "${totalMins}m"
} else {
    $h = [int][math]::Floor($totalMins / 60)
    $m = $totalMins % 60
    if ($m -eq 0) { $session = "${h}h" } else { $session = "${h}h${m}m" }
}

# --- Git branch (silent if not a repo or git is missing) ---------------------

$branch = ''
try {
    if (Test-Path $cwd) {
        Push-Location -LiteralPath $cwd -ErrorAction Stop
        try {
            $null = & git rev-parse --git-dir 2>$null
            if ($LASTEXITCODE -eq 0) {
                $b = (& git branch --show-current 2>$null)
                if ($b) { $branch = $b.Trim() }
            }
        } finally {
            Pop-Location
        }
    }
} catch { }

# --- Compose the line --------------------------------------------------------

$usedK  = Format-K $tokensUsed
$totalK = Format-K $ctxSize

$ctxBar = Render-Bar $pctInt
$line   = "📊 Context: $ctxBar $pctInt% ($usedK/$totalK)"

if ($null -ne $fivePct) {
    $fiveInt = [int][math]::Round([double]$fivePct)
    $fiveBar = Render-Bar $fiveInt
    if ($null -ne $fiveReset) {
        $fiveIn = Format-Countdown ([int]$fiveReset - $now)
        $line = "$line │ 5h: $fiveBar $fiveInt% ($fiveIn)"
    } else {
        $line = "$line │ 5h: $fiveBar $fiveInt%"
    }
}

if ($null -ne $sevenPct) {
    $sevenInt = [int][math]::Round([double]$sevenPct)
    $sevenBar = Render-Bar $sevenInt
    if ($null -ne $sevenReset) {
        $sevenIn = Format-Countdown ([int]$sevenReset - $now)
        $line = "$line │ 7d: $sevenBar $sevenInt% ($sevenIn)"
    } else {
        $line = "$line │ 7d: $sevenBar $sevenInt%"
    }
}

$line = "$line │ Session: $session │ Model: $model"
if ($branch) { $line = "$line │ Branch: $branch" }

[Console]::Out.Write($line)
