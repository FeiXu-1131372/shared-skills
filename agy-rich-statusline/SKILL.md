---
name: agy-rich-statusline
description: Install or configure a feature-rich Google Antigravity CLI (agy) statusline that displays real-time context window usage with a truecolor progress bar (e.g. "📊 █▌░░░ 35% (367k/1049k)"), model quota consumption with live reset countdowns (e.g. "7d: ███░░ 66% (2d10h)"), active model with deduplicated reasoning effort, working directory, VCS branch + dirty marker, active subagents summary, estimated session spend, and latest response generation speed ("116.1 tok/s"). Bars use a smooth green→yellow→red 24-bit gradient so hue encodes severity at a glance. Works on macOS, Linux, and Windows (Windows Terminal + PowerShell). Use this skill whenever the user asks to set up an Antigravity or agy status line, configure statusLine or /statusline, see context window usage in their terminal, monitor Gemini/model quota or reset timers, track active subagents/cost/token consumption, or get real-time session visibility in agy.
---

# Rich Antigravity CLI (`agy`) Statusline

The Antigravity CLI (`agy`) can run a custom shell command on every agent/UI state change and render its stdout as the TUI status bar (either replacing or stacking beneath the built-in bar). This skill installs a rich, glanceable status line modeled on `claude-rich-statusline` and tailored to Antigravity's native `StatusLineData` payload.

Sample output (24-bit color in the bars themselves, gradient green→yellow→red):

```text
📊 █▌░░░ 35% (367k/1049k) │ 7d: ███░░ 66% (2d10h) │ Gemini 4 Carbon (Medium) │ ~/develop │ Branch: main* │ 🤖 2 subagents │ $0.14 │ 116.1 tok/s
```

Each segment is independent and silently omitted when empty or unavailable:

- **Context bar (`📊 █▌░░░ 35% (367k/1049k)`)** — Current context occupancy from `context_window.used_percentage` and `context_window.context_window_size` (auto-adapts to 1M `1049k`, `200k`, etc.).
- **Quota bars (`7d: ███░░ 66% (2d10h)`, `5h: …`, `Credits: …`)** — Converts Antigravity's `quota.<bucket>.remaining_fraction` (`0..1` remaining) into **percentage consumed** (`(1 - remaining_fraction) × 100`) so green means plenty of quota left and red means nearly exhausted, paired with a coarse reset countdown computed from `reset_time` (falling back to `reset_in_seconds`). Disabled buckets and zero credit balances are hidden automatically. If multiple weekly/daily buckets exist (e.g. `gemini-weekly` + `claude-weekly`), labels auto-disambiguate (`Gem 7d`, `Cld 7d`).
- **Model & effort (`Gemini 4 Carbon (Medium)`)** — Reads `model.display_name` (else `model.id`) and `model.effort`. Because Antigravity's `display_name` often already includes `(Medium)` or `(High)`, the script deduplicates case-insensitively so it never prints `(Medium) (medium)`.
- **Directory (`~/develop`)** — Reads `workspace.current_dir` (else `cwd`) with `$HOME` abbreviated to `~`.
- **VCS branch (`Branch: main*`)** — Reads `vcs.branch` (or `vcs.client` for CitC/Mercurial) directly from `agy`'s payload with **zero `git` subprocess spawns** during live sessions, appending `*` when `vcs.dirty` is `true` (and falling back to `git branch --show-current` only if `.vcs` is omitted, such as in manual smoke tests).
- **Active subagents (`🤖 Codebase Researcher (flash)` or `🤖 2 subagents`)** — Shown only while one or more entries in `.subagents` are actively running; disappears once all subagents finish.
- **Session spend (`$0.14`)** — Shown only when `cost.total_usd > 0`; omitted on `$0` or flat-rate tiers without cost reporting.
- **Generation speed (`116.1 tok/s`)** — Speed of the *latest completed model response* (see "Generation speed" below).

