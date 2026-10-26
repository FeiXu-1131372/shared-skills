---
name: droid-rich-statusline
description: Install or configure a feature-rich Factory Droid status line that displays real-time context window usage with a colored progress bar (e.g. "📊 █▌░░░ 35% (140k/400k)"), the Factory plan's 5-hour, weekly and monthly consumption with reset countdowns (e.g. "5h: █░░░░ 28% (2h32m)"), the current working directory, and the generation speed of the latest model call (e.g. "116.1 tok/s"). Bars use a smooth green→yellow→red truecolor gradient so the hue itself encodes severity. Works on macOS, Linux and Windows. Use this skill whenever the user asks to set up a Droid status line, configure the statusLine field in ~/.factory/settings.json, see context window usage in their terminal, monitor Factory plan limits / FSC consumption, see how close they are to their 5-hour or weekly cap, or wants any kind of real-time visibility into their Droid session — even if they don't explicitly say "statusline".
---

# Rich Droid Statusline

Droid can run a shell command on every redraw and show its stdout as a status line below the prompt. This skill installs a line that surfaces the things you otherwise only learn about at the worst moment: how much context you have burned, and how much of your Factory plan is left.

Sample output (the color lives in the bars themselves, gradient green → yellow → red):

```
📊 █▌░░░ 35% (140k/400k) │ 5h: ░░░░░ 2% (4h24m) │ 7d: ▌░░░░ 10% (2d4h) │ Month: ░░░░░ 5% (25d4h) │ 📁 web-business │ 116.1 tok/s
```

Every segment is independent, and each one drops out silently when its data is unavailable. To save width the context segment is marked by its 📊 icon rather than a text label; `5h` / `7d` / `Month` keep theirs because they tell the plan bars apart. The line degrades in this order:

- **No `node`** → no `5h` / `7d` / `Month` segments. Context, directory and speed still render.
- **No `jq`** (macOS/Linux) → the script prints one short install hint and nothing else.
- **Credentials in the OS keychain only** → no usage segments (see "Known limits").
- **No `context` in the payload** → no Context segment.
- **No readable `transcript_path` / `session_settings_path`**, or the latest call was too short to time → no `tok/s` segment.

**Visual encoding.** Bars are 5 cells wide (20% per cell) with a `▌` half block for the 10% step in between, rounded down (so 30% reads as `█▌░░░` rather than jumping from `█░░░░` to `██░░░`). The empty part is a flat dark-gray track (`░` in the samples here), and a half cell is the bar color on a track-colored background. Color is a smooth 24-bit gradient: pure green at 0%, yellow at 50%, pure red at 100%. Severity is glanceable from the hue alone — peripheral vision picks up "the bars are going orange" without reading a single number.

## When to use this skill

Trigger on any of:

- "set up [a/the] Droid statusline"
- "configure statusLine in Droid / ~/.factory/settings.json"
- "show me context usage in the terminal"
- "I want to see how much of my context I've used"
- "monitor my Factory plan / FSC usage"
- "how close am I to my 5-hour or weekly limit"
- "track my usage while I'm coding"

Don't trigger for:

- The **Claude Code** statusline — that is the sibling skill `claude-rich-statusline` in this same repo. Different settings file (`~/.claude/settings.json`), different payload shape, and Claude Code supplies its rate limits directly instead of needing an API call.
- A plain shell prompt (zsh/bash PS1, starship, oh-my-posh). Those are about your interactive shell, not Droid's status line.

## What it shows, and where each number comes from

| Segment | Source | Why |
|---|---|---|
| `📊` context bar | Droid's payload | Droid's own compaction meter, so it matches the threshold Droid acts on |
| `5h` / `7d` / `Month` | Factory billing API | Droid's payload carries no usage data at all |
| `📁 <dir>` | Droid's payload | Which project this tab is pointed at |
| `tok/s` | Droid's session files | The payload has no timing or output-token fields, so the two session files it points at supply them (see "Generation speed") |

