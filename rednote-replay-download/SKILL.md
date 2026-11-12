---
name: rednote-replay-download
description: Extract playback URLs and download video from Xiaohongshu (Rednote / 小红书) — livestream replays (HLS), currently-live streams (FLV), regular note video posts (`/explore/{note_id}`, plain MP4 ladder up to 4K), and event/match pages (`/worldcup26/match/...` etc.) that link to video notes. Invoke whenever the user pastes a `xiaohongshu.com/hina/livereplay/...`, `xiaohongshu.com/fe/live-h5/page/live_replay/...`, `xiaohongshu.com/livestream/...`, `xiaohongshu.com/explore/...`, or `xiaohongshu.com/worldcup26/...` URL with any download/record/save intent, or says "download xiaohongshu replay", "download rednote video", "save xhs livestream", "record xhs live", "download the 小红书 video", "save the 小红书 replay", "小红书直播回放下载", "小红书直播录制", "小红书视频下载", "小红书视频4K下载", or anything similar. Also use it if they only want the raw playback URL handed back (no download) so they can pipe it into their own tool. The user is responsible for copyright/ToS compliance — typical use is saving their own content or content they have permission to download.
---

# Rednote (Xiaohongshu) live & replay downloader

XHS video isn't directly downloadable through the web UI. Every flavour exposes its playback URL(s) somewhere machine-readable — an internal JSON endpoint, the SSR page state, or the network log; the cleanest path is to ride the user's Chrome login via `agent-browser`, capture the URL, then hand it to `yt-dlp` (or back to the user).

The flavours differ in important ways:
- **Note video post** (`/explore/{note_id}`) — regular user/official video posts, including full-match replays posted as notes (全场回放). Source: `window.__INITIAL_STATE__` in the page HTML. Format: plain signed MP4s on `sns-video-*.xhscdn.com`, one per (codec, resolution) rung — can go up to 4K h264/h265. Anonymous pages may only expose the low rungs (e.g. 720p); the **full ladder often requires login**. Download big files with yt-dlp + aria2c.
- **Event/match page** (`/worldcup26/match/{match_id}`, similar campaign pages) — not a video page itself. Its SSR state (`worldCupMatch`) lists linked video notes (highlights, goal clips, full replays) with `noteId` + `xsecToken`; build note URLs from those and treat them as note posts. yt-dlp's generic extractor fails on these pages.
- **Replay** (`/hina/livereplay/{room_id}` or `/fe/live-h5/page/live_replay/{room_id}`) — past livestream broadcast. API: `clip_detail_web`. Format: HLS `.m3u8`. Has fixed duration. Downloadable to MP4 with `yt-dlp -N 16` in a few minutes.
- **Live** (`/livestream/{room_id}`) — currently broadcasting. API: `current_room_info` on `live-room.xiaohongshu.com`. Format: HTTP-FLV (continuous feed). URL is only valid while the host is live. Record-while-live with `yt-dlp` / `ffmpeg`; stop with Ctrl+C.

## Prerequisites

Check these before starting:

- `agent-browser` installed (`which agent-browser`). If missing: `brew install agent-browser` or `npm i -g agent-browser`.
- `yt-dlp` installed (`which yt-dlp`). If missing: `brew install yt-dlp`. This is the **primary downloader** — it fetches HLS segments in parallel and is typically 6–15× faster than ffmpeg for long replays.
- `ffmpeg` installed (`which ffmpeg`). Used by yt-dlp internally for the final MP4 fixup pass, and as a fallback if yt-dlp ever fails. If missing: `brew install ffmpeg`.
- `aria2c` installed (`which aria2c`) — only needed for **note posts**, where the video is one big plain MP4 (no HLS fragments for `-N` to parallelize). If missing: `brew install aria2`.
- An XHS-authenticated agent-browser profile at `~/.agent-browser-xhs` — **required for live streams** (`/livestream/` URLs) and **recommended for note posts** (the full quality ladder, e.g. 1080p/4K rungs, is often only exposed to logged-in sessions). Livestream replays (`/livereplay/`, `/live_replay/`) work anonymously: the `clip_detail_web` API is public read. Check if the profile exists with `test -d ~/.agent-browser-xhs && echo ready`. If missing and you need it, walk through the **one-time setup** below.

