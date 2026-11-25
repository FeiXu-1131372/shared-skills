# Antigravity CLI (agy) rich statusline - PowerShell / Windows.
# Reads StatusLineData JSON from stdin, prints one colored line with segments:
#   context bar, quota bar(s) + countdowns, model (effort), directory, branch,
#   active subagents (when present), session cost (when > 0), tok/s
# Bar color is a smooth truecolor gradient: green (0%) -> yellow (50%) -> red (100%).
# Requires Windows Terminal (or any host with VT / 24-bit color enabled).
# Compatible with Windows PowerShell 5.1+ and PowerShell 7+ (pwsh). Zero external deps.
#
# Keep this file pure 7-bit ASCII! Windows PowerShell 5.1 reads a .ps1 without a
# UTF-8 BOM in the system legacy code page, turning literal emoji or box-drawing
# bytes into mojibake that can break parsing and blank the status line. Write all
# non-ASCII glyphs as [char] / ConvertFromUtf32 escapes.

$ErrorActionPreference = 'Stop'

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $utf8NoBom } catch { }

function Write-Utf8Stdout([string]$text) {
    if ([string]::IsNullOrEmpty($text)) { return }
    $bytes = $utf8NoBom.GetBytes($text)
    $stdout = [Console]::OpenStandardOutput()
    $stdout.Write($bytes, 0, $bytes.Length)
    $stdout.Flush()
}

try {
    $stdin = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), $utf8NoBom)
    $inputJson = $stdin.ReadToEnd()
} catch {
    $inputJson = ''
}

if ([string]::IsNullOrWhiteSpace($inputJson)) {
    return
}

$j = $inputJson | ConvertFrom-Json
$inv = [System.Globalization.CultureInfo]::InvariantCulture

# --- Helpers -----------------------------------------------------------------

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

function Format-K([long]$n) {
    if ($n -ge 1000) {
        return ([math]::Round($n / 1000.0)).ToString('0', $inv) + 'k'
    }
    return $n.ToString($inv)
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
    for ($i = 0; $i -lt $full; $i++) { [void]$sb.Append([char]0x2588) }   # full block
    if ($half) { [void]$sb.Append("$esc[48;2;62;62;62m").Append([char]0x258C).Append("$esc[49m"); $full++ }
    [void]$sb.Append("$esc[38;2;62;62;62m")
    for ($i = $full; $i -lt $cells; $i++) { [void]$sb.Append([char]0x2588) } # empty track
    return "$($sb.ToString())$esc[0m"
}

function Format-Countdown([long]$secs) {
    if ($secs -le 0) { return 'now' }
    $days  = [long][math]::Floor($secs / 86400.0)
    $hours = [long][math]::Floor(($secs % 86400) / 3600.0)
    $mins  = [long][math]::Floor(($secs % 3600) / 60.0)
    if ($days -ge 1) {
        if ($hours -gt 0) { return "${days}d${hours}h" } else { return "${days}d" }
    }
    if ($hours -ge 1) {
        if ($mins -gt 0) { return "${hours}h${mins}m" } else { return "${hours}h" }
    }
    return "${mins}m"
}

function Get-ShortPrefix([string]$k) {
    if ($k -match '(?i)^gemini')          { return 'Gem' }
    if ($k -match '(?i)^claude')          { return 'Cld' }
    if ($k -match '(?i)^(gpt|openai)')    { return 'GPT' }
    return (($k -split '[-_]')[0])
}

function Parse-IsoEpoch($val) {
    if ($null -eq $val) { return $null }
    try {
        if ($val -is [datetime]) {
            return [long][math]::Floor(([DateTimeOffset]$val.ToUniversalTime()).ToUnixTimeSeconds())
        }
        $s = [string]$val
        if ([string]::IsNullOrWhiteSpace($s)) { return $null }
        $dto = [DateTimeOffset]::Parse($s, $inv, [System.Globalization.DateTimeStyles]::AssumeUniversal)
        return $dto.ToUnixTimeSeconds()
    } catch {
        return $null
    }
}

$nowSec = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$nowMs  = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

# --- Context window ----------------------------------------------------------

$ctxSize = [long](Get-Path $j @('context_window','context_window_size') 1048576)
$usedPctRaw = Get-Path $j @('context_window','used_percentage')
$remPctRaw  = Get-Path $j @('context_window','remaining_percentage')
if ($null -ne $usedPctRaw) {
    $pct = [double]$usedPctRaw
} elseif ($null -ne $remPctRaw) {
    $pct = 100.0 - [double]$remPctRaw
} else {
    $pct = 0.0
}

