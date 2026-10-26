---
name: claude-rich-statusline
description: Install or configure a feature-rich Claude Code statusline that displays real-time context window usage with a colored progress bar (e.g. "Context █▌░░░ 35% (350k/1000k)"), 5-hour and weekly rate-limit consumption with reset countdowns, current model with its reasoning effort, current directory, git branch, and the generation speed of the latest response (e.g. "116.1 tok/s"). Bars use a smooth green→yellow→red truecolor gradient so the hue itself encodes severity. Works on macOS, Linux, and Windows (Windows Terminal + PowerShell). Use this skill whenever the user asks to set up a Claude Code status line, configure the statusLine field, see context window usage in their terminal, monitor Claude rate limits / token consumption, see how close they are to hitting their 5-hour or weekly limits, or wants any kind of real-time visibility into their Claude session — even if they don't explicitly say "statusline".
---

# Rich Claude Code Statusline

Claude Code can run a custom shell command on every message and display its single-line stdout as a status line below the prompt. This skill installs a status line that surfaces the things Claude Code itself only warns you about at critical thresholds — context window usage and rate limit consumption — alongside the model, reasoning effort, and working directory, so the user can pace their work proactively.

Sample output (color in the bars themselves, gradient green→yellow→red):

```
📊 Context: █▌░░░ 35% (350k/1000k) │ 5h: █░░░░ 28% (2h32m) │ 7d: ███░░ 66% (2d10h) │ Model: Opus 4.7 (high) │ Dir: ~/Developer/my-project │ Branch: main │ 116.1 tok/s
```

Each segment is independent. The 5h / 7d segments are dropped silently when Claude Code doesn't supply rate-limit data (some auth states omit it). The effort suffix on the model (`(high)`, `(xhigh)`, …) is dropped when the model has no effort level. `Dir:` shows the workspace directory with `$HOME` abbreviated to `~`. The branch is dropped when the workspace isn't a git repo.

**Generation speed (`tok/s`).** The last segment is the speed of the *latest* response only — not an average — so it tells you how fast the model is running right now. It is the output tokens of that response divided by the API time it took (the growth in `cost.total_api_duration_ms` since the previous status-line update). See "Generation speed" below for what it does and doesn't measure.

**Visual encoding.** Bars are 5 cells wide (20% per cell) with a `▌` half block for the 10% step in between, rounded down (so 30% reads as `█▌░░░` rather than jumping from `█░░░░` to `██░░░`). The empty part is a flat dark-gray track (`░` in the samples here), and a half cell is the bar color on a track-colored background. Color is a smooth 24-bit gradient: pure green at 0%, yellow at 50%, pure red at 100%, interpolated linearly. Severity is glanceable from the hue alone — no need to read the number.

## When to use this skill

Trigger on any of:

- "set up [a/the] statusline"
- "configure statusLine [in Claude Code]"
- "show me context usage in the terminal"
- "I want to see how much of my context I've used"
- "monitor my Claude rate limits"
- "track token consumption while I'm coding"
- "how close am I to my weekly limit"
- "real-time context info"

Don't trigger for:

- Unrelated shell prompt setup (e.g. "configure my zsh prompt", "set up starship") — those are about the user's interactive shell, not Claude Code's status line.
- Fixing a *broken* statusline that isn't this one (the user already has another statusline and just wants it repaired) — clarify first.

## Install

The install is four steps: verify deps, write the script, register it in `settings.json`, smoke-test, restart. Pick the macOS/Linux or Windows path below.

### macOS / Linux (bash)

#### Step 1 — Verify `jq`

The bash script uses `jq` for JSON parsing. On macOS 13+ it's bundled at `/usr/bin/jq`. Otherwise:

- macOS: `brew install jq`
- Debian/Ubuntu: `sudo apt install jq`
- Fedora: `sudo dnf install jq`

Check before installing the script:

```bash
which jq && jq --version
```

If `jq` is missing the status line will fail silently (Claude Code will show no line). Tell the user to install it before continuing.

#### Step 2 — Write `~/.claude/statusline.sh`

Copy `assets/statusline.sh` from this skill to `~/.claude/statusline.sh` and make it executable. Use the absolute path from where the skill is loaded:

```bash
mkdir -p ~/.claude
cp <skill-path>/assets/statusline.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```