**Visual encoding.** Bars are 5 cells wide (20% per cell) with a `▌` half block for the 10% step in between, rounded down (`30%` renders as `█▌░░░`). Empty cells use a flat dark-gray track (`RGB(62,62,62)`), and half cells draw the bar color over the track background. Color is a smooth 24-bit linear gradient: pure green `RGB(0,255,0)` at 0%, pure yellow `RGB(255,255,0)` at 50%, pure red `RGB(255,0,0)` at 100%.

## When to use this skill

Trigger on any of:

- "set up [a/the] statusline [in Antigravity / agy]"
- "configure `statusLine` or `/statusline`"
- "show context window usage in `agy` / terminal"
- "monitor my Gemini / Antigravity quota or reset timer"
- "track token consumption / generation speed / cost while coding in `agy`"
- "port `claude-rich-statusline` to Antigravity"

Don't trigger for:

- Interactive shell prompt tools (`starship`, `oh-my-posh`, `p10k`) unrelated to `agy`'s TUI status bar.
- Repairing a custom statusline script unrelated to this one without asking first.

---

## Install

Installation has four steps: verify dependencies, write the script into `~/.gemini/antigravity-cli/`, smoke-test it with synthetic Antigravity payloads, and register it via `/statusline` (or `settings.json`).

> [!IMPORTANT]
> Antigravity enforces a system protection boundary around `~/.gemini/antigravity-cli/settings.json` for agent file-read/edit tools. Do **not** attempt to read or edit `settings.json` directly from agent tools if blocked — instead, install and smoke-test the script first, then give the user the exact `/statusline <command>` slash command (which updates `settings.json` atomically and activates **live without restarting `agy`**) alongside the optional `settings.json` snippet.

### macOS / Linux (`bash`)

#### Step 1 — Verify `jq`

`statusline.sh` parses the full payload in a single `jq` invocation (~4 ms, portable across macOS BSD and Linux GNU without `date` flag differences). Verify `jq` is installed:

```bash
which jq && jq --version
```

If missing, ask the user to install it first (`brew install jq`, `sudo apt install jq`, or `sudo dnf install jq`).

#### Step 2 — Write `~/.gemini/antigravity-cli/statusline.sh`

If `~/.gemini/antigravity-cli/statusline.sh` already exists, **stop and ask the user** before overwriting so custom edits aren't lost. Otherwise copy `assets/statusline.sh` from this skill directory and mark it executable:

```bash
mkdir -p ~/.gemini/antigravity-cli
cp "<skill-path>/assets/statusline.sh" ~/.gemini/antigravity-cli/statusline.sh
chmod +x ~/.gemini/antigravity-cli/statusline.sh
```

#### Step 3 — Smoke test

Run a synthetic `StatusLineData` payload through the script to verify colors, quota countdowns, effort deduplication, subagents, cost, and 2-tick `tok/s`:

```bash
SMOKE_SPEED=$(mktemp -d)
RESET_ISO=$(jq -nr '(now + 219600) | todateiso8601')

# Tick 1: agent starts running (records generation baseline)
AGY_STATUSLINE_SPEED_DIR="$SMOKE_SPEED" bash ~/.gemini/antigravity-cli/statusline.sh <<EOF && echo
{
  "conversation_id": "smoke-conv",
  "agent_state": "running",
  "model": {"id": "Gemini 4 Carbon (Medium)", "display_name": "Gemini 4 Carbon (Medium)", "effort": "medium"},
  "workspace": {"current_dir": "$PWD"},
  "vcs": {"type": "git", "branch": "main", "dirty": true},
  "context_window": {"used_percentage": 35.0, "context_window_size": 1048576, "total_output_tokens": 1200, "current_usage": {"output_tokens": 0}},
  "quota": {"gemini-weekly": {"remaining_fraction": 0.34, "reset_time": "$RESET_ISO", "reset_in_seconds": 219600}},
  "subagents": [{"name": "research-1", "role": "Codebase Researcher", "model": "flash", "status": "running"}],
  "cost": {"total_usd": 0.14, "subagent_usd": 0.02, "estimated": true}
}
EOF

sleep 1

# Tick 2: response completes (+120 output tokens -> ~120 tok/s)
AGY_STATUSLINE_SPEED_DIR="$SMOKE_SPEED" bash ~/.gemini/antigravity-cli/statusline.sh <<EOF && echo
{
  "conversation_id": "smoke-conv",
  "agent_state": "idle",
  "model": {"id": "Gemini 4 Carbon (Medium)", "display_name": "Gemini 4 Carbon (Medium)", "effort": "medium"},
  "workspace": {"current_dir": "$PWD"},
  "vcs": {"type": "git", "branch": "main", "dirty": true},
  "context_window": {"used_percentage": 35.2, "context_window_size": 1048576, "total_output_tokens": 1320, "current_usage": {"output_tokens": 120}},
  "quota": {"gemini-weekly": {"remaining_fraction": 0.34, "reset_time": "$RESET_ISO", "reset_in_seconds": 219600}},
  "subagents": [],
  "cost": {"total_usd": 0.15, "subagent_usd": 0.02, "estimated": true}
}
EOF
rm -rf "$SMOKE_SPEED"
```

