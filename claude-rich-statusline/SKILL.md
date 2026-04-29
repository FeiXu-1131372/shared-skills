---
name: claude-rich-statusline
description: Install or configure a feature-rich Claude Code statusline that displays real-time context window usage (e.g. "Context 42% (84k/200k)"), 5-hour and weekly rate-limit consumption with reset countdowns, session duration, current model, and git branch. Use this skill whenever the user asks to set up a Claude Code status line, configure the statusLine field, see context window usage in their terminal, monitor Claude rate limits / token consumption, see how close they are to hitting their 5-hour or weekly limits, or wants any kind of real-time visibility into their Claude session — even if they don't explicitly say "statusline".
---

# Rich Claude Code Statusline

Claude Code can run a custom shell command on every message and display its single-line stdout as a status line below the prompt. This skill installs a status line that surfaces the things Claude Code itself only warns you about at critical thresholds — context window usage, rate limit consumption, session duration — so the user can pace their work proactively.

Sample output:

```
📊 Context: 42% (85k/200k) | 5h: 24% (4h12m) | 7d: 41% (3d5h) | Session: 2h5m | Model: Opus 4.7 | Branch: main
```

Each segment is independent. The 5h / 7d segments are dropped silently when Claude Code doesn't supply rate-limit data (some auth states omit it). The branch is dropped when the workspace isn't a git repo.

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

The install is three steps: write the script, register it in `settings.json`, smoke-test, restart.

### Step 1 — Verify `jq` is available

The script uses `jq` for JSON parsing. On macOS 13+ it's bundled at `/usr/bin/jq`. Otherwise:

- macOS: `brew install jq`
- Debian/Ubuntu: `sudo apt install jq`
- Fedora: `sudo dnf install jq`

Check before installing the script:

```bash
which jq && jq --version
```

If `jq` is missing the status line will fail silently (Claude Code will show no line). Tell the user to install it before continuing.

### Step 2 — Write `~/.claude/statusline.sh`

Copy `assets/statusline.sh` from this skill to `~/.claude/statusline.sh` and make it executable. Use the absolute path from where the skill is loaded:

```bash
mkdir -p ~/.claude
cp <skill-path>/assets/statusline.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```

If `~/.claude/statusline.sh` already exists, **stop and ask the user** before overwriting — they may have customized it. Show them the existing contents (`cat ~/.claude/statusline.sh`) and ask whether to replace, diff, or skip.

### Step 3 — Wire it into `~/.claude/settings.json`

Add a `statusLine` block. Use the `Read` then `Edit` tools rather than `Write` — `~/.claude/settings.json` likely already contains hooks, plugin config, model selection, etc. Don't clobber them.

The block to add (or merge):

```json
"statusLine": {
  "type": "command",
  "command": "bash ~/.claude/statusline.sh"
}
```

If `~/.claude/settings.json` doesn't exist, create it with just `{"statusLine": {...}}`.

For project-scoped statusline (only in one repo), put the same block in `<project>/.claude/settings.json` instead of the user-level file. Project-level wins over user-level when both are present.

### Step 4 — Smoke test

Run the script with a synthetic payload to confirm formatting works before the user reloads:

```bash
NOW=$(date +%s) bash -c '
echo "{
  \"model\": {\"display_name\": \"Opus 4.7\"},
  \"workspace\": {\"current_dir\": \"$PWD\"},
  \"cost\": {\"total_duration_ms\": 7500000},
  \"context_window\": {\"used_percentage\": 42.3, \"context_window_size\": 200000},
  \"rate_limits\": {
    \"five_hour\": {\"used_percentage\": 23.5, \"resets_at\": '"$(($(date +%s) + 4*3600 + 12*60))"'},
    \"seven_day\": {\"used_percentage\": 41.2, \"resets_at\": '"$(($(date +%s) + 3*86400 + 5*3600))"'}
  }
}" | bash ~/.claude/statusline.sh && echo
'
```

Expected (countdowns will reflect the actual current time, not literal `4h12m`):

```
📊 Context: 42% (85k/200k) | 5h: 24% (4h12m) | 7d: 41% (3d5h) | Session: 2h5m | Model: Opus 4.7 | Branch: <whatever>
```

### Step 5 — Reload

Tell the user to **restart Claude Code** (or `/config reload` if available). The new line will appear below the prompt on the next message.

## Customizing

The script in `assets/statusline.sh` is intentionally readable bash with one section per segment. Common edits:

**Drop a segment**
Comment out the relevant `if`/append block. Each of `5h`, `7d`, `Session`, `Model`, `Branch` is independent — removing one doesn't affect the others.

**Change emoji or labels**
Find the `line=` assignments. The very first line of output is `"📊 Context: ${pct_int}% (${used_k}/${total_k})"` — swap the emoji or rename the label freely.

**Add the rate-limit reset as wall-clock time instead of countdown**
Replace `fmt_countdown $(( five_reset - now ))` with `date -r $five_reset +%H:%M` (macOS) or `date -d @$five_reset +%H:%M` (Linux).

**Faster refresh**
Add `"refreshInterval": 1000` (milliseconds) inside the `statusLine` block in settings.json. Default is debounced after activity; this forces a wall-clock cadence so countdowns tick visibly.

**Show a warning color when close to a limit**
Wrap the segments in ANSI escape codes when `five_int -ge 80`. Example:

```bash
if [ "$five_int" -ge 80 ]; then
  five_segment="$(printf '\033[31m')5h: ${five_int}% (${five_in})$(printf '\033[0m')"
else
  five_segment="5h: ${five_int}% (${five_in})"
fi
```

## What Claude Code feeds the script

For reference (and for anyone forking this), Claude Code passes the following JSON on stdin every time it refreshes the status line:

```json
{
  "model": {"id": "claude-opus-4-7", "display_name": "Opus 4.7"},
  "workspace": {"current_dir": "...", "project_dir": "..."},
  "cost": {"total_cost_usd": 0.012, "total_duration_ms": 45000},
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
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
- `rate_limits` may be absent in some auth states (e.g. raw API key without subscription metadata). The script's `// empty` jq fallbacks handle that — those segments simply don't appear.

## Why this exists

Claude Code has no built-in indicator for context window utilization until you hit critical thresholds (warnings around 80%/90%). For long-running sessions, especially in 200k-context mode, that's late — by the time you see the warning you've already lost the ability to plan a graceful wrap-up. This statusline gives a continuous read so the user can pace.

The 5h / 7d rate-limit segments serve the same purpose for subscription quota — the user gets a glanceable answer to "can I keep coding for the next hour?" without leaving the terminal.