If `~/.claude/statusline.sh` already exists, **stop and ask the user** before overwriting — they may have customized it. Show them the existing contents (`cat ~/.claude/statusline.sh`) and ask whether to replace, diff, or skip.

#### Step 3 — Wire it into `~/.claude/settings.json`

Use `Read` then `Edit` to add a `statusLine` block — `~/.claude/settings.json` likely already contains hooks, plugin config, model selection, etc. Don't clobber them.

```json
"statusLine": {
  "type": "command",
  "command": "bash ~/.claude/statusline.sh",
  "refreshInterval": 60
}
```

`refreshInterval` (seconds) re-runs the script on a wall-clock cadence in addition to Claude Code's event-driven updates. Without it the script only re-runs on events (turn end, tool use), so the rate-limit countdowns freeze between turns. 60s is enough for the minute-granularity countdowns to stay visibly fresh.

If `~/.claude/settings.json` doesn't exist, create it with just `{"statusLine": {...}}`.

For project-scoped statusline, put the same block in `<project>/.claude/settings.json`. Project-level wins over user-level.

#### Step 4 — Smoke test

Run the script with a synthetic payload to confirm formatting + colors before the user reloads:

```bash
NOW=$(date +%s)
echo "{
  \"model\": {\"display_name\": \"Opus 4.7\"},
  \"effort\": {\"level\": \"high\"},
  \"workspace\": {\"current_dir\": \"$PWD\"},
  \"context_window\": {\"used_percentage\": 42.3, \"context_window_size\": 200000},
  \"rate_limits\": {
    \"five_hour\": {\"used_percentage\": 23.5, \"resets_at\": $((NOW + 4*3600 + 12*60))},
    \"seven_day\": {\"used_percentage\": 41.2, \"resets_at\": $((NOW + 3*86400 + 5*3600))}
  }
}" | bash ~/.claude/statusline.sh && echo
```

You should see three colored bars (yellow-green Context, yellow-green 5h, yellow-green 7d) and segment separators (`│`). If the bars appear monochrome, the terminal lacks 24-bit color — see "Truecolor support" below.

The `tok/s` segment won't be in that output: it needs two ticks in the same session to have anything to measure. To see it, feed two payloads with the same `session_id` and a growing `cost.total_api_duration_ms`. A throwaway `HOME` keeps a real session's state untouched:

```bash
SMOKE_HOME=$(mktemp -d)
for tick in "10000 200" "16000 600"; do
  api=${tick% *}; out=${tick#* }
  echo "{\"session_id\":\"smoke\",\"cost\":{\"total_api_duration_ms\":$api},\"context_window\":{\"used_percentage\":10,\"context_window_size\":200000,\"current_usage\":{\"output_tokens\":$out}}}" \
    | HOME="$SMOKE_HOME" bash ~/.claude/statusline.sh && echo
done
```

The first line has no speed (it only records a baseline); the second should end with `│ 100.0 tok/s` (600 tokens over 6 s). In a real session the segment appears after the second response finishes.

### Windows (Windows Terminal + PowerShell)

The PowerShell script is dependency-free — no `jq` needed, since PowerShell parses JSON natively.

**Requirements:**
- **Windows Terminal** (recommended). The legacy `conhost.exe` (the old black-and-blue console) does not reliably interpret 24-bit color or unicode block characters. Install Windows Terminal from the Microsoft Store if the user is still on `conhost`.
- **PowerShell 5.1+** (built into Windows 10/11) or PowerShell 7+ (`pwsh`). Both work.
- **Git for Windows** if you want the `Branch:` segment to populate.

#### Step 1 — Write `statusline.ps1`

Copy `assets/statusline.ps1` from this skill to `~\.claude\statusline.ps1` (which on Windows resolves to `C:\Users\<name>\.claude\statusline.ps1`):

```powershell
$claudeDir = Join-Path $HOME '.claude'
New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
Copy-Item -Path '<skill-path>\assets\statusline.ps1' -Destination (Join-Path $claudeDir 'statusline.ps1') -Force
```

If `statusline.ps1` already exists, **stop and ask** before overwriting (same caution as the bash path).

#### Step 2 — Wire it into `settings.json`

`~\.claude\settings.json` uses the same JSON format on Windows. Add (or merge):

```json
"statusLine": {
  "type": "command",
  "command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\<name>\\.claude\\statusline.ps1"
}
```