#### Step 4 — Activate in `agy`

Give the user the live slash command to run inside `agy` (takes effect immediately, no restart needed):

```text
/statusline bash ~/.gemini/antigravity-cli/statusline.sh
```

Or in `~/.gemini/antigravity-cli/settings.json`:

```json
"statusLine": {
  "type": "command",
  "command": "bash ~/.gemini/antigravity-cli/statusline.sh",
  "enabled": true,
  "padding": 0,
  "stack_with_default": false
}
```

---

### Windows (Windows Terminal + PowerShell)

`statusline.ps1` has **zero external dependencies** (uses native PowerShell JSON & `DateTimeOffset` parsing) and is strictly **pure 7-bit ASCII** so both Windows PowerShell 5.1 and PowerShell 7 (`pwsh`) parse it cleanly regardless of system code page.

**Requirements:**
- **Windows Terminal** (recommended for 24-bit truecolor and Unicode block glyphs; legacy `conhost.exe` prints raw ANSI escapes).
- **PowerShell 7 (`pwsh`)** preferred (~3× faster cold start than `powershell.exe` 5.1, though both work).

#### Step 1 — Locate or copy `statusline.ps1`

Note that `~/.gemini/antigravity-cli/` is behind Antigravity's agent protection boundary, so keep `statusline.ps1` inside `~/.gemini/config/` (either directly in the installed skill folder `~/.gemini/config/skills/agy-rich-statusline/assets/statusline.ps1`, or copied to `~/.gemini/config/statusline.ps1`):

```powershell
$cfgDir = Join-Path (Join-Path $HOME '.gemini') 'config'
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
Copy-Item -LiteralPath '<skill-path>\assets\statusline.ps1' -Destination (Join-Path $cfgDir 'statusline.ps1') -Force
```

If the destination `statusline.ps1` already exists, **stop and ask** before overwriting.

#### Step 2 — Build the command string (NO double quotes!)

Resolve the script path with **forward slashes** and wrap it in **single quotes** with `-Command . '<path>'`:

```powershell
$scriptPath = ((Join-Path $HOME '.gemini\config\skills\agy-rich-statusline\assets\statusline.ps1') -replace '\\', '/')
$psExe = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' }
"$psExe -NoProfile -ExecutionPolicy Bypass -Command . '$scriptPath'"
```

Critical notes on Windows shell execution in `agy`:
- **NEVER use double quotes (`"..."`) inside `statusLine.command` on Windows!** Unlike Claude Code (which runs via Git Bash), `agy` is a Go binary that invokes `exec.Command("cmd", "/c", command)`. Go's `syscall.EscapeArg` escapes any inner `"` to `\"`, which `cmd.exe` passes literally to PowerShell — causing `-File` to fail with `exit status 0xfffd0000 (Illegal characters in path)`.
- Using `-Command . 'C:/Users/<name>/.../statusline.ps1'` (with **single quotes** and forward slashes) contains zero `"` characters, survives Go's `cmd /c` escaping intact, and handles spaces in Windows usernames (`C:/Users/First Last/...`) cleanly. (If the path has no spaces, unquoted `-File C:/Users/<name>/.../statusline.ps1` also works.)
- Always use the expanded absolute path (`C:/Users/<name>/...`), never `~`.
- `-NoProfile` skips loading `$PROFILE` so ticks stay fast and deterministic; `-ExecutionPolicy Bypass` scopes execution permission to this single process.