### One-time profile setup (only needed for live URLs, only if `~/.agent-browser-xhs` doesn't exist yet)

```bash
agent-browser --profile ~/.agent-browser-xhs --headed --session xhs-setup open https://www.xiaohongshu.com/
```

Tell the user to scan the QR with their XHS / REDNote mobile app (Me → top-right scan icon → confirm on phone). The page should redirect to their feed (`/explore`) once login succeeds. Verify with a screenshot, then `agent-browser --session xhs-setup close`. The profile cookies persist in `~/.agent-browser-xhs/` for all future runs — no more Chrome quitting.

If the user has multiple XHS accounts and you need a different one, set up a parallel profile (e.g. `~/.agent-browser-xhs-alt`) and pass that path instead. One profile per account.

**Re-login when cookies expire.** If the profile exists but pages render logged-out (a red 登录 button in the sidebar), open the homepage headed with the profile, click 登录, and have the user scan the QR again — the session flips to logged-in within seconds (watch for the 登录成功 toast in a screenshot). No need to redo the whole setup.

## Workflow

### 1. Parse the URL and pick a flavour

URL shapes you'll see in the wild:

| Shape | Flavour | Continue at |
|---|---|---|
| `xiaohongshu.com/explore/{note_id}?xsec_token=...` | Note video post | step 3c |
| `xiaohongshu.com/worldcup26/match/{match_id}?...` (or similar campaign/event pages) | Event/match page | step 3d |
| `xiaohongshu.com/hina/livereplay/{room_id}?share_source_id={clip_id}&host_id={host_id}&...` | Livestream replay | step 3a |
| `xiaohongshu.com/fe/live-h5/page/live_replay/{room_id}?...` (replay page after redirect) | Livestream replay | step 3a |
| `xiaohongshu.com/livestream/{room_id}?...` | Live (currently broadcasting) | step 3b |

For **note** URLs, the `xsec_token` query param matters — keep the URL intact. If the user pasted a bare `/explore/{note_id}` with no token and the page 404s or shows nothing, ask for the full share link.

For **event/match** pages there's nothing to extract from the URL beyond the page itself — step 3d mines the SSR state for the linked video notes.

For **replay** URLs, extract three values:
- **`room_id`** — last path segment (a long numeric ID)
- **`clip_id`** — from the `share_source_id` query param
- **`host_id`** — from the `host_id` query param

If `clip_id` or `host_id` is missing, ask the user to repaste the full share link (those params come from the original share). If they pre-extracted the IDs and gave them to you directly, skip to step 3a.

For **live** URLs, you only need the `room_id` (the path segment). There's no `clip_id`/`host_id` because the stream isn't archived yet — XHS knows it by room only.

### 2. Choose an auth path (live + quality-gated notes — anonymous replays skip this)

**If the URL is a livestream replay, skip to step 3a.** The `clip_detail_web` API returns the full payload (including `video_url`) without any login, so you just need a vanilla agent-browser session — no profile, no auth.

**If the URL is a note post, start anonymous** (plain curl of the page HTML is enough — see step 3c). Only switch to the logged-in profile if the quality ladder is capped below what the user expects (e.g. only 720p visible but they can watch 4K when logged in) or the note requires login to view at all.

**If the URL is live**, the page hard-gates anonymous access (461 → redirect to `/website-login/error`). You must use a logged-in session. Pick the first option that applies:

**Option A — Dedicated agent-browser profile (preferred, zero friction).** If `~/.agent-browser-xhs` exists (verify with `test -d ~/.agent-browser-xhs`), use it for every call. No Chrome conflicts because it's an isolated profile dir, not your real Chrome profile:
```bash
agent-browser --profile ~/.agent-browser-xhs --session xhs open <url>
```
If it doesn't exist, walk the user through the one-time setup in the Prerequisites section before continuing. This is the path to gently push users toward — it eliminates the recurring "quit Chrome" tax.