Notes:
- Replace `<name>` with the actual Windows username — `~` does **not** expand inside the `command` string. If the user has PowerShell 7 (`pwsh`) installed, prefer `pwsh` over `powershell` for ~3× faster startup, which makes the statusline noticeably more responsive.
- `-NoProfile` skips loading the user's profile (faster, deterministic).
- `-ExecutionPolicy Bypass` is needed because Windows blocks unsigned scripts by default. Scoping it to this single invocation (rather than changing the system-wide policy) is the safer choice.

For an even faster startup using PowerShell 7:

```json
"statusLine": {
  "type": "command",
  "command": "pwsh -NoProfile -File C:\\Users\\<name>\\.claude\\statusline.ps1"
}
```

#### Step 3 — Smoke test

In Windows Terminal, run:

```powershell
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$payload = @{
  model = @{ display_name = 'Opus 4.7' }
  effort = @{ level = 'high' }
  workspace = @{ current_dir = $PWD.Path }
  context_window = @{ used_percentage = 42.3; context_window_size = 200000 }
  rate_limits = @{
    five_hour = @{ used_percentage = 23.5; resets_at = ($now + 4*3600 + 12*60) }
    seven_day = @{ used_percentage = 41.2; resets_at = ($now + 3*86400 + 5*3600) }
  }
} | ConvertTo-Json -Depth 5

$payload | powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\.claude\statusline.ps1"
Write-Host
```

You should see the same colored bars as the macOS/Linux version. If the line shows raw escape codes like `␛[38;2;...m`, the host doesn't support virtual-terminal sequences — switch to Windows Terminal.

### Performance variant — thin reader + background daemon (optional)

The default `statusline.sh` invokes `jq` ~9 times per Claude Code tick. On most systems that's ~30 ms — invisible. On slow systems (older laptops, cold-cache jq, network-mounted homes), it can stutter the prompt or stall countdown ticks.

The performance variant splits the work in three:

- **`~/.claude/statusline.sh`** — a thin reader. Persists the latest JSON snapshot, then either serves the daemon's pre-rendered cache (fast) or recomputes on the fly when the session identity (`session_id` / cwd / model / effort / context size) changes.
- **`~/.claude/statusline-daemon.sh`** — a background loop that recomputes the line every 30s from the persisted snapshot, so countdowns advance even when Claude is idle.
- **`~/.claude/statusline-compute.sh`** — pure rendering logic, called by both.

**Important:** the thin reader keys the cache by session identity (`session_id|cwd|model|effort|ctx_size|api_duration_ms`). Without that check, starting a new session with a different model, effort, cwd, or context window would show the previous session's line until the daemon's next 30s tick. The API duration is in the key because it only grows when a response finishes, so each finished response refreshes the line (and its `tok/s`) straight away instead of waiting for the daemon. Always install the matching daemon — they share the identity file `~/.claude/statusline_cache_id.txt`.

#### Install (macOS / Linux)

```bash
# 1. Drop the three scripts in place.
mkdir -p ~/.claude
cp <skill-path>/assets/perf/statusline-reader.sh   ~/.claude/statusline.sh
cp <skill-path>/assets/perf/statusline-daemon.sh   ~/.claude/statusline-daemon.sh
cp <skill-path>/assets/perf/statusline-compute.sh  ~/.claude/statusline-compute.sh
chmod +x ~/.claude/statusline.sh ~/.claude/statusline-daemon.sh ~/.claude/statusline-compute.sh
```

The `statusLine` block in `settings.json` stays the same — `bash ~/.claude/statusline.sh`.

#### Run the daemon — macOS (launchd user agent)

```bash
# Substitute $HOME into the plist (launchd does not expand ~ in paths).
sed "s|__HOME__|$HOME|g" \
  <skill-path>/assets/perf/com.user.claude-statusline-daemon.plist \
  > ~/Library/LaunchAgents/com.user.claude-statusline-daemon.plist

# Load it. Re-loading is safe if it was already loaded.
launchctl unload ~/Library/LaunchAgents/com.user.claude-statusline-daemon.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.user.claude-statusline-daemon.plist

# Verify it's running.
launchctl list | grep claude-statusline-daemon
```

Logs land at `~/.claude/statusline-daemon.log`.

#### Run the daemon — Linux (systemd user service)

