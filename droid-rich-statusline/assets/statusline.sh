#!/bin/bash
# Droid statusline — macOS / Linux.
#
# One line, same shape as the Claude Code rich statusline:
#
#   📊 Context: ▓░░░░░░░░░ 9% (36k/400k) │ 5h: ██▓░░░░░░░ 28% (2h32m) │
#   7d: ▓░░░░░░░░░ 6% (2d10h) │ Month: ▓░░░░░░░░░ 5% (25d4h) │ 📁 web-business │ 116.1 tok/s
#
# Context and the working directory come from the JSON Droid pipes in on every
# tick. The Factory plan numbers do not — they need the billing limits API, so a
# detached worker (fetch-usage.mjs) refreshes a cache file and this script only
# reads it, spawning a refresh when it goes stale.
#
# The tok/s segment (last on the line) is the speed of the latest model call. It
# needs the two session files Droid points at in the payload, and keeps no state.
#
# Needs: bash, jq, node (node only for the usage segments — without it the line
# still renders context and directory).

set -eu

DIR="${FACTORY_HOME:-${HOME}/.factory}"
CACHE="${DIR}/statusline-usage.json"
LOCK="${DIR}/statusline-usage.lock"
REFRESH="${DIR}/statusline-fetch-usage.mjs"
LOG="${DIR}/statusline-usage.log"

FRESH=60      # cache younger than this: render as-is, no refresh
USABLE=900    # cache older than this: drop the usage segments
LOCK_MAX=30   # ignore a lock older than this (a refresh that died)

input=$(cat)
now=$(date +%s)

# --- dependencies -----------------------------------------------------------
# jq is required for everything; node only for the usage numbers. Missing node
# degrades quietly to context + directory, so a bare install still works.
JQ=$(command -v jq 2>/dev/null || true)
if [ -z "$JQ" ]; then
  printf 'statusline: jq not found (brew install jq)'
  exit 0
fi

NODE=$(command -v node 2>/dev/null || true)
if [ -z "$NODE" ]; then
  for candidate in /opt/homebrew/bin/node /usr/local/bin/node /usr/bin/node; do
    [ -x "$candidate" ] && NODE="$candidate" && break
  done
fi