**Option B — Auto-connect (use the user's real Chrome, non-disruptive).** Only if they explicitly prefer this. Requires their Chrome to have been launched with `--remote-debugging-port=9222`:
```bash
agent-browser --auto-connect get url   # verifies the connection works
agent-browser --auto-connect <command> # use auto-connect for subsequent calls
```

**Option C — `--profile Default` (last resort).** Riding the user's real Chrome profile. Requires Chrome fully quit (profile lock). Only use if A and B aren't available and the user is OK quitting Chrome:
```bash
agent-browser profiles                            # list profiles
agent-browser --profile Default --headed --session xhs open https://www.xiaohongshu.com/
```

Don't try cookies-from-browser via plain curl — XHS bot detection (`x-s` / `x-t` signed headers) makes static-cookie requests flaky. You need a real Chrome session for the page's JS to compute valid signed headers.

### 3a. Replay → fetch via `clip_detail_web` (no auth)

The replay API is public read, so spin up a **fresh, sessionless** agent-browser — no `~/.agent-browser-xhs` profile, no `--profile` flag, no `--auto-connect`. The browser is needed only so the page's JS can compute valid signed headers (`x-s`/`x-t`) for the request; the session itself doesn't need cookies.

```bash
# 1. Open the replay page in a vanilla session (use any session name)
agent-browser --session xhs-replay open '<the replay URL the user pasted>'

# 2. Evaluate the API call on the xiaohongshu.com origin
agent-browser --session xhs-replay eval --stdin <<'EVALEOF'
fetch('/api/sns/v1/live/dynamic/clip_detail_web?clip_id=<CLIP_ID>&host_id=<HOST_ID>')
  .then(r => r.json())
  .then(j => JSON.stringify(j))
EVALEOF
```

Substitute the real `clip_id` and `host_id` (parsed in step 1). Step 2 must run **after** step 1 because the eval uses a relative URL and needs to be on the xiaohongshu.com origin. The response shape:

```json
{
  "result": 0,
  "success": true,
  "data": {
    "clip_info": {
      "video_url": "https://xhslive-video.xhscdn.com/stream/.../*.m3u8",
      "duration": "11216",
      "room_id": "...",
      "cover_url": "...",
      "pv": "...",
      "room_start_time": "..."
    },
    "host_info": { "nickname": "...", "avatar": "..." }
  }
}
```

What to capture: `video_url` (m3u8), `duration` (seconds, despite being a string), `host_info.nickname` (for naming). If `result` is non-zero or `success` is false, the session isn't authenticated — back to step 2.

Skip to step 4.

### 3b. Live → harvest URL from page network traffic

For live streams the relevant API is on a different host (`live-room.xiaohongshu.com`) and **requires per-request signed headers** (`x-s` / `x-t`) that only the page's own JS generates. A direct `fetch(...)` from devtools eval returns `{code: -1, success: false}`. The trick: **let the page make the call itself, then scoop the playback URL out of the network log**.

```bash
# 1. Navigate to the live URL with the authenticated session
agent-browser --session xhs open 'https://www.xiaohongshu.com/livestream/<ROOM_ID>?source=web_live'

# 2. Wait briefly — the page fires its room-info call within a few seconds
agent-browser --session xhs wait 4000

# 3. Dump the network log and grep for the playback URL
agent-browser --session xhs network requests --json > /tmp/xhs-live-net.json
python3 -c "
import json
with open('/tmp/xhs-live-net.json') as f:
    data = json.load(f)
for r in data['data']['requests']:
    url = r.get('url','')
    if 'live-source-play.xhscdn.com' in url or url.endswith('.flv') or '.m3u8' in url:
        print(r.get('method'), r.get('status'), url)
"
```

The playback URL looks like:
```
https://live-source-play.xhscdn.com/live/<ROOM_ID>_<variant>.flv?userId=<some-id>
```

Where `<variant>` is something like `hcv5401` (XHS's chosen quality tag for desktop web). You may also see HLS variants on the same host with `.m3u8` — capture whichever appears.

If you also need the host nickname / room title for naming, grab it from the `current_room_info` response payload:
```bash
agent-browser --session xhs network requests --json | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data['data']['requests']:
    if 'current_room_info' in r.get('url','') and r.get('method') == 'GET':
        body = r.get('responseBody') or ''
        if body: print(body[:2000])
"
```

**Security-verification overlay** (`Scan with logged-in REDNote APP for account security`) often appears on the live page **after** the room-info call has already fired. You can ignore the overlay — the playback URL is already in the network log. If for some reason it never fires (very rare), the user does need to scan the QR with their mobile app to proceed.

### 3c. Note post → mine `__INITIAL_STATE__` for the quality ladder

Every note page embeds the full video manifest in `window.__INITIAL_STATE__` in the HTML — no playback or network-harvesting needed. Path: `note.noteDetailMap[{note_id}].note.video.media.stream`, an object keyed by codec (`h264` / `h265` / `av1`), each an array of rungs with `width`, `height`, `streamType`, `size` (bytes), `duration` (ms), `masterUrl`, `backupUrls`.

**Anonymous first — plain curl is enough** (no browser, no login):

```bash
curl -sL -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" \
  '<the note URL with xsec_token>' -o /tmp/xhs_note.html

python3 - <<'EOF'
import re, json
html = open('/tmp/xhs_note.html', encoding='utf-8', errors='replace').read()
m = re.search(r'window\.__INITIAL_STATE__=(\{.*?\})</script>', html, re.S)
raw = re.sub(r'(?<=[:\[,])undefined(?=[,\}\]])', 'null', m.group(1))  # SSR state is not strict JSON
state = json.loads(raw)
for nid, entry in (state.get('note', {}).get('noteDetailMap') or {}).items():
    media = ((entry or {}).get('note') or {}).get('video', {}).get('media') or {}
    print('title:', (entry.get('note') or {}).get('title'), '| duration:', media.get('video', {}).get('duration'), 's')
    for codec, rungs in (media.get('stream') or {}).items():
        for st in rungs or []:
            print(f"  {codec} {st.get('width')}x{st.get('height')} type={st.get('streamType')} "
                  f"size={round((st.get('size') or 0)/1e6)}MB url={st.get('masterUrl')}")
EOF
```

Two parsing gotchas: the state contains bare `undefined` tokens (hence the regex → `null`), and `qualityType` is always the meaningless string `"HD"` — judge quality by `width`/`height` only.

**If the ladder is capped (e.g. only 720p) but the user can watch higher logged in** — the anonymous SSR state only includes the low rungs. Re-extract from a logged-in browser instead:

```bash
agent-browser close --all   # IMPORTANT: a running daemon ignores --profile on later calls
agent-browser --profile ~/.agent-browser-xhs --headed --session xhs open '<note URL>'
agent-browser --session xhs wait 6000
agent-browser --session xhs eval --stdin <<'EVALEOF'
(() => {
  const map = window.__INITIAL_STATE__?.note?.noteDetailMap || {};
  const out = [];
  for (const [id, entry] of Object.entries(map)) {
    const v = entry?.note?.video?.media;
    if (!v) continue;
    const streams = [];
    for (const [codec, arr] of Object.entries(v.stream || {}))
      for (const st of arr || [])
        streams.push({codec, width: st.width, height: st.height, streamType: st.streamType,
                      sizeMB: Math.round((st.size||0)/1e6), masterUrl: st.masterUrl, backupUrls: st.backupUrls});
    out.push({id, title: entry?.note?.title, duration: v?.video?.duration, streams});
  }
  return JSON.stringify(out);
})()
EVALEOF
```

Stream URL anatomy: `http://sns-video-<host>-m.xhscdn.com/stream/{a}/{biz}/{streamType}/{fileId}_{streamType}.mp4?sign=...&t=...` — CDN-signed, valid for hours. `masterUrl` plus 3–4 `backupUrls` on different CDN hosts; if one host is slow or throttled, retry the same file on a backup host. Prefer `https` upgrade if `http` gives trouble (both work).

For small notes (a few hundred MB) you can skip all this: `yt-dlp '<note URL>'` works directly — the XiaoHongShu extractor handles notes with `xsec_token`, but only sees the anonymous ladder.

Skip to step 4.

### 3d. Event/match page → find the linked video notes

Campaign pages like `/worldcup26/match/{match_id}` are SSR apps with no direct video — yt-dlp's generic extractor fails on them. The page state at `worldCupMatch` lists the associated video notes. Plain curl works (anonymous is fine for listing):

```bash
curl -sL -A "Mozilla/5.0 ... Chrome/126.0.0.0 Safari/537.36" '<event page URL>' -o /tmp/xhs_event.html

python3 - <<'EOF'
import re, json
html = open('/tmp/xhs_event.html', encoding='utf-8', errors='replace').read()
m = re.search(r'window\.__INITIAL_STATE__=(\{.*?\})</script>', html, re.S)
raw = re.sub(r'(?<=[:\[,])undefined(?=[,\}\]])', 'null', m.group(1))
wc = json.loads(raw).get('worldCupMatch') or {}
mi = wc.get('matchInfo') or {}
for section in ('reportList', 'highList'):
    for item in mi.get(section) or []:
        if item.get('type') == 'video':
            print(item.get('noteId'), '|', item.get('title'), '|', item.get('xsecToken'))
print('replayVideoInfo:', wc.get('replayVideoInfo'))  # often null anonymously — not proof no replay exists
EOF
```

- `reportList` — recap/highlight videos (全场集锦 = full-match highlights, usually the best single clip).
- `highList` — moment-by-moment clips (goal-by-goal).
- `replayVideoInfo: null` anonymously does **not** mean no replay — full replays are usually posted as regular notes (search the page/reportList for 全场回放 = full replay), and event APIs may return more when logged in.

Build note URLs as `https://www.xiaohongshu.com/explore/{noteId}?xsec_token={xsecToken}` and continue at **step 3c** for each one the user wants. Note: tokens from the event page can be short-lived; if a note URL 403s/404s, re-fetch the event page for fresh tokens, or ask the user to paste the note's own share link.

### 4. Probe and confirm

**Note post:** the manifest already told you everything — `duration`, exact `size`, resolution, codec. No probing needed; just present the ladder to the user and confirm which rung to pull (don't default to the biggest: 4K h264 can be 2–3× the h265 size for the same pixels; on a Mac both play natively). If the user picked by resolution, also mention codec/size tradeoff in one line.

**Livestream replay:** probe the stream to show real numbers before kicking off a multi-GB download:

```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 \
  -headers $'Referer: https://www.xiaohongshu.com/\r\n' \
  '<VIDEO_URL>'
```

Report duration, resolution (use a fuller `ffprobe -show_streams` if helpful), and rough size estimate (XHS replays are typically ~2 Mbps for 1080p portrait → ~15 MB/min). For anything >30 min, default to running the download in the background.

**Live:** skip `ffprobe -show_format` — a live FLV has no fixed duration, ffprobe will hang. Instead, do a quick HEAD probe to confirm the URL is alive:

```bash
curl -sI --max-time 5 -H 'Referer: https://www.xiaohongshu.com/' '<VIDEO_URL>'
```

Look for `200 OK` and `Content-Type: video/x-flv` (or `application/vnd.apple.mpegurl` for m3u8 variants). Anything else (403, 404, timeout) means the stream is offline or the URL has rotated — re-run step 3b.

### 5a. Livestream replay → parallel download with yt-dlp (preferred)

Use `yt-dlp` with parallel fragment workers. For a 3-hour replay this finishes in ~3 minutes instead of ~30:

```bash
mkdir -p ~/Downloads
cd ~/Downloads && yt-dlp \
  -N 16 \
  --hls-prefer-native \
  --add-header 'Referer:https://www.xiaohongshu.com/' \
  --merge-output-format mp4 \
  -o '<filename>.%(ext)s' \
  '<VIDEO_URL>'
```

What the flags do:
- `-N 16` — 16 parallel HLS fragment downloads. This is the speed win. Going above 16 rarely helps and may trigger rate-limiting.
- `--hls-prefer-native` — use yt-dlp's parallel downloader instead of delegating to ffmpeg's sequential one.
- `--add-header` — required Referer (XHS CDN returns 403 without it).
- `--merge-output-format mp4` — yt-dlp runs a final ffmpeg fixup pass that produces a clean MP4 (no DTS warnings reach the user).
- `-o '<filename>.%(ext)s'` — let yt-dlp pick the extension so the fixup step can rename if needed.

**Filename suggestion:** `<ascii-sanitized-nickname>-replay-<room_id>.mp4`. Strip emoji, non-ASCII, and shell-unsafe chars from the nickname (replace spaces with `-`). If the nickname is entirely non-ASCII, fall back to `xhs-replay-<room_id>.mp4` — ASCII names avoid quoting headaches and stay portable across drives. Date-based names like `<show-slug>-<YYYY-MM-DD>.mp4` are also fine if the user prefers.

For long replays, run in the background and tell the user how to monitor:
```bash
# in agent: run_in_background=true, redirect to a log file
... > /tmp/xhs-ytdlp-<room_id>.log 2>&1

# user can watch:
tail -f /tmp/xhs-ytdlp-<room_id>.log
ls -lh ~/Downloads/<filename>.mp4
```

### 5b. Live → record while broadcasting

Live FLV is a continuous feed — there are no segments to parallelize, so `-N 16` doesn't help. Just point yt-dlp (or ffmpeg) at the URL and let it run; stop with Ctrl+C (or kill the background task) when the user has captured enough. The output starts at "now" — anything that aired before you started is lost.

**yt-dlp (recommended — handles re-connect on brief network hiccups):**
```bash
mkdir -p ~/Downloads
yt-dlp \
  --add-header 'Referer:https://www.xiaohongshu.com/' \
  --no-part \
  -o '~/Downloads/<filename>-%(epoch)s.flv' \
  '<FLV_URL>'
```

**ffmpeg (use if you want to remux to MP4 on the fly):**
```bash
ffmpeg -headers $'Referer: https://www.xiaohongshu.com/\r\n' \
  -i '<FLV_URL>' \
  -c copy \
  ~/Downloads/<filename>.mp4
# Ctrl+C produces a playable file because -c copy doesn't need a clean trailer.
```

**Filename suggestion:** `<ascii-nickname>-live-<YYYYMMDD-HHMM>.flv` (or `.mp4` if remuxing). Include the date because the room can air multiple separate sessions over time.

Run in the background — live recordings can run for hours. Watch with:
```bash
ls -lh ~/Downloads/<filename>*  # growing means it's still alive
```

If the file stops growing before the user expects, the host went offline (or the URL rotated). Re-run step 3b to get a fresh URL.

### 5c. ffmpeg replay fallback

Only reach for this if yt-dlp errors out on a replay (e.g., a fragment URL signature scheme changes and yt-dlp's extractor can't follow). Single-threaded so much slower:

```bash
ffmpeg -hide_banner -loglevel warning -stats \
  -headers $'Referer: https://www.xiaohongshu.com/\r\n' \
  -i '<VIDEO_URL>' \
  -c copy -bsf:a aac_adtstoasc \
  -y ~/Downloads/<filename>.mp4
```

### 5d. Hand off the URL (no download)

If the user wants to use their own tool (IDM, Free Download Manager, VLC, Folx, OBS, etc.), give them the raw URL plus the required Referer header. xhscdn.com returns 403 without it.
- VLC: `Media → Open Network Stream`, paste URL. Set Referer via `Preferences → All → Input/Codecs → Access modules → HTTP → HTTP referer`.
- Most desktop players accept FLV directly.

### 5e. Note post → aria2-accelerated MP4 download

Note streams are single plain MP4s — there are no HLS fragments, so `-N` does nothing. For anything over ~500 MB, parallelize by ranges with aria2c through yt-dlp:

```bash
mkdir -p ~/Downloads
cd ~/Downloads && yt-dlp \
  --downloader aria2c \
  --downloader-args "aria2c:-x 16 -s 16 -k 4M --file-allocation=none" \
  --add-header 'Referer:https://www.xiaohongshu.com/' \
  -o '<filename>.%(ext)s' \
  '<MASTER_OR_BACKUP_URL>'
```

- `-x 16 -s 16 -k 4M` — 16 range connections, 4 MB minimum split. The CDN throttles per-IP after an initial burst, so expect an impressive first minute then a drop to single-digit MB/s; that's normal, don't "fix" it.
- `--file-allocation=none` — avoids preallocating the full file (see the preallocation gotcha below).
- **Resume after a drop:** the CDN sometimes kills all connections mid-file ("Got EOF from the server", aria2 exit 1). Just re-run the same command with `--continue=true` added to the aria2 args — the `.aria2` control file resumes where it left off. Note `--continue=true` (equals sign): `-c true` is parsed as an extra URI ("Unrecognized URI: true"). If the same host keeps dropping, switch to a `backupUrls` host — resume still works because the control file tracks byte ranges, not the URI.
- Referer is mandatory, same as everywhere else.
- Small notes (<200 MB): plain `yt-dlp '<note URL>'` is simpler and fast enough.
- If the CDN stalls or errors mid-file, retry the same `{fileId}_{streamType}.mp4` path on one of the `backupUrls` hosts — the `sign`/`t` query is shared across them.

**Filename suggestion:** `<ascii-title-slug>-<quality>.mp4`, e.g. `france-4-6-england-full-replay-4k.mp4`. Include the quality tag — these notes exist at multiple resolutions and the user may pull more than one.

### 6. Cleanup

After the download starts (or finishes), close the browser session to free resources:
```bash
agent-browser --session xhs close
```
Auto-connect users: don't close — that would shut down the user's real Chrome.

## Gotchas

- **`--profile` silently ignored if a daemon is already running.** agent-browser prints `--profile ignored: daemon already running` and uses the wrong (unauthenticated) browser. Always `agent-browser close --all` before launching with a different profile or after any failed session.
- **IP-risk block (error 300012).** XHS risk control can redirect any session — profiled or anonymous — to `/website-login/error?...error_code=300012&error_msg=IP at risk`, sometimes after several rapid automated requests. Plain curl usually still works at the same moment (different fingerprint), so prefer curl-first extraction (steps 3c/3d) and keep browser usage minimal. If the browser gets blocked, wait a bit and retry headed — it often clears.
- **Anonymous note pages show a truncated quality ladder.** The SSR state may only include low rungs (e.g. 720p) even when 1080p/1440p/4K exist. Before telling the user "no 4K," re-extract from a logged-in session (step 3c). Conversely, if the anonymous ladder is complete, no login is needed at all.
- **`qualityType: "HD"` is meaningless.** Every rung says HD, including 4K. Use `width`/`height`.
- **Aria2 preallocation fakes progress.** On APFS the `.part` file can show the full multi-GB size in `ls`/`du` within seconds while aria2 has only fetched a few percent. Trust aria2's own `[#... XMiB/YGiB(Z%) ...]` counter in the log, not the file size. `--file-allocation=none` reduces but may not eliminate this.
- **CDN throttles after an initial burst.** Multi-hundred-MB/s for the first seconds, then a drop to ~5 MB/s per IP. 16 connections don't fix it — it's per-IP shaping. Set user expectations for multi-GB 4K files (~20–30 min).
- **`__INITIAL_STATE__` is not strict JSON.** It contains bare `undefined` tokens — `json.loads` fails at the first one. Regex-replace `(?<=[:\[,])undefined(?=[,\}\]])` with `null` before parsing.
- **Profile lock.** `--profile Default` fails with a cryptic CDP error if Chrome is running with that profile. Always check first — if `pgrep -x "Google Chrome"` returns a PID and the user picked profile-based auth, have them Cmd+Q first.
- **Referer is mandatory.** xhscdn.com returns 403 without `Referer: https://www.xiaohongshu.com/`. Pass it to `ffprobe`, `ffmpeg`, `yt-dlp`, and aria2c.
- **Non-monotonic DTS warnings.** Harmless. XHS occasionally has minor timestamp glitches in source segments; ffmpeg auto-corrects. Don't surface these as errors to the user.
- **Duration string.** The replay API returns `"duration": "11218"` as a string in **seconds** (not ms). Note manifests are the opposite: `stream.h264[].duration` is in **ms** while `video.duration` is in **seconds**. Check which field you're reading.
- **No baked-in expiry, but URLs are CDN-signed.** The m3u8 / FLV / MP4 URL is typically valid for hours, not days. If a user comes back tomorrow with the same URL, re-run from step 3 instead of trying to reuse an old `video_url`/`masterUrl`.
- **Live URL only valid while broadcasting.** Once the host ends the stream, the FLV URL 404s. If the user wants the full archive, wait for it to become a replay and use the replay path instead. Conversely, if the user already knows the broadcast is past and pastes a `/livestream/` URL, the page may auto-redirect to the replay URL — just follow the redirect.
- **Live API requires per-request signed headers.** Don't try to call `current_room_info` directly via `agent-browser eval` — the live-room.xiaohongshu.com API checks `x-s` / `x-t` headers that only the page's own JS generates. The proven pattern is to let the page make the call and harvest the URL from the network log (step 3b).
- **Security-verification QR overlay on live pages.** Often appears *after* the page has already fetched the playback URL — ignore it. If it appears *before* the network call happens (rare), the user has to scan it with their REDNote mobile app to proceed; there's no clean web bypass.
- **App-only content.** Some replays are gated behind the mobile app and return `result != 0` even when authenticated. There's no clean web workaround; tell the user honestly.

## Clarifying questions to ask up front

Only ask what you actually need. Skip questions the user has already answered. For replays, skip auth questions entirely.

1. **Auth path** (live and quality-gated notes — anonymous replays and note listing don't need this): if `~/.agent-browser-xhs` exists, just use it silently. Otherwise walk through the one-time setup. Only fall back to auto-connect / `--profile Default` if the user explicitly prefers their main Chrome.
2. **Which profile / which account** (only if the user has multiple XHS accounts and you need to pick one).
3. **Which quality rung** (note posts only): show the ladder with sizes and let the user pick; mention the h264-vs-h265 size tradeoff for the same resolution.
4. **Output path / filename** (only if the default `~/Downloads/<nickname>-replay-<room_id>.mp4`, `<title-slug>-<quality>.mp4`, or `<nickname>-live-<timestamp>.flv` doesn't suit them).
5. **Foreground vs background** (only for replays >30 min or note downloads >2 GB — short ones finish in a minute). For live, always background — the user controls when to stop with Ctrl+C / kill.
6. **For live recordings: when to stop.** The download keeps running until the host ends the stream or the user kills it. Confirm the user's plan (e.g. "stop after 1 hour", "until the host ends it") so you can set a wakeup or just hand back the kill instructions.

## Sanity checks before claiming success

**Note post:**
- Final file size should match the manifest's `size` field almost exactly (it's the exact byte count of the source file) — the strongest possible check.
- Verify the yt-dlp/aria2 process exited 0. If you see `.part` / `.part.aria2` files, it's not done.
- `ffprobe` the output: duration ≈ `video.duration` (seconds) and resolution matches the rung the user picked.
- Mid-download, ignore `ls`/`du` on the `.part` file (preallocation — see gotchas); read aria2's counter instead.

**Livestream replay:**
- `ls -lh` the output file — size should match your earlier estimate within ±30%.
- For background downloads, verify the yt-dlp / ffmpeg process exited 0 (not just that the file exists — a partial file exists too). For yt-dlp, look for `100% of ... in HH:MM:SS at ...` and the `[FixupM3u8]` line. For ffmpeg, the final `frame=... time=HH:MM:SS` should ≈ the reported duration.
- If the user wants stronger verification, `ffprobe` the output file's duration and compare to the API's `duration` field.

**Live:**
- File size keeps growing → still recording. File size flat → host ended the stream or URL rotated.
- `ffprobe` the partial FLV (it's playable mid-recording — just won't have a fixed duration in metadata).
- Don't claim a recording is "complete" — only the user knows when they want to stop. Report status as "recording, N MB captured" instead.