```bash
mkdir -p ~/.config/systemd/user
cp <skill-path>/assets/perf/claude-statusline-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-statusline-daemon.service

# Verify.
systemctl --user status claude-statusline-daemon.service
```

Logs land in the user journal: `journalctl --user -u claude-statusline-daemon -f`.

#### Uninstall

macOS:
```bash
launchctl unload ~/Library/LaunchAgents/com.user.claude-statusline-daemon.plist
rm ~/Library/LaunchAgents/com.user.claude-statusline-daemon.plist
```

Linux:
```bash
systemctl --user disable --now claude-statusline-daemon.service
rm ~/.config/systemd/user/claude-statusline-daemon.service
systemctl --user daemon-reload
```

Then either restore the self-contained `statusline.sh` from `assets/statusline.sh`, or remove the `statusLine` block from `settings.json` entirely. The `tok/s` segment's small per-session files live in `~/.claude/statusline-speed/` (`~\.claude\statusline-speed\` on Windows); delete that folder when uninstalling.

#### When NOT to use the performance variant

- Single-platform Windows install (no launchd / systemd; the .ps1 is already fast — PowerShell's native JSON parsing has none of the jq overhead).
- Systems where you don't want background processes running for any reason (the daemon is ~0.1% CPU but it's still always-on).
- The default `statusline.sh` already feels snappy — no need to add complexity.

### Step 5 (both platforms) — Reload

Tell the user to **restart Claude Code** (or `/config reload` if available). The new line will appear below the prompt on the next message.

## Truecolor support

The gradient bars use 24-bit color via `\033[38;2;R;G;Bm` ANSI escapes. Supported by:

- macOS Terminal.app (Catalina+), iTerm2, Alacritty, kitty, WezTerm, Ghostty, VS Code integrated terminal.
- Linux: most modern terminals (GNOME Terminal, Konsole, xterm-256color with `COLORTERM=truecolor`, tmux 3.2+ with `terminal-overrides`).
- **Windows Terminal** (full support since launch).
- **NOT** legacy Windows `conhost.exe` (the old console host) — escape codes appear as raw text.

If the user reports raw `␛[38;2;...m` strings, the fix is "use a modern terminal," not "patch the script." If they need a fallback, replace `render_bar` with the 16-color version below (commented out at the bottom of `statusline.sh` for reference).

## Customizing

The scripts are intentionally readable, with one section per segment. Common edits:

**Drop a segment** — Comment out the relevant `if`/append block. Each of `5h`, `7d`, `Model`, `Dir`, `Branch`, `tok/s` is independent.

**Tune the tok/s noise filter** — In the speed block, `t >= 30 && d >= 500` ignores responses under 30 output tokens or 0.5 s of API time, and `<= 2000` discards impossible readings. Loosen the first two to show speed for very short replies (they read noisy), or change what happens when a response is skipped: today the previous figure stays on screen; to blank the segment instead, add `else new_rate=""` after the `new_rate="$r"` line (bash) or reset `$newRate = ''` when the filter fails (PowerShell).

**Change emoji or labels** — Find the `line=` (bash) or `$line =` (PowerShell) assignments. Swap freely.

**Use wall-clock reset time instead of countdown** — Replace `fmt_countdown $(( five_reset - now ))` (bash) with `date -r $five_reset +%H:%M` (macOS) or `date -d @$five_reset +%H:%M` (Linux). On PowerShell: `[DateTimeOffset]::FromUnixTimeSeconds([int]$fiveReset).LocalDateTime.ToString('HH:mm')`.

**Faster (or slower) refresh**
The install sets `refreshInterval: 60` (seconds — schema minimum is 1, not milliseconds). Drop to `5` for snappier ticking or raise to `300` to spawn fewer subprocesses. Setting it too high (or omitting it) means the countdowns only update when Claude Code triggers an event, which is what most users perceive as "frozen".

**Different gradient endpoints** — In `render_bar`, the formula is:
- `0%` → RGB(0,255,0) (pure green)
- `50%` → RGB(255,255,0) (pure yellow)
- `100%` → RGB(255,0,0) (pure red)

To shift the breakpoint (e.g. yellow at 70% instead of 50%), change the threshold in the `if (p <= 50)` line. To use a blue→purple→pink gradient instead of green→yellow→red, replace the RGB formulas — both scripts share the same logic so update both.

