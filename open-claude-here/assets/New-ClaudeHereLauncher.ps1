<#
Generates a "<Backend>-Claude-Here.bat" launcher plus matching Explorer
right-click context-menu (.reg) entries for opening Claude Code, in a
chosen folder, against a given Anthropic-API-compatible backend.

Called by Claude Code (agent-driven) or run directly by a human.

IMPORTANT for agent-driven calls: always pass -AuthToken explicitly.
Claude Code's shell tools run non-interactively (stdin is the null
device), so the Read-Host fallback below will hang if AuthToken is
omitted from an agent-issued call. The fallback exists only for a human
running this script by hand from a real console.
#>
param(
    [Parameter(Mandatory)] [string]$BackendName,
    [Parameter(Mandatory)] [string]$BaseUrl,
    [Parameter(Mandatory)] [string]$Model,
    [string]$SmallFastModel = $Model,
    [string]$AuthToken,
    [string]$TargetDir = (Get-Location).Path,
    [string]$ClaudeFlags = "--dangerously-skip-permissions",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not $AuthToken) {
    $secure = Read-Host -Prompt "Paste the $BackendName API token" -AsSecureString
    $AuthToken = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure))
}

if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
}
$TargetDir = (Resolve-Path $TargetDir).Path

$slug = ($BackendName -replace '[^A-Za-z0-9]', '')
if (-not $slug) { throw "BackendName must contain at least one letter or digit." }

$batName = "$BackendName-Claude-Here.bat"
$batPath = Join-Path $TargetDir $batName
$verbKey = "${slug}ClaudeHere"
$menuLabel = "Open $BackendName Claude Here"

if ((Test-Path $batPath) -and -not $Force) {
    $resp = Read-Host "$batName already exists in $TargetDir. Overwrite? (y/N)"
    if ($resp -notmatch '^[Yy]') {
        Write-Host "Skipped writing $batName."
        return
    }
}

$batContent = @"
@echo off
cd /d "%~1"
set ANTHROPIC_BASE_URL=$BaseUrl
set ANTHROPIC_AUTH_TOKEN=$AuthToken
set ANTHROPIC_MODEL=$Model
set ANTHROPIC_SMALL_FAST_MODEL=$SmallFastModel
set ANTHROPIC_DEFAULT_SONNET_MODEL=$Model
set ANTHROPIC_DEFAULT_OPUS_MODEL=$Model
set ANTHROPIC_DEFAULT_HAIKU_MODEL=$SmallFastModel
set API_TIMEOUT_MS=3000000
set CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
set ALWAYS_THINKING_ENABLED=true
claude $ClaudeFlags
"@

Set-Content -Path $batPath -Value $batContent -Encoding ascii
Write-Host "Wrote $batPath"
Write-Host "NOTE: this file contains your API token in plaintext. Keep it local -- never commit it to a shared or public repo."

$escapedBatPath = $batPath -replace '\\', '\\\\'

$addRegPath = Join-Path $TargetDir "Add-Claude-Context-Menu.reg"
$uninstallRegPath = Join-Path $TargetDir "Uninstall-Claude-Context-Menu.reg"

if (-not (Test-Path $addRegPath)) {
    Set-Content -Path $addRegPath -Value "Windows Registry Editor Version 5.00`r`n" -Encoding ascii
}
if (-not (Test-Path $uninstallRegPath)) {
    Set-Content -Path $uninstallRegPath -Value "Windows Registry Editor Version 5.00`r`n" -Encoding ascii
}

$addContent = Get-Content $addRegPath -Raw
if ($addContent -match [regex]::Escape("\shell\$verbKey]")) {
    Write-Host "'$menuLabel' context-menu entries are already registered in $addRegPath -- leaving them as-is."
} else {
    $addBlock = @"

[HKEY_CURRENT_USER\Software\Classes\Directory\shell\$verbKey]
"MUIVerb"="$menuLabel"

[HKEY_CURRENT_USER\Software\Classes\Directory\shell\$verbKey\command]
@="\"$escapedBatPath\" \"%1\""

[HKEY_CURRENT_USER\Software\Classes\Directory\Background\shell\$verbKey]
"MUIVerb"="$menuLabel"

[HKEY_CURRENT_USER\Software\Classes\Directory\Background\shell\$verbKey\command]
@="\"$escapedBatPath\" \"%V\""
"@
    Add-Content -Path $addRegPath -Value $addBlock -Encoding ascii

    $uninstallBlock = @"

[-HKEY_CURRENT_USER\Software\Classes\Directory\shell\$verbKey]

[-HKEY_CURRENT_USER\Software\Classes\Directory\Background\shell\$verbKey]
"@
    Add-Content -Path $uninstallRegPath -Value $uninstallBlock -Encoding ascii
    Write-Host "Added '$menuLabel' entries to $addRegPath and $uninstallRegPath"
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Double-click $addRegPath to install the context menu (HKCU scope, no admin needed)."
Write-Host "  2. Right-click any folder, or empty space inside one, and choose '$menuLabel'."
Write-Host "  To remove later: double-click $uninstallRegPath."
