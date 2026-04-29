#!/bin/bash
# Claude Code statusline.
# Reads JSON from stdin, prints one line:
#   📊 Context: 42% (85k/200k) | 5h: 23% (4h12m) | 7d: 41% (3d) | Session: 2h | Model: Opus 4.7 | Branch: main

set -eu

input=$(cat)

model=$(printf '%s' "$input" | jq -r '.model.display_name // .model.id // "?"')
pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0')
ctx_size=$(printf '%s' "$input" | jq -r '.context_window.context_window_size // 200000')
duration_ms=$(printf '%s' "$input" | jq -r '.cost.total_duration_ms // 0')
cwd=$(printf '%s' "$input" | jq -r '.workspace.current_dir // "."')

five_pct=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
five_reset=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
seven_pct=$(printf '%s' "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
seven_reset=$(printf '%s' "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')

now=$(date +%s)

pct_int=$(awk -v p="$pct" 'BEGIN { printf "%.0f", p }')
tokens_used=$(awk -v p="$pct" -v s="$ctx_size" 'BEGIN { printf "%d", p * s / 100 }')

fmt_k() {
  awk -v n="$1" 'BEGIN {
    if (n >= 1000) printf "%.0fk", n/1000
    else printf "%d", n
  }'
}
used_k=$(fmt_k "$tokens_used")
total_k=$(fmt_k "$ctx_size")

# Format a duration in seconds as "Xd", "XhYm", or "Xm" — picks the coarsest
# useful unit so a 4-day countdown shows "4d" not "96h".
fmt_countdown() {
  local secs=$1
  if [ "$secs" -le 0 ]; then
    echo "now"
    return
  fi
  local d=$(( secs / 86400 ))
  local h=$(( (secs % 86400) / 3600 ))
  local m=$(( (secs % 3600) / 60 ))
  if [ "$d" -ge 1 ]; then
    if [ "$h" -gt 0 ]; then
      echo "${d}d${h}h"
    else
      echo "${d}d"
    fi
  elif [ "$h" -ge 1 ]; then
    if [ "$m" -gt 0 ]; then
      echo "${h}h${m}m"
    else
      echo "${h}h"
    fi
  else
    echo "${m}m"
  fi
}

# Session duration (already-elapsed time, not a countdown).
mins=$(( duration_ms / 60000 ))
if [ "$mins" -lt 60 ]; then
  session="${mins}m"
else
  hours=$(( mins / 60 ))
  rem=$(( mins % 60 ))
  if [ "$rem" -eq 0 ]; then
    session="${hours}h"
  else
    session="${hours}h${rem}m"
  fi
fi

branch=""
if git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
fi

line="📊 Context: ${pct_int}% (${used_k}/${total_k})"

# 5-hour rate limit. Skip silently if Claude Code didn't supply it.
if [ -n "${five_pct:-}" ]; then
  five_int=$(awk -v p="$five_pct" 'BEGIN { printf "%.0f", p }')
  if [ -n "${five_reset:-}" ]; then
    five_in=$(fmt_countdown $(( five_reset - now )))
    line="${line} | 5h: ${five_int}% (${five_in})"
  else
    line="${line} | 5h: ${five_int}%"
  fi
fi

# 7-day rate limit.
if [ -n "${seven_pct:-}" ]; then
  seven_int=$(awk -v p="$seven_pct" 'BEGIN { printf "%.0f", p }')
  if [ -n "${seven_reset:-}" ]; then
    seven_in=$(fmt_countdown $(( seven_reset - now )))
    line="${line} | 7d: ${seven_int}% (${seven_in})"
  else
    line="${line} | 7d: ${seven_int}%"
  fi
fi

line="${line} | Session: ${session} | Model: ${model}"

if [ -n "$branch" ]; then
  line="${line} | Branch: ${branch}"
fi

printf '%s' "$line"