$pctInt     = [int][math]::Round($pct)
$tokensUsed = [long][math]::Floor($pct * $ctxSize / 100.0)
$usedK      = Format-K $tokensUsed
$totalK     = Format-K $ctxSize

# --- Model & effort (deduplicate if display_name already ends with "(Effort)")

$model = [string](Get-Path $j @('model','display_name') '')
if (-not $model) { $model = [string](Get-Path $j @('model','id') '') }
if (-not $model) { $model = '?' }

$effort = [string](Get-Path $j @('model','effort') '')
if (-not $effort) { $effort = [string](Get-Path $j @('effort','level') '') }
if ($effort) {
    $suffix = "($effort)"
    if (-not $model.EndsWith($suffix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $model = "$model ($effort)"
    }
}

# --- Current directory, with $HOME shown as ~ --------------------------------

$cwd = [string](Get-Path $j @('workspace','current_dir') '')
if (-not $cwd) { $cwd = [string](Get-Path $j @('cwd') '.') }

$dir = $cwd
$homeDir = $HOME.TrimEnd('\', '/')
if ($homeDir -and $cwd.Length -ge $homeDir.Length -and $cwd.Substring(0, $homeDir.Length) -ieq $homeDir) {
    $rest = $cwd.Substring($homeDir.Length)
    if ($rest -eq '' -or $rest[0] -eq '\' -or $rest[0] -eq '/') { $dir = "~$rest" }
}

# --- VCS branch (prefer Antigravity .vcs payload; fallback to git) -----------

$vcsObj = Get-Path $j @('vcs')
$branch = ''
if ($null -ne $vcsObj) {
    $branch = [string](Get-Path $vcsObj @('branch') '')
    if (-not $branch) { $branch = [string](Get-Path $vcsObj @('client') '') }
    if ($branch -and (Get-Path $vcsObj @('dirty') $false) -eq $true) {
        $branch = "${branch}*"
    }
} else {
    try {
        if (Test-Path -LiteralPath $cwd) {
            Push-Location -LiteralPath $cwd -ErrorAction Stop
            try {
                $null = & git --no-optional-locks rev-parse --git-dir 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $b = (& git --no-optional-locks branch --show-current 2>$null)
                    if ($b) { $branch = ([string]$b).Trim() }
                }
            } finally {
                Pop-Location
            }
        }
    } catch { }
}

# --- Quota buckets (Antigravity .quota map, fallback to .rate_limits) --------

$quotaSegs = New-Object System.Collections.Generic.List[string]
$quotaObj  = Get-Path $j @('quota')

if ($null -ne $quotaObj -and @($quotaObj.PSObject.Properties).Count -gt 0) {
    $entries = @($quotaObj.PSObject.Properties | Where-Object {
        $null -ne $_.Value -and (Get-Path $_.Value @('disabled') $false) -ne $true
    } | Sort-Object @{ Expression = {
        $n = [string]$_.Name
        $hasFrac = ($null -ne (Get-Path $_.Value @('remaining_fraction')))
        if (-not $hasFrac) { return 50 }
        if ($n -match '(?i)([-_]5h$|^five_hour$|^5h$)')   { return 10 }
        if ($n -match '(?i)([-_]daily$|^1d$)')            { return 20 }
        if ($n -match '(?i)([-_]weekly$|^seven_day$|^7d$)'){ return 30 }
        return 40
    }}, Name)

    $wkCnt = @($entries | Where-Object { $_.Name -match '(?i)[-_]weekly$' }).Count
    $dyCnt = @($entries | Where-Object { $_.Name -match '(?i)[-_]daily$' }).Count
    $fhCnt = @($entries | Where-Object { $_.Name -match '(?i)([-_]5h$|^five_hour$)' }).Count

    foreach ($e in $entries) {
        $k = [string]$e.Name
        $v = $e.Value

        if ($k -match '(?i)^(five_hour|5h)$')      { $lbl = '5h' }
        elseif ($k -match '(?i)^(seven_day|7d)$')  { $lbl = '7d' }
        elseif ($k -match '(?i)[-_]5h$')           { $lbl = if ($fhCnt -gt 1) { "$(Get-ShortPrefix $k) 5h" } else { '5h' } }
        elseif ($k -match '(?i)[-_]weekly$')       { $lbl = if ($wkCnt -gt 1) { "$(Get-ShortPrefix $k) 7d" } else { '7d' } }
        elseif ($k -match '(?i)[-_]daily$')        { $lbl = if ($dyCnt -gt 1) { "$(Get-ShortPrefix $k) 1d" } else { '1d' } }
        else                                       { $lbl = ($k -replace '(?i)[-_]quota$', '') }

        $remFrac = Get-Path $v @('remaining_fraction')
        $remAmt  = Get-Path $v @('remaining_amount')

        if ($null -ne $remFrac) {
            $usedPct = (1.0 - [double]$remFrac) * 100.0
            if ($usedPct -lt 0)   { $usedPct = 0 }
            if ($usedPct -gt 100) { $usedPct = 100 }
            $uInt = [int][math]::Round($usedPct)
            $qBar = Render-Bar $uInt

            $rtEpoch = Parse-IsoEpoch (Get-Path $v @('reset_time'))
            $remSecs = Get-Path $v @('reset_in_seconds')
            if ($null -ne $rtEpoch) {
                $cd = Format-Countdown ($rtEpoch - $nowSec)
                $quotaSegs.Add("${lbl}: $qBar ${uInt}% ($cd)")
            } elseif ($null -ne $remSecs) {
                $cd = Format-Countdown ([long][math]::Floor([double]$remSecs))
                $quotaSegs.Add("${lbl}: $qBar ${uInt}% ($cd)")
            } else {
                $quotaSegs.Add("${lbl}: $qBar ${uInt}%")
            }
        } elseif ($null -ne $remAmt -and [long]$remAmt -gt 0) {
            $quotaSegs.Add("Credits: $(Format-K ([long]$remAmt))")
        }
    }
} else {
    $fivePct    = Get-Path $j @('rate_limits','five_hour','used_percentage')
    $fiveReset  = Get-Path $j @('rate_limits','five_hour','resets_at')
    $sevenPct   = Get-Path $j @('rate_limits','seven_day','used_percentage')
    $sevenReset = Get-Path $j @('rate_limits','seven_day','resets_at')

    if ($null -ne $fivePct) {
        $fInt = [int][math]::Round([double]$fivePct)
        $fBar = Render-Bar $fInt
        if ($null -ne $fiveReset) {
            $fIn = Format-Countdown ([long]$fiveReset - $nowSec)
            $quotaSegs.Add("5h: $fBar ${fInt}% ($fIn)")
        } else {
            $quotaSegs.Add("5h: $fBar ${fInt}%")
        }
    }
    if ($null -ne $sevenPct) {
        $sInt = [int][math]::Round([double]$sevenPct)
        $sBar = Render-Bar $sInt
        if ($null -ne $sevenReset) {
            $sIn = Format-Countdown ([long]$sevenReset - $nowSec)
            $quotaSegs.Add("7d: $sBar ${sInt}% ($sIn)")
        } else {
            $quotaSegs.Add("7d: $sBar ${sInt}%")
        }
    }
}

# --- Active subagents (optional inline summary) ------------------------------

$subSummary = ''
$robot = [char]::ConvertFromUtf32(0x1F916)   # robot emoji
$subs = @(Get-Path $j @('subagents') @())
if ($subs.Count -gt 0) {
    $activeSubs = @($subs | Where-Object {
        if ($null -eq $_) { return $false }
        $st = ([string](Get-Path $_ @('status') '')).ToLowerInvariant()
        return ($st -ne '' -and $st -notmatch '^(completed|done|failed|killed|stopped|cancelled|canceled|idle|subagent_state_killed)$')
    })
    if ($activeSubs.Count -eq 1) {
        $s0 = $activeSubs[0]
        $role = [string](Get-Path $s0 @('role') '')
        if (-not $role) { $role = [string](Get-Path $s0 @('name') 'subagent') }
        $sModel = [string](Get-Path $s0 @('model') '')
        if ($sModel) { $subSummary = "$robot $role ($sModel)" }
        else         { $subSummary = "$robot $role" }
    } elseif ($activeSubs.Count -gt 1) {
        $subSummary = "$robot $($activeSubs.Count) subagents"
    }
}

# --- Session cost (optional inline when > 0) ---------------------------------

$costSummary = ''
$costRaw = Get-Path $j @('cost','total_usd')
if ($null -eq $costRaw) { $costRaw = Get-Path $j @('cost','total_cost_usd') }
if ($null -ne $costRaw) {
    $costVal = [double]$costRaw
    if ($costVal -ge 0.01) {
        $costSummary = '$' + $costVal.ToString('0.00', $inv)
    } elseif ($costVal -ge 0.001) {
        $costSummary = '$' + $costVal.ToString('0.000', $inv)
    }
}

# --- Generation speed of the latest completed response (tok/s) ---------------

$speed = ''
try {
    $sid = [string](Get-Path $j @('conversation_id') '')
    if (-not $sid) { $sid = [string](Get-Path $j @('session_id') '') }

    if ($sid -match '^[A-Za-z0-9_-]+$') {
        $totOut = [long][math]::Floor([double](Get-Path $j @('context_window','total_output_tokens') 0))
        $curOut = [long][math]::Floor([double](Get-Path $j @('context_window','current_usage','output_tokens') 0))
        $apiRaw = Get-Path $j @('cost','total_api_duration_ms')
        $astate = ([string](Get-Path $j @('agent_state') 'idle')).ToLowerInvariant()
        $paused = ((Get-Path $j @('tool_confirmation_pending') $false) -eq $true) -or ([int](Get-Path $j @('pending_input_count') 0) -gt 0)

        $speedDir = $env:AGY_STATUSLINE_SPEED_DIR
        if (-not $speedDir) {
            $speedDir = Join-Path (Join-Path (Join-Path $HOME '.gemini') 'antigravity-cli') 'statusline-speed'
        }
        $stateFile = Join-Path $speedDir $sid

        $prevOut  = $null
        $phaseMs  = 0L
        $prevApi  = $null
        $lastRate = ''

        if (Test-Path -LiteralPath $stateFile) {
            $parts = @((Get-Content -LiteralPath $stateFile -Raw).Trim() -split '\s+')
            if ($parts.Count -ge 1 -and $parts[0] -match '^\d+$') { $prevOut = [long]$parts[0] }
            if ($parts.Count -ge 2 -and $parts[1] -match '^\d+$') { $phaseMs = [long]$parts[1] }
            if ($parts.Count -ge 3 -and $parts[2] -match '^\d+$') { $prevApi = [long]$parts[2] }
            if ($parts.Count -ge 4) { $lastRate = $parts[3] }
        } else {
            New-Item -ItemType Directory -Force -Path $speedDir | Out-Null
            Get-ChildItem -LiteralPath $speedDir -File -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }

        $newRate  = $lastRate
        $newPhase = $phaseMs
        $apiMsVal = 0L

        if ($null -ne $apiRaw) {
            $apiMsVal = [long][math]::Floor([double]$apiRaw)
            if ($null -ne $prevApi -and $prevApi -gt 0 -and $apiMsVal -gt $prevApi) {
                $dMs = $apiMsVal - $prevApi
                $tokSample = if ($curOut -gt 0) { $curOut } elseif ($null -ne $prevOut -and $totOut -gt $prevOut) { $totOut - $prevOut } else { 0L }
                if ($tokSample -ge 30 -and $dMs -ge 500) {
                    $rate = $tokSample / ($dMs / 1000.0)
                    if ($rate -le 2000) { $newRate = $rate.ToString('0.0', $inv) }
                }
            }
        } else {
            if ($paused) {
                $newPhase = 0L
            } elseif ($null -eq $prevOut) {
                $newPhase = if ($astate -ne 'idle') { $nowMs } else { 0L }
            } elseif ($totOut -gt $prevOut) {
                $deltaTok = $totOut - $prevOut
                if ($curOut -gt 0 -and $curOut -lt $deltaTok) { $deltaTok = $curOut }
                if ($phaseMs -gt 0 -and $nowMs -gt $phaseMs) {
                    $dMs = $nowMs - $phaseMs
                    if ($deltaTok -ge 30 -and $dMs -ge 500) {
                        $rate = $deltaTok / ($dMs / 1000.0)
                        if ($rate -le 2000) { $newRate = $rate.ToString('0.0', $inv) }
                    }
                }
                $newPhase = if ($astate -eq 'idle') { 0L } else { $nowMs }
            } else {
                if ($astate -eq 'idle') { $newPhase = 0L }
                elseif ($phaseMs -eq 0) { $newPhase = $nowMs }
            }
        }

        $prevApiNorm = if ($null -ne $prevApi) { $prevApi } else { 0L }
        if ($prevOut -ne $totOut -or $newPhase -ne $phaseMs -or $apiMsVal -ne $prevApiNorm -or $newRate -ne $lastRate) {
            Set-Content -LiteralPath $stateFile -Value "$totOut $newPhase $apiMsVal $newRate" -Encoding ASCII
        }
        $speed = $newRate
    }
} catch { }

# --- Compose the line --------------------------------------------------------

$chart = [char]::ConvertFromUtf32(0x1F4CA)   # bar chart emoji
$sep   = [char]0x2502                        # box-drawing vertical bar

$ctxBar = Render-Bar $pctInt
$line   = "$chart $ctxBar $pctInt% ($usedK/$totalK)"

foreach ($qs in $quotaSegs) {
    $line = "$line $sep $qs"
}

$line = "$line $sep $model $sep $dir"
if ($branch)      { $line = "$line $sep Branch: $branch" }
if ($subSummary)  { $line = "$line $sep $subSummary" }
if ($costSummary) { $line = "$line $sep $costSummary" }
if ($speed)       { $line = "$line $sep $speed tok/s" }

Write-Utf8Stdout $line