The Context figure uses `context.percentage` with `context.adjusted_tokens` / `context.adjusted_limit`. Those are the numbers *after* Droid subtracts its fixed system-prompt baseline, which is exactly what the compaction meter uses. That makes it the honest "how close am I to compaction" number rather than a raw token count.

## Install — macOS / Linux

### Step 1 — Check dependencies

```bash
command -v jq && jq --version
command -v node && node --version
```

`jq` is required (macOS 13+ ships it at `/usr/bin/jq`; otherwise `brew install jq` or `sudo apt install jq`). `node` is needed only for the plan-usage segments. If `jq` is missing the line renders nothing but a hint, so install it first.

### Step 2 — Install the two scripts

```bash
mkdir -p ~/.factory
cp <skill-path>/assets/statusline.sh            ~/.factory/statusline.sh
cp <skill-path>/assets/fetch-usage.mjs          ~/.factory/statusline-fetch-usage.mjs
chmod +x ~/.factory/statusline.sh
```

The `.mjs` worker goes in `~/.factory/` rather than a scripts folder, because the status line reads it from there and the whole install stays in one predictable place.

If `~/.factory/statusline.sh` already exists, **stop and ask the user** before overwriting — they may have a customized line. Show them the current contents and offer to replace, diff, or skip.

### Step 3 — Wire it into `~/.factory/settings.json`

`statusLine` sits at the **root** of the file, not nested under `general`. Merge it in without disturbing existing keys:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash /Users/<you>/.factory/statusline.sh",
    "maxRows": 1
  }
}
```

Droid's statusLine schema accepts exactly `type`, `command`, `padding` and `maxRows` (1–3). Use an **absolute path** in `command` — `~` is not expanded there.

### Step 4 — Smoke test

```bash
echo '{"cwd":"'"$PWD"'","context":{"percentage":9,"adjusted_tokens":36000,"adjusted_limit":400000}}' \
  | bash ~/.factory/statusline.sh && echo
```

You should see the Context bar, then the plan segments (the first run writes the cache in the background, so the usage numbers may take one extra redraw to appear), then the folder name. There is no `tok/s` here: that payload names no session files. To see it, point the payload at a real session (substitute a project folder and session id from `~/.factory/sessions/`; each session is a `<id>.jsonl` transcript plus a `<id>.settings.json`):

```bash
S=~/.factory/sessions/-Users-<you>-<project>/<session-id>
echo '{"cwd":"'"$PWD"'","transcript_path":"'"$S.jsonl"'","session_settings_path":"'"$S.settings.json"'"}' \
  | bash ~/.factory/statusline.sh && echo