#### Step 3 — Smoke test through Go-equivalent `cmd /c` argv escaping

Test using Python's `subprocess.run(['cmd', '/c', $cmd])` or `& cmd /c $cmd` (which applies the exact same MSVCRT `\"` escaping as Go's `exec.Command("cmd", "/c", command)` in `agy`, catching any accidental double-quote regressions):

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$scriptPath = ((Join-Path $HOME '.gemini\config\skills\agy-rich-statusline\assets\statusline.ps1') -replace '\\', '/')
$psExe = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' }
$cmd = "$psExe -NoProfile -ExecutionPolicy Bypass -Command . '$scriptPath'"
$smokeSpeed = Join-Path ([System.IO.Path]::GetTempPath()) ("agy-sl-smoke-" + [guid]::NewGuid().ToString('N'))
$env:AGY_STATUSLINE_SPEED_DIR = $smokeSpeed
$resetIso = [DateTimeOffset]::UtcNow.AddSeconds(219600).ToString('yyyy-MM-ddTHH:mm:ssZ')

$tick1 = @{
  conversation_id = 'smoke-conv'
  agent_state = 'running'
  model = @{ id = 'Gemini 4 Carbon (Medium)'; display_name = 'Gemini 4 Carbon (Medium)'; effort = 'medium' }
  workspace = @{ current_dir = $PWD.Path }
  vcs = @{ type = 'git'; branch = 'main'; dirty = $true }
  context_window = @{ used_percentage = 35.0; context_window_size = 1048576; total_output_tokens = 1200; current_usage = @{ output_tokens = 0 } }
  quota = @{ 'gemini-weekly' = @{ remaining_fraction = 0.34; reset_time = $resetIso; reset_in_seconds = 219600 } }
  subagents = @(@{ name = 'research-1'; role = 'Codebase Researcher'; model = 'flash'; status = 'running' })
  cost = @{ total_usd = 0.14; subagent_usd = 0.02; estimated = $true }
} | ConvertTo-Json -Depth 6 -Compress

$out1 = $tick1 | & cmd.exe /c $cmd
Start-Sleep -Milliseconds 900

$tick2 = @{
  conversation_id = 'smoke-conv'
  agent_state = 'idle'
  model = @{ id = 'Gemini 4 Carbon (Medium)'; display_name = 'Gemini 4 Carbon (Medium)'; effort = 'medium' }
  workspace = @{ current_dir = $PWD.Path }
  vcs = @{ type = 'git'; branch = 'main'; dirty = $true }
  context_window = @{ used_percentage = 35.2; context_window_size = 1048576; total_output_tokens = 1320; current_usage = @{ output_tokens = 120 } }
  quota = @{ 'gemini-weekly' = @{ remaining_fraction = 0.34; reset_time = $resetIso; reset_in_seconds = 219600 } }
  subagents = @()
  cost = @{ total_usd = 0.15; subagent_usd = 0.02; estimated = $true }
} | ConvertTo-Json -Depth 6 -Compress

$out2 = $tick2 | & cmd.exe /c $cmd
Remove-Item -Recurse -Force $smokeSpeed -ErrorAction SilentlyContinue
Remove-Item Env:\AGY_STATUSLINE_SPEED_DIR -ErrorAction SilentlyContinue