# --- input fields -----------------------------------------------------------
# Droid's context block is the compaction meter: percentage plus the token
# counts after a fixed system-prompt baseline is subtracted.
fields=$(printf '%s' "$input" | "$JQ" -r '[
  (.cwd // .workspace.current_dir // "."),
  (.context.percentage // ""),
  (.context.adjusted_tokens // ""),
  (.context.adjusted_limit // ""),
  (.transcript_path // ""),
  (.session_settings_path // "")
] | @tsv' 2>/dev/null || printf '.\t\t\t\t\t')

cwd=$(printf '%s' "$fields" | cut -f1)
ctx_pct=$(printf '%s' "$fields" | cut -f2 | tr -d '%')
ctx_used=$(printf '%s' "$fields" | cut -f3)
ctx_total=$(printf '%s' "$fields" | cut -f4)
transcript=$(printf '%s' "$fields" | cut -f5)
session_settings=$(printf '%s' "$fields" | cut -f6)

# No directory in the payload: fall back to where this process actually is,
# so the segment shows a real folder name rather than a bare ".". PowerShell
# resolves "." the same way, which keeps the two platforms in step.
case "$cwd" in ""|".") cwd="$PWD" ;; esac

# --- rendering helpers ------------------------------------------------------

# 10-cell bar with half-cell ▓ resolution. Color is a smooth truecolor gradient
# from green (0%) → yellow (50%) → red (100%), so the bar's hue itself encodes
# severity — you can read the line peripherally without parsing the numbers.
render_bar() {
  awk -v p="$1" 'BEGIN {
    cells=10;
    if (p < 0) p=0; if (p > 100) p=100;
    full=int(p/10);
    rem=p - full*10;
    half=(rem >= 5 && full < cells) ? 1 : 0;
    if (p <= 50) { r=int(p/50*255+0.5); g=255 }
    else         { r=255; g=int((100-p)/50*255+0.5) }
    out="";
    for (i=0; i<full; i++) out=out "█";
    if (half) { out=out "▓"; full++ }
    for (i=full; i<cells; i++) out=out "░";
    printf "\033[38;2;%d;%d;%dm%s\033[0m", r, g, 0, out;
  }'
}

# Coarsest useful unit, so a month-long window reads "25d" not "600h".
fmt_countdown() {
  local secs=$1
  if [ "$secs" -le 0 ]; then echo "now"; return; fi
  local d=$(( secs / 86400 ))
  local h=$(( (secs % 86400) / 3600 ))
  local m=$(( (secs % 3600) / 60 ))
  if [ "$d" -ge 1 ]; then
    if [ "$h" -gt 0 ]; then echo "${d}d${h}h"; else echo "${d}d"; fi
  elif [ "$h" -ge 1 ]; then
    if [ "$m" -gt 0 ]; then echo "${h}h${m}m"; else echo "${h}h"; fi
  else
    echo "${m}m"
  fi
}

fmt_tokens() {
  awk -v n="$1" 'BEGIN {
    if (n >= 1000000) printf "%.1fM", n/1000000
    else if (n >= 1000) printf "%.0fk", n/1000
    else printf "%d", n
  }'
}

# Rounded whole percent, but never "0%" for a real, tiny amount of usage.
fmt_percent() {
  awk -v p="$1" 'BEGIN {
    if (p > 0 && p < 0.5) printf "<1"
    else printf "%.0f", p
  }'
}

line=""
append() {
  if [ -z "$line" ]; then line="$1"; else line="${line} │ $1"; fi
}

# --- context window ---------------------------------------------------------
if [ -n "$ctx_pct" ]; then
  ctx_int=$(awk -v p="$ctx_pct" 'BEGIN { printf "%.0f", p }')
  ctx_label=$(fmt_percent "$ctx_pct")
  if [ -n "$ctx_used" ] && [ -n "$ctx_total" ]; then
    append "📊 Context: $(render_bar "$ctx_int") ${ctx_label}% ($(fmt_tokens "$ctx_used")/$(fmt_tokens "$ctx_total"))"
  else
    append "📊 Context: $(render_bar "$ctx_int") ${ctx_label}%"
  fi
fi

# --- Factory plan usage (from the cache) ------------------------------------
cache_age=-1
if [ -s "$CACHE" ]; then
  fetched_at=$("$JQ" -r '.fetched_at // 0' "$CACHE" 2>/dev/null || echo 0)
  cache_age=$(( now - fetched_at ))
fi

if [ "$cache_age" -ge 0 ] && [ "$cache_age" -lt "$USABLE" ]; then
  # Older than FRESH but still usable: mark the number so stale data is obvious.
  suffix=""
  [ "$cache_age" -ge "$FRESH" ] && suffix="~"

  for window in fiveHour:5h weekly:7d monthly:Month; do
    key="${window%%:*}"
    label="${window##*:}"
    pct=$("$JQ" -r --arg k "$key" '.[$k].usedPercent // empty' "$CACHE" 2>/dev/null || true)
    [ -n "$pct" ] || continue
    end=$("$JQ" -r --arg k "$key" '.[$k].windowEnd // empty' "$CACHE" 2>/dev/null || true)
    pct_int=$(awk -v p="$pct" 'BEGIN { printf "%.0f", p }')
    pct_label=$(fmt_percent "$pct")
    if [ -n "$end" ]; then
      append "${label}: $(render_bar "$pct_int") ${pct_label}%${suffix} ($(fmt_countdown $(( ${end%.*} - now ))))"
    else
      append "${label}: $(render_bar "$pct_int") ${pct_label}%${suffix}"
    fi
  done
fi

# --- working directory ------------------------------------------------------
append "📁 $(basename "$cwd")"

# --- generation speed of the latest model call ------------------------------
# Droid's payload has no timing or output-token fields, so this reads the two
# session files it points at:
#
#   tokens  = lastCallTokenUsage.outputTokens in the session settings file
#   seconds = timestamp of the newest assistant message in the transcript minus
#             the timestamp of the message right before it (the prompt or tool
#             result that call was answering)
#
# Only the last few transcript lines are read, so a multi-MB transcript costs
# nothing. It is an end-to-end figure (includes time-to-first-token and network),
# so it reads below raw decode speed, most visibly on short replies. Calls under
# 30 tokens or 0.5 s are too noisy to be worth showing, so the segment drops out.
# No state is kept: the same files always give the same number.
speed=""
if [ -n "$transcript" ] && [ -n "$session_settings" ] && [ -r "$transcript" ] && [ -r "$session_settings" ]; then
  out_tok=$("$JQ" -r '.lastCallTokenUsage.outputTokens // empty' "$session_settings" 2>/dev/null || true)
  span=$(tail -n 24 "$transcript" 2>/dev/null | "$JQ" -Rrn '
    def secs: ((.[0:19] + "Z") | fromdateiso8601) + ((.[19:23] | tonumber?) // 0);
    [inputs | fromjson? | select(.type == "message" and .timestamp != null)] as $m
    | ([range(1; $m | length) | select($m[.].message.role == "assistant")] | last) as $i
    | if $i == null then empty else ($m[$i].timestamp | secs) - ($m[$i - 1].timestamp | secs) end
  ' 2>/dev/null || true)
  case "$out_tok" in ''|*[!0-9]*) out_tok="" ;; esac
  if [ -n "$out_tok" ] && [ -n "$span" ]; then
    speed=$(awk -v t="$out_tok" -v d="$span" 'BEGIN {
      if (t >= 30 && d >= 0.5 && t / d <= 2000) printf "%.1f", t / d
    }')
  fi
fi
[ -n "$speed" ] && append "${speed} tok/s"

# --- refresh the cache in the background when it goes stale -----------------
if [ -n "$NODE" ] && [ -f "$REFRESH" ] && { [ "$cache_age" -lt 0 ] || [ "$cache_age" -ge "$FRESH" ]; }; then
  lock_age=9999
  if [ -f "$LOCK" ]; then
    lock_mtime=$(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK" 2>/dev/null || echo 0)
    lock_age=$(( now - lock_mtime ))
  fi
  if [ "$lock_age" -ge "$LOCK_MAX" ]; then
    : > "$LOCK" 2>/dev/null || true
    nohup "$NODE" "$REFRESH" >> "$LOG" 2>&1 &
    disown 2>/dev/null || true
  fi
fi

printf '%s' "$line"