```

It ends with something like `│ 106.1 tok/s`, from that session's latest model call.

### Step 5 — Confirm against Droid's own budget

```bash
droid statusline-probe
```

This runs your configured command exactly the way Droid will, under the execution budget Droid enforces (5000 ms), and reports the result as JSON. Confirm it says `"ok": true`. **Do not skip this step** — a command that exceeds the budget renders nothing at all, and running the script yourself does not prove it fits. The installed line takes roughly 100–150 ms, so there is plenty of headroom.

Then restart Droid.

## Install — Windows

Windows needs no `jq` — PowerShell parses JSON natively. It does still need **Node** for the plan-usage segments, and the reason is worth stating plainly: Factory's credential file is AES-256-GCM with a **16-byte nonce**, and .NET's `AesGcm` accepts only 12. A native PowerShell decrypt is therefore not possible, so one small Node worker serves every platform and keeps the numbers identical everywhere.

### Step 1 — Check dependencies

```powershell
Get-Command node -ErrorAction SilentlyContinue
```

If Node is missing, install it (`winget install OpenJS.NodeJS`) or accept a line without the usage segments. Node is a reasonable assumption for anyone running Droid, and everything else works without it.

### Step 2 — Install the scripts

```powershell
New-Item -ItemType Directory -Force -Path (Join-Path $HOME '.factory') | Out-Null
Copy-Item '<skill-path>\assets\statusline.ps1'            (Join-Path $HOME '.factory\statusline.ps1')
Copy-Item '<skill-path>\assets\fetch-usage.mjs'          (Join-Path $HOME '.factory\statusline-fetch-usage.mjs')
```

As on macOS, **stop and ask** before overwriting an existing `statusline.ps1`.

### Step 3 — Wire it into `settings.json`

```json
{
  "statusLine": {
    "type": "command",
    "command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\<you>\\.factory\\statusline.ps1",
    "maxRows": 1
  }
}
```

Notes:

- Replace `<you>` with the real username — `~` does **not** expand inside `command`.
- If PowerShell 7 (`pwsh`) is installed, prefer it over `powershell`: noticeably faster startup, which makes the line feel snappier.
- `-NoProfile` keeps startup fast and deterministic. `-ExecutionPolicy Bypass` is scoped to this one invocation rather than loosening the machine-wide policy.

### Step 4 — Smoke test

```powershell
'{"cwd":"C:\\Users\\<you>\\project","context":{"percentage":9,"adjusted_tokens":36000,"adjusted_limit":400000}}' |
  powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\.factory\statusline.ps1"