**Wider or narrower bars** — Change `cells=5` in `render_bar` and keep the per-cell step at `100/cells` (`p/20` and `rem >= 10` for 5 cells; `p/10` and `rem >= 5` for 10). 5 cells is compact; 10 or 20 give finer visual granularity at the cost of line length. The PowerShell script and `assets/perf/statusline-compute.sh` carry the same logic — update all three.

**Track color** — The empty cells and the half-cell background use RGB(62,62,62), which suits a dark terminal. On a light terminal use a light gray such as `210;210;210` instead (every `62;62;62` in `render_bar`, or `62;62;62` in `Render-Bar`).

## What Claude Code feeds the script

For reference (and for anyone forking this), Claude Code passes the following JSON on stdin every time it refreshes the status line:

```json
{
  "model": {"id": "claude-opus-4-7", "display_name": "Opus 4.7"},
  "effort": {"level": "high"},
  "workspace": {"current_dir": "...", "project_dir": "..."},
  "cost": {"total_cost_usd": 0.012, "total_duration_ms": 45000, "total_api_duration_ms": 13640},
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
    "current_usage": {"output_tokens": 154},
    "context_window_size": 200000,
    "used_percentage": 8.4
  },
  "rate_limits": {
    "five_hour": {"used_percentage": 23.5, "resets_at": 1738425600},
    "seven_day": {"used_percentage": 41.2, "resets_at": 1738857600}
  },
  "session_id": "..."
}
```

Notes:

- `context_window_size` is dynamic — `200000` for standard-context Sonnet/Opus, `1000000` for the `[1m]` extended-context variants. The script reads it directly so the `(85k/1000k)` format auto-adapts.
- `total_input_tokens + total_output_tokens` is the *cumulative* count for the session, **not** the current context. The script computes current usage as `used_percentage × context_window_size / 100` instead, which matches what Claude Code's own threshold warnings use.
- `effort` may be absent for models without reasoning-effort levels; the scripts then show the bare model name.
- `rate_limits` may be absent in some auth states (e.g. raw API key without subscription metadata). Both scripts' fallbacks handle that — those segments simply don't appear.
- `cost.total_api_duration_ms` is *cumulative* time spent in API calls this session, and `context_window.current_usage.output_tokens` is the output (including thinking) tokens of the *last* response only — not a running total. Those two are what the `tok/s` segment uses; the scripts fall back to `total_output_tokens` if `current_usage` is absent.

## Generation speed (`tok/s`)

Claude Code doesn't hand the status line a speed, and the only timing it exposes is a cumulative API duration that moves when a response completes, so a live, mid-stream figure isn't possible. What the script shows is the speed of the **last completed response**:

```
tok/s = output_tokens of the last response
        / (growth in cost.total_api_duration_ms since the previous status-line update)
```

Because that needs the previous duration, the script keeps a tiny per-session file, `~/.claude/statusline-speed/<session_id>`, holding the last duration and the last rate (files older than 7 days are pruned when a new session file is created). Re-rendering the same snapshot never changes the number: the daemon's 30-second recomputes and `refreshInterval` timer ticks see no growth in the duration, so they leave the figure alone.

What to expect:

- **Nothing at first.** The segment appears after the *second* response in a session, once there are two durations to diff.
- **End-to-end, not raw decode speed.** The API time includes time-to-first-token and network, so it reads lower than the model's decode rate, most visibly on short replies.
- **Short replies are skipped.** Responses under 30 output tokens or 0.5 s are too noisy; the previous figure stays on screen instead of showing a bad one.
- **Can read low.** If two responses finish between two status-line updates, or subagent / side-query API time lands in the same window, the duration is larger than the response alone.
- **Sanity cap.** Any reading above 2000 tok/s is discarded as a mismatch.

## Why this exists

Claude Code has no built-in indicator for context window utilization until you hit critical thresholds (warnings around 80%/90%). For long-running sessions, especially in 1M-context mode, that's late — by the time you see the warning you've already lost the ability to plan a graceful wrap-up. This statusline gives a continuous read so the user can pace.

The 5h / 7d rate-limit segments serve the same purpose for subscription quota — the user gets a glanceable answer to "can I keep coding for the next hour?" without leaving the terminal.

The gradient color encoding means you don't even have to read the percentages — peripheral vision picks up "the bars are turning orange" or "everything's still green" without conscious attention.
