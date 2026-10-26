#!/bin/bash
# Claude Code statusline — bash / macOS / Linux.
# Reads JSON from stdin, prints one colored line:
#   📊 Context: █▌░░░ 35% (350k/1000k) │ 5h: █░░░░ 28% (2h32m) │ 7d: ███░░ 66% (2d10h) │ Model: Opus 4.7 (high) │ Dir: ~/Developer/my-project │ Branch: main │ 116.1 tok/s
# Bar color is a smooth truecolor gradient: green (0%) → yellow (50%) → red (100%).
# Requires a terminal with 24-bit color (any modern macOS/Linux terminal qualifies).
#
# One small piece of state: the generation-speed segment (tok/s, last segment
# of the line) keeps a tiny per-session file in ~/.claude/statusline-speed/ so
# it can diff cost.total_api_duration_ms between ticks. It is idempotent —
# re-rendering the same snapshot never changes the number.

set -eu

input=$(cat)

model=$(printf '%s' "$input" | jq -r '.model.display_name // .model.id // "?"')
pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0')
ctx_size=$(printf '%s' "$input" | jq -r '.context_window.context_window_size // 200000')
effort=$(printf '%s' "$input" | jq -r '.effort.level // empty')
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

# Render a 5-cell bar with half-cell ▌ resolution. Color is a smooth truecolor
# gradient from green (0%) → yellow (50%) → red (100%); the empty part is a flat
# dark-gray track, and a half cell is the bar color on a track-colored background.
render_bar() {
  local pct=$1
  awk -v p="$pct" 'BEGIN {
    cells=5;
    full=int(p/20);
    rem=p - full*20;
    half=(rem >= 10 && full < cells) ? 1 : 0;
    if (p < 0) p=0; if (p > 100) p=100;
    if (p <= 50) { r=int(p/50*255+0.5); g=255 }
    else         { r=255; g=int((100-p)/50*255+0.5) }
    b=0;
    track="\033[38;2;62;62;62m";
    out=sprintf("\033[38;2;%d;%d;%dm", r, g, b);
    for (i=0; i<full; i++) out=out "█";
    if (half) { out=out "\033[48;2;62;62;62m▌\033[49m"; full++ }
    out=out track;
    for (i=full; i<cells; i++) out=out "█";
    printf "%s\033[0m", out;
  }'
}

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

# Current directory, with $HOME shown as ~.
case "$cwd" in
  "$HOME") dir="~" ;;
  "$HOME"/*) dir="~${cwd#"$HOME"}" ;;
  *) dir="$cwd" ;;
esac

branch=""
if git -C "$cwd" --no-optional-locks rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null || true)
fi

# Generation speed of the most recent API response, in tokens per second.
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
SPEED_DIR="${HOME}/.claude/statusline-speed"
speed=""
sid=$(printf '%s' "$input" | jq -r '.session_id // empty')
api_ms=$(printf '%s' "$input" | jq -r '.cost.total_api_duration_ms // empty')
out_tok=$(printf '%s' "$input" | jq -r '.context_window.current_usage.output_tokens // .context_window.total_output_tokens // empty')
api_ms="${api_ms%%.*}"
out_tok="${out_tok%%.*}"
case "$sid" in *[!A-Za-z0-9_-]*) sid="" ;; esac
case "$api_ms" in ''|*[!0-9]*) api_ms="" ;; esac
case "$out_tok" in ''|*[!0-9]*) out_tok="" ;; esac

if [ -n "$sid" ] && [ -n "$api_ms" ] && [ -n "$out_tok" ]; then
  speed_state="${SPEED_DIR}/${sid}"
  prev_ms=""
  last_rate=""
  if [ -f "$speed_state" ]; then
    read -r prev_ms last_rate < "$speed_state" || true
  else
    mkdir -p "$SPEED_DIR" 2>/dev/null || true
    find "$SPEED_DIR" -type f -mtime +7 -delete 2>/dev/null || true
  fi

  new_rate="$last_rate"
  case "$prev_ms" in
    ''|*[!0-9]*) ;;   # no baseline yet: record one below, show nothing
    *)
      if [ "$api_ms" -gt "$prev_ms" ]; then
        r=$(awk -v t="$out_tok" -v d=$(( api_ms - prev_ms )) 'BEGIN {
          if (t >= 30 && d >= 500 && t / (d / 1000) <= 2000) printf "%.1f", t / (d / 1000)
        }')
        if [ -n "$r" ]; then
          new_rate="$r"
        fi
      fi
      ;;
  esac

  if [ "$api_ms" != "$prev_ms" ]; then
    printf '%s %s\n' "$api_ms" "$new_rate" > "${speed_state}.tmp.$$" 2>/dev/null \
      && mv -f "${speed_state}.tmp.$$" "$speed_state" 2>/dev/null || true
  fi
  speed="$new_rate"
fi

ctx_bar=$(render_bar "$pct_int")
line="📊 Context: ${ctx_bar} ${pct_int}% (${used_k}/${total_k})"

# 5-hour rate limit. Skip silently if Claude Code didn't supply it.
if [ -n "${five_pct:-}" ]; then
  five_int=$(awk -v p="$five_pct" 'BEGIN { printf "%.0f", p }')
  five_bar=$(render_bar "$five_int")
  if [ -n "${five_reset:-}" ]; then
    five_in=$(fmt_countdown $(( five_reset - now )))
    line="${line} │ 5h: ${five_bar} ${five_int}% (${five_in})"
  else
    line="${line} │ 5h: ${five_bar} ${five_int}%"
  fi
fi

# 7-day rate limit.
if [ -n "${seven_pct:-}" ]; then
  seven_int=$(awk -v p="$seven_pct" 'BEGIN { printf "%.0f", p }')
  seven_bar=$(render_bar "$seven_int")
  if [ -n "${seven_reset:-}" ]; then
    seven_in=$(fmt_countdown $(( seven_reset - now )))
    line="${line} │ 7d: ${seven_bar} ${seven_int}% (${seven_in})"
  else
    line="${line} │ 7d: ${seven_bar} ${seven_int}%"
  fi
fi

# Reasoning effort is absent for models that don't support it.
if [ -n "$effort" ]; then
  model="${model} (${effort})"
fi

line="${line} │ Model: ${model} │ Dir: ${dir}"

if [ -n "$branch" ]; then
  line="${line} │ Branch: ${branch}"
fi

if [ -n "$speed" ]; then
  line="${line} │ ${speed} tok/s"
fi

printf '%s' "$line"