if ($LASTEXITCODE -eq 0 -and $out1 -and $out2) { 'PASS'; $out1; $out2 } else { "FAIL (exit $LASTEXITCODE)" }
```

#### Step 4 — Activate in `agy`

Give the user the exact `/statusline` command to run inside `agy` (using **single quotes**, never double quotes, around `<script-path>`):

```text
/statusline powershell -NoProfile -ExecutionPolicy Bypass -Command . 'C:/Users/<name>/.gemini/config/skills/agy-rich-statusline/assets/statusline.ps1'
```

Or in `~\.gemini\antigravity-cli\settings.json`:

```json
"statusLine": {
  "type": "command",
  "command": "powershell -NoProfile -ExecutionPolicy Bypass -Command . 'C:/Users/<name>/.gemini/config/skills/agy-rich-statusline/assets/statusline.ps1'",
  "enabled": true,
  "padding": 0,
  "stack_with_default": false
}
```

---

## Managing & Stacking in `agy`

Antigravity's built-in `/statusline` command controls the status bar live without restarting:

- `/statusline` — Toggle the statusline on or off.
- `/statusline on` / `/statusline off` (or `enable` / `disable`) — Explicitly enable or disable.
- `/statusline <command>` — Set and activate a custom command immediately.
- `/statusline delete` (or `reset`) — Remove the custom command and revert to `agy`'s built-in statusline.
- **Stacking with the built-in statusline:** Set `"stack_with_default": true` inside `"statusLine"` in `settings.json` (or test via `agy --settings '{"statusLine":{"stack_with_default":true}}'`) to keep Antigravity's default status bar and render this rich bar directly underneath it.
- **Auto-disable recovery:** If a script fails repeatedly, `agy` logs `Statusline disabled after N consecutive failures` and temporarily disables custom rendering. Once fixed, run `/statusline enable` in `agy` to re-enable it.

---

## Performance & Idle-Countdown Variant (`assets/perf/`, optional — macOS / Linux)

Antigravity refreshes `statusLine` on state changes (and periodically during streaming turns >=1 minute), but does **not** run a wall-clock `refreshInterval` timer while idle. On slow machines or if you want quota countdowns (`2h32m` → `2h31m`) to advance on disk while idle:

- **`~/.gemini/antigravity-cli/statusline.sh`** (`assets/perf/statusline-reader.sh`) — Thin reader: saves `statusline_snapshot.json` and returns `statusline_cache.txt` on repeated identical redraws (e.g. terminal resize), or calls `statusline-compute.sh` immediately whenever session/turn fields (`conversation_id`, `model`, `effort`, `cwd`, `used_percentage`, `total_output_tokens`, `agent_state`, `vcs`, `subagents`, `cost`) change.
- **`~/.gemini/antigravity-cli/statusline-daemon.sh`** (`assets/perf/statusline-daemon.sh`) — Recomputes the cached line every 30s from `statusline_snapshot.json` using each quota bucket's ISO `reset_time` so countdowns stay fresh.
- **`~/.gemini/antigravity-cli/statusline-compute.sh`** (`assets/perf/statusline-compute.sh`) — Pure renderer shared by both.

#### Install (`macOS / Linux`)

```bash
mkdir -p ~/.gemini/antigravity-cli
cp "<skill-path>/assets/perf/statusline-reader.sh"  ~/.gemini/antigravity-cli/statusline.sh
cp "<skill-path>/assets/perf/statusline-daemon.sh"  ~/.gemini/antigravity-cli/statusline-daemon.sh
cp "<skill-path>/assets/perf/statusline-compute.sh" ~/.gemini/antigravity-cli/statusline-compute.sh
chmod +x ~/.gemini/antigravity-cli/statusline.sh ~/.gemini/antigravity-cli/statusline-daemon.sh ~/.gemini/antigravity-cli/statusline-compute.sh
```

#### Run the daemon — macOS (`launchd`)

```bash
sed "s|__HOME__|$HOME|g" \
  "<skill-path>/assets/perf/com.user.agy-statusline-daemon.plist" \
  > ~/Library/LaunchAgents/com.user.agy-statusline-daemon.plist
