# Claude Code statusline — PowerShell / Windows.
# Reads JSON from stdin, prints one colored line:
#   📊 █▌░░░ 35% (350k/1000k) │ 5h: █░░░░ 28% (2h32m) │ 7d: ███░░ 66% (2d10h) │ Opus 4.7 (high) │ ~\Developer\my-project │ Branch: main │ 116.1 tok/s
# Bar color is a smooth truecolor gradient: green (0%) → yellow (50%) → red (100%).
# Requires Windows Terminal (or any host with VT / 24-bit color enabled).
# Compatible with Windows PowerShell 5.1+ and PowerShell 7+. No external deps —
# uses built-in ConvertFrom-Json (no jq needed).
#
# One small piece of state: the generation-speed segment (tok/s, last segment
# of the line) keeps a tiny per-session file in ~\.claude\statusline-speed\ so
# it can diff cost.total_api_duration_ms between ticks. It is idempotent —
# re-rendering the same snapshot never changes the number.

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
$effort     = [string](Get-Path $j @('effort','level') '')
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
    $cells = 5
    $full  = [int][math]::Floor($p / 20)
    $rem   = $p - $full * 20
    $half  = ($rem -ge 10) -and ($full -lt $cells)

    if ($p -le 50) { $r = [int][math]::Round($p / 50.0 * 255); $g = 255 }
    else           { $r = 255; $g = [int][math]::Round((100 - $p) / 50.0 * 255) }
    $b = 0

    $esc = [char]27
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append("$esc[38;2;$r;$g;${b}m")
    for ($i = 0; $i -lt $full; $i++) { [void]$sb.Append([char]0x2588) }   # █
    if ($half) { [void]$sb.Append("$esc[48;2;62;62;62m").Append([char]0x258C).Append("$esc[49m"); $full++ } # ▌ on track
    [void]$sb.Append("$esc[38;2;62;62;62m")
    for ($i = $full; $i -lt $cells; $i++) { [void]$sb.Append([char]0x2588) } # empty track
    return "$($sb.ToString())$esc[0m"
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

# --- Current directory, with $HOME shown as ~ --------------------------------

$dir = $cwd
$homeDir = $HOME.TrimEnd('\', '/')
if ($cwd.Length -ge $homeDir.Length -and $cwd.Substring(0, $homeDir.Length) -ieq $homeDir) {
    $rest = $cwd.Substring($homeDir.Length)
    if ($rest -eq '' -or $rest[0] -eq '\' -or $rest[0] -eq '/') { $dir = "~$rest" }
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

# --- Generation speed of the last response (tok/s) ---------------------------
#
#   tok/s = output_tokens of the last response
#           / (growth in cost.total_api_duration_ms since the previous tick)
#
# The status line re-runs after each response, so the growth in
# total_api_duration_ms since the previous tick is the API time of that
# response (timer ticks in between see no growth and change nothing). It is an
# end-to-end figure (includes time-to-first-token and network), so it reads
# lower than raw decode speed, most visibly on short replies. Responses under
# 30 output tokens or 0.5 s are ignored as too noisy; the previous figure stays.
# Nothing is shown until one full response has been measured in the session.

$speed = ''
try {
    $sid    = [string](Get-Path $j @('session_id') '')
    $apiMs  = Get-Path $j @('cost','total_api_duration_ms')
    $outTok = Get-Path $j @('context_window','current_usage','output_tokens')
    if ($null -eq $outTok) { $outTok = Get-Path $j @('context_window','total_output_tokens') }

    if ($sid -match '^[A-Za-z0-9_-]+$' -and $null -ne $apiMs -and $null -ne $outTok) {
        $apiMs     = [long][math]::Floor([double]$apiMs)
        $outTok    = [long][math]::Floor([double]$outTok)
        $speedDir  = Join-Path (Join-Path $HOME '.claude') 'statusline-speed'
        $stateFile = Join-Path $speedDir $sid

        $prevMs   = $null
        $lastRate = ''
        if (Test-Path -LiteralPath $stateFile) {
            $parts = (Get-Content -LiteralPath $stateFile -Raw).Trim() -split '\s+'
            if ($parts.Count -ge 1 -and $parts[0] -match '^\d+$') { $prevMs = [long]$parts[0] }
            if ($parts.Count -ge 2) { $lastRate = $parts[1] }
        } else {
            New-Item -ItemType Directory -Force -Path $speedDir | Out-Null
            Get-ChildItem -LiteralPath $speedDir -File |
                Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }

        $newRate = $lastRate
        # No baseline yet: record one below, show nothing.
        if ($null -ne $prevMs -and $apiMs -gt $prevMs) {
            $dMs = $apiMs - $prevMs
            if ($outTok -ge 30 -and $dMs -ge 500) {
                $rate = $outTok / ($dMs / 1000.0)
                if ($rate -le 2000) {
                    $newRate = $rate.ToString('0.0', [System.Globalization.CultureInfo]::InvariantCulture)
                }
            }
        }

        if ($apiMs -ne $prevMs) {
            Set-Content -LiteralPath $stateFile -Value "$apiMs $newRate" -Encoding ASCII
        }
        $speed = $newRate
    }
} catch { }

# --- Compose the line --------------------------------------------------------

$usedK  = Format-K $tokensUsed
$totalK = Format-K $ctxSize

$ctxBar = Render-Bar $pctInt
$line   = "📊 $ctxBar $pctInt% ($usedK/$totalK)"

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

# Reasoning effort is absent for models that don't support it.
if ($effort) { $model = "$model ($effort)" }

$line = "$line │ $model │ $dir"
if ($branch) { $line = "$line │ Branch: $branch" }
if ($speed) { $line = "$line │ $speed tok/s" }

[Console]::Out.Write($line)