```

To test the usage refresh on its own (it runs in the foreground and prints nothing on success):

```powershell
powershell -NoProfile -File "$HOME\.factory\statusline.ps1" -RefreshOnly
Get-Content "$HOME\.factory\statusline-usage.json"
```

### Step 5 — Confirm and restart

```powershell
droid statusline-probe
```

Confirm `"ok": true`, then restart Droid. Use **Windows Terminal** — the legacy `conhost.exe` does not render 24-bit color or the block characters properly, and you will see raw `␛[38;2;...m` text instead of bars.

## How the Factory usage numbers actually work

This is the only non-obvious part of the install, so it is worth understanding before troubleshooting.

**The problem.** Droid's status-line payload contains no usage data — no rate limits, no quota, nothing. The numbers live behind `GET https://api.factory.ai/api/billing/limits`, which needs a bearer token, and that call takes a few hundred milliseconds. Calling it on every redraw would make the prompt feel sluggish, and it would fail the moment the budget tightened.

**The solution — a cache and a detached worker.**

1. On each redraw, `statusline.sh` reads `~/.factory/statusline-usage.json`. That is a plain file read: microseconds.
2. If the cache is younger than 60 s, it renders as-is. If it is older, the numbers get a `~` suffix so you can see they are not fresh.
3. If the cache is older than 60 s **and** no refresh is already in flight, the script spawns `fetch-usage.mjs` detached and returns immediately. The redraw never waits for the network.
4. The worker decrypts the credential file, calls the API, and writes the cache atomically (temp file + rename, so a reader never sees a half-written file).
5. A lock file stops a burst of redraws from spawning a dozen workers at once.
6. Past 15 minutes without a successful refresh, the usage segments disappear rather than showing stale numbers as if they were current.

**How the token is read.** Droid keeps credentials in one of three places, newest first:

| Location | Notes |
|---|---|
| `auth.v2.keyring` / `auth.v2.loginkeychain` | OS keychain — macOS Keychain, Windows Credential Manager, libsecret. **Not read** by this skill. |
| `auth.v2.file` + `auth.v2.key` | Encrypted file. This is what the worker reads. |
| `auth.json` | Plain JSON, oldest format. Read as a fallback. |

The encrypted file is `base64(iv):base64(authTag):base64(ciphertext)`, AES-256-GCM, key from `auth.v2.key`. The worker re-reads it on every refresh, so a token Droid rotates is picked up automatically.

**Nothing is written back to Factory.** The worker only performs a `GET`. It does not refresh tokens, change settings, or touch your account.

## Generation speed (`tok/s`)

The last segment is the speed of the **latest model call** — not an average — so it tells you how fast the model is running right now. Droid's payload carries no timing or output-token fields, but it does point at two files that do:

```
tok/s = lastCallTokenUsage.outputTokens           (session_settings_path)
        / (timestamp of the newest assistant message in the transcript
           − timestamp of the message just before it)     (transcript_path)
```

The message just before an assistant message is the prompt or tool result that call was answering, so the gap is how long the call took to come back.

- **Cheap.** Only the last 24 lines of the transcript are read (a transcript can run to tens of MB), and only the head of each line on Windows, so it adds a few milliseconds.
- **Stateless.** Nothing is cached or written: the same two files always give the same number, and a redraw between calls changes nothing.
- **Tokens appear to include thinking.** A call with a short visible reply can report several times more output tokens than its text accounts for, which fits hidden reasoning being counted. The elapsed time covers that reasoning too, so the ratio is still a fair generation rate.
- **End-to-end, not raw decode speed.** The gap includes time-to-first-token and network, so it reads lower than the model's decode rate, most visibly on short replies. Timestamps have millisecond precision, so the figure is stable.
- **Short calls drop out.** Calls under 30 output tokens or 0.5 s are too noisy to be worth showing, and any reading above 2000 tok/s is discarded as a mismatch. In both cases the segment is simply absent for that call.
- **Not `assistantActiveTimeMs`.** The session settings file also has a cumulative active-time counter, but it can advance by minutes between two writes while the token counts don't move (it is not tied to model output), so dividing tokens by it gives a meaningless number. The timestamp gap is what the script uses.

## Truecolor support

The gradient bars use 24-bit color via `\033[38;2;R;G;Bm`. Supported by:

- macOS: Terminal.app (Catalina+), iTerm2, Alacritty, kitty, WezTerm, Ghostty, VS Code.
- Linux: GNOME Terminal, Konsole, xterm-256color with `COLORTERM=truecolor`, tmux 3.2+ with `terminal-overrides`.
- Windows: **Windows Terminal**. Not legacy `conhost.exe`.

If the user reports raw escape codes, the fix is "use a modern terminal", not "patch the script".

## Customizing

Both scripts are deliberately readable, with one section per segment.

**Drop a segment** — comment out its block. Each of Context, `5h`, `7d`, `Month`, the directory and `tok/s` is independent.

**Tune the tok/s noise filter** — in the speed block, `t >= 30 && d >= 0.5` skips calls under 30 output tokens or 0.5 s, and `t / d <= 2000` discards impossible readings (PowerShell: `$outTok -ge 30 -and $seconds -ge 0.5`, `$rate -le 2000`). Loosen the first two to show speed for very short replies; they read noisy. The `5h`/`7d`/`Month` loop is driven by a single list (`for window in fiveHour:5h weekly:7d monthly:Month`), so removing one entry is a one-line edit.

**Change emoji or labels** — find the `append "…"` calls (bash) or `$segments.Add(…)` (PowerShell).

**Show reset clock time instead of a countdown** — replace `fmt_countdown $(( end - now ))` with `date -r $end +%H:%M` (macOS) or `date -d @$end +%H:%M` (Linux). PowerShell: `[DateTimeOffset]::FromUnixTimeSeconds([int64]$end).LocalDateTime.ToString('HH:mm')`.

**Adjust freshness** — `FRESH=60` (how often to re-poll) and `USABLE=900` (when to give up and hide the segments).

**Different gradient** — in `render_bar`, `0%` → RGB(0,255,0), `50%` → RGB(255,255,0), `100%` → RGB(255,0,0). Change the `p <= 50` threshold to move the yellow point; change the RGB formulas for a different ramp. Update both scripts if you change it.

**Wider or narrower bars** — change `cells=5` and keep the per-cell step at `100/cells` (`p/20` and `rem >= 10` for 5 cells; `p/10` and `rem >= 5` for 10). 5 is compact; 10 or 20 give finer resolution at the cost of length. Update both scripts.

**Track color** — the empty cells and the half-cell background use RGB(62,62,62), which suits a dark terminal. On a light terminal use a light gray such as `210;210;210` instead (every `62;62;62` in `render_bar`, or in `Render-Bar`).

## What Droid feeds the script

For reference, and for anyone forking this:

```json
{
  "session_id": "...",
  "transcript_path": "...",
  "session_settings_path": "...",
  "cwd": "/path/to/project",
  "workspace": { "current_dir": "/path/to/project" },
  "model": { "id": "...", "display_name": "...", "reasoning_effort": "xhigh" },
  "context": {
    "last_call_compaction_tokens": 12345,
    "token_limit": 400000,
    "adjusted_tokens": 36000,
    "adjusted_limit": 400000,
    "percentage": 9,
    "display": "9%"
  },
  "version": "1.0.71"
}
```

Notes:

- `context` is **nullable** — it is `null` before the first turn, and both scripts handle that by dropping the segment.
- `adjusted_*` subtract the fixed system-prompt baseline; `token_limit` is the raw configured limit. The scripts use the adjusted pair so the display matches Droid's compaction behavior.
- There is **no** `rate_limits` field. That absence is the entire reason for the worker.
- There is also no output-token or timing field. `transcript_path` (a JSONL file, one object per line, message lines carrying `timestamp` and `message.role`) and `session_settings_path` (JSON with `lastCallTokenUsage.outputTokens`, cumulative `tokenUsage` and `assistantActiveTimeMs`) are how the `tok/s` segment gets them.
- `maxRows` caps the height; the script prints a single line and no trailing newline.

## Known limits

**Keychain-only credentials.** If a machine stores its credentials *only* in `auth.v2.keyring` (or `auth.v2.loginkeychain`) with no `auth.v2.file`, the worker cannot read them and the usage segments stay hidden. Context and directory still work. The worker logs why to `~/.factory/statusline-usage.log`. This is a deliberate trade: reading the OS keychain would mean shipping a native keyring dependency for one optional segment.

**Token expiry.** The API needs a valid access token, which Droid rotates roughly every 20 hours. The worker re-reads the credential file each time, so rotation is handled automatically as long as Droid is in use. If the machine sits idle for a long stretch the usage segments may drop out until Droid refreshes.

**Plan shape.** The worker reads `limits.standard` and falls back to `limits.core`, preferring whichever has a live window, so it matches the Factory dashboard on both metered styles.

**Countdown freshness.** Droid's statusLine schema has no refresh-interval option (unlike Claude Code's), so countdowns advance when Droid redraws the line — on turn end and tool use. An idle tab's countdown looks frozen until the next redraw. That is a Droid limitation, not a bug in the script.

**tok/s depends on Droid's session file layout.** The speed comes from the transcript's per-message `timestamp` and `message.role` and from `lastCallTokenUsage.outputTokens`, which are Droid internals rather than a documented interface. If a Droid update renames them, the segment quietly disappears (the rest of the line is unaffected) until the script is adjusted. If the settings file and the transcript are ever written at slightly different moments, a redraw could pair one call's tokens with a neighbouring call's timing; the next redraw corrects it. (In the sessions this was tested against, both files were written together.)

**Logs.** Failures append to `~/.factory/statusline-usage.log` and never print to the status line. If the usage segments will not appear, read that file first — it names the reason (`no access token found`, `billing limits returned HTTP 401`, `node not found`, and so on).

## Why this exists

Droid gives you no continuous read on context consumption until you are close to compaction, and no read at all on plan consumption. Both are the kind of thing you want to know *before* starting a long refactor, not after.

The gradient encoding means you do not have to read the numbers. Green means keep going; orange means wrap up the current thread; red means stop starting new work.