launchctl unload ~/Library/LaunchAgents/com.user.agy-statusline-daemon.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.user.agy-statusline-daemon.plist
launchctl list | grep agy-statusline-daemon
```

#### Run the daemon — Linux (`systemd --user`)

```bash
mkdir -p ~/.config/systemd/user
cp "<skill-path>/assets/perf/agy-statusline-daemon.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agy-statusline-daemon.service
systemctl --user status agy-statusline-daemon.service
```

---

## Customizing

Both `statusline.sh` and `statusline.ps1` keep one clean section per segment:

- **Drop a segment** — Comment out the append block for Quota (`$quotaSegs` / `qitems`), Branch, Subagents (`$subSummary` / `sub_str`), Cost (`$costSummary` / `cost_str`), or Speed (`$speed` / `speed`).
- **Keep `.ps1` pure ASCII** — In `statusline.ps1`, always encode non-ASCII characters via `[char]0x...` or `[char]::ConvertFromUtf32(0x...)` so Windows PowerShell 5.1 never misparses UTF-8 bytes as smart quotes.
- **Change bar width or colors** — Edit `cells=5` (`p/20`, `rem >= 10`) and the RGB endpoints in `render_bar` / `Render-Bar`. For light terminal themes, replace track color `62;62;62` with `210;210;210`.

---

## What Antigravity (`agy`) feeds on `stdin`

For reference when extending this skill, `agy` serializes `StatusLineData` to `stdin` on updates:

```json
{
  "cwd": "/path/to/workspace",
  "session_id": "...",
  "conversation_id": "ec33ebf9-0cba-4100-8142-c61503f6c587",
  "conversation_title": "Refactor auth middleware",
  "transcript_path": "/path/to/brain/<id>/.system_generated/logs/transcript.jsonl",
  "model": {
    "id": "Gemini 4 Carbon (Medium)",
    "display_name": "Gemini 4 Carbon (Medium)",
    "effort": "medium"
  },
  "workspace": {
    "current_dir": "/path/to/workspace",
    "project_dir": "/path/to/workspace"
  },
  "version": "1.5.16",
  "context_window": {
    "total_input_tokens": 88244,
    "total_output_tokens": 61074,
    "context_window_size": 1048576,
    "used_percentage": 14.24,
    "remaining_percentage": 85.76,
    "current_usage": {
      "input_tokens": 63382,
      "output_tokens": 346,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 20857
    }
  },
  "quota": {
    "gemini-weekly": {
      "remaining_fraction": 0.9378,
      "reset_time": "2026-07-06T07:50:32Z",
      "reset_in_seconds": 560580
    }
  },
  "agent_state": "idle",
  "vcs": {
    "type": "git",
    "branch": "main",
    "dirty": true
  },
  "sandbox": {
    "enabled": true,
    "allow_network": false
  },
  "subagents": [
    {
      "name": "research-1",
      "role": "Codebase Researcher",
      "model": "flash",
      "status": "running"
    }
  ],
  "artifact_count": 1,
  "task_count": 0,
  "terminal_width": 180,
  "plan_tier": "Pro",
  "cost": {
    "total_usd": 0.142,
    "subagent_usd": 0.031,
    "estimated": true
  }
}
```

## Generation speed (`tok/s`)

Antigravity's `cost` object tracks dollar spend (`total_usd`, `subagent_usd`) rather than cumulative API duration milliseconds. Instead, `agy` triggers statusline updates when `agent_state` leaves `"idle"` (model begins thinking/generating) and again when a model step completes and `context_window.total_output_tokens` advances:

```text
tok/s = delta(output_tokens) / ((t_response_done_ms - t_phase_start_ms) / 1000)
```

State is stored per conversation in `~/.gemini/antigravity-cli/statusline-speed/<conversation_id>` (pruned automatically after 7 days):

- **Paused turns excluded:** Whenever `tool_confirmation_pending` is `true` or `pending_input_count > 0` (waiting on user approval or `ask_question`), the timer resets so user think-time never drags down `tok/s`.
- **Noise filtering:** Steps under 30 output tokens or 0.5 s, or spikes above 2000 tok/s, are skipped cleanly while preserving the previous reading.
- **Idempotent on idle redraws:** Re-rendering the same snapshot while `idle` sees no token delta and leaves the displayed `tok/s` untouched.
