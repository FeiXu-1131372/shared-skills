#!/bin/bash
# Claude Code subagent statusline — one row per subagent.
#
# Claude Code pipes {"tasks":[{id,agentType,status,description,label,
# startTime,model,effort,tokenCount,contextWindowSize,tokenSamples,cwd}, ...]}
# to stdin and expects one JSON object per line on stdout:
#   {"id":"<task id>","content":"<row text>"}
#
# Style follows statusline-compute.sh: " │ " separators, truecolor gradient
# for severity. Row layout:
#   <type> │ <model> (<effort>) │ <elapsed> │ ↓ <tokens> │ <n> tok/s │ <description> · <activity>
# Description goes last so a narrow terminal clips it, not the numbers.
# Every field is optional, so missing parts are simply left out.
#
# Effort: Claude Code only sends a task's effort when the agent set one itself;
# normally it is null. Then we show what settings.json would give that model
# (modelSettings.<id>.effortLevel, else effortLevel), in dim brackets to mark it
# as inferred. A per-agent override we cannot see would make it wrong.
#
# Speed: Claude Code gives only a running token total (tokenCount), so tok/s is
# the growth of that total over a >=5 s window, kept in a tiny per-task file in
# ~/.claude/subagent-speed/. It is the same kind of end-to-end figure as the
# main line's tok/s, but tokenCount also grows when a tool result lands in the
# subagent's context, so a big file read shows as a brief spike. Windows above
# 3000 tok/s are ignored as such spikes; the previous figure stays. Nothing is
# shown until one window has been measured, or while the count is not moving.
#
# The raw input is kept in ~/.claude/subagent_statusline_snapshot.json
# (like statusline.sh does) so the field shapes can be checked later.

set -eu

SPEED_DIR="${HOME}/.claude/subagent-speed"
MIN_WINDOW=5      # seconds of growth to average over
MAX_RATE=3000     # tok/s above this is a tool-result spike, not generation
STALE=60          # seconds without a tick before a task's baseline is dropped

input=$(cat)
printf '%s\n' "$input" > "${HOME}/.claude/subagent_statusline_snapshot.json"

now=$(date +%s)
mkdir -p "$SPEED_DIR" 2>/dev/null || true
find "$SPEED_DIR" -type f -mtime +1 -delete 2>/dev/null || true

# One "id rate" line per running task that has a measured, non-zero rate.
speed_lines=""
while IFS=$'\t' read -r id count; do
  case "$id" in ''|*[!A-Za-z0-9_-]*) continue ;; esac
  count="${count%%.*}"
  case "$count" in ''|*[!0-9]*) continue ;; esac

  state="${SPEED_DIR}/${id}"
  t0=""; c0=""; rate=""
  if [ -f "$state" ]; then
    read -r t0 c0 rate < "$state" || true
  fi
  case "$t0" in ''|*[!0-9]*) t0="" ;; esac
  case "$c0" in ''|*[!0-9]*) c0="" ;; esac

  if [ -z "$t0" ] || [ -z "$c0" ] || [ $(( now - t0 )) -gt "$STALE" ] || [ "$count" -lt "$c0" ]; then
    # No usable baseline: start one, show nothing yet.
    rate=""
    t0="$now"; c0="$count"
  elif [ $(( now - t0 )) -ge "$MIN_WINDOW" ]; then
    r=$(awk -v d=$(( count - c0 )) -v s=$(( now - t0 )) -v max="$MAX_RATE" -v prev="${rate:-}" 'BEGIN {
      v = d / s
      if (v > max) { printf "%s", prev }
      else         { printf "%.0f", v }
    }')
    rate="$r"
    t0="$now"; c0="$count"
  fi

  printf '%s %s %s\n' "$t0" "$c0" "$rate" > "${state}.tmp.$$" 2>/dev/null \
    && mv -f "${state}.tmp.$$" "$state" 2>/dev/null || true

  if [ -n "$rate" ] && [ "$rate" -gt 0 ]; then
    speed_lines="${speed_lines}${id} ${rate}"$'\n'
  fi
done < <(printf '%s' "$input" | jq -r '(.tasks // [])[] | select(.id != null and .status == "running") | [.id, (.tokenCount // "")] | @tsv')

speeds=$(printf '%s' "$speed_lines" | jq -Rn '[inputs | select(length > 0) | split(" ") | {(.[0]): (.[1] | tonumber)}] | add // {}')

printf '%s' "$input" | jq -c --argjson speeds "$speeds" --slurpfile settings "${HOME}/.claude/settings.json" '
  # startTime may be epoch ms, epoch seconds or an ISO string.
  def to_epoch:
    if . == null then null
    elif type == "number" then (if . > 1e11 then . / 1000 else . end)
    elif type == "string" then (try (sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601) catch null)
    else null end;

  # 24-bit colour, same ramp as the main status line: green -> yellow -> red.
  def ramp($p):
    ([0, ([$p, 100] | min)] | max) as $q
    | (if $q <= 50 then [($q / 50 * 255 + 0.5 | floor), 255, 0]
       else [255, ((100 - $q) / 50 * 255 + 0.5 | floor), 0] end)
    | "\u001b[38;2;\(.[0]);\(.[1]);\(.[2])m";
  def dim: "\u001b[2m";
  def reset: "\u001b[0m";

  def fmt_elapsed($s):
    ($s | floor) as $s
    | if $s >= 3600 then "\($s / 3600 | floor)h\(($s % 3600) / 60 | floor)m"
      elif $s >= 60 then "\($s / 60 | floor)m\($s % 60)s"
      else "\($s)s" end;

  def fmt_k:
    if . >= 1000000 then "\(. / 1000000 * 10 | round / 10)M"
    elif . >= 1000 then "\(. / 1000 * 10 | round / 10)k"
    else "\(.)" end;

  # model may be a string id or an object; "claude-sonnet-5-5" -> "sonnet 5.5".
  def model_name:
    (if type == "object" then (.display_name // .id // "") else (. // "") end) as $m
    | if $m == "" then ""
      else ($m | sub("^claude-"; "") | sub("-(?<a>[0-9])-(?<b>[0-9])$"; " \(.a).\(.b)") | sub("-"; " ")) end;

  now as $now
  | (.tasks // [])[]
  | select(.id != null)
  | . as $t
  | ([
      (($t.agentType // $t.name // "agent") | tostring),
      ((($t.model | model_name) as $m
        | ($t.model | if type == "object" then .id else . end) as $mid
        | ($settings[0].modelSettings[$mid // ""].effortLevel // $settings[0].effortLevel // null) as $cfg
        | if $m == "" then empty
          elif $t.effort then "\($m) (\($t.effort))"
          elif $cfg then "\($m) \(dim)(\($cfg))\(reset)"
          else $m end)),
      (($t.startTime | to_epoch) as $st
        | if $st == null then empty
          else ($now - $st) as $el
          | "\(ramp($el / 36))\(fmt_elapsed([$el, 0] | max))\(reset)" end),
      (if ($t.tokenCount // null) != null then "↓ \($t.tokenCount | fmt_k)" else empty end),
      ($speeds[$t.id] // null | if . then "\(.) tok/s" else empty end),
      (([($t.description // ""), (if ($t.label // "") != "" then "\(dim)\($t.label)\(reset)" else "" end)]
         | map(select(. != "")) | join(" · ")) | select(. != ""))
    ] | join(" │ ")) as $row
  | {id: $t.id, content: $row}
'
