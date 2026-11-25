#!/bin/bash
# Antigravity CLI (agy) rich statusline — bash / macOS / Linux.
# Reads StatusLineData JSON from stdin, prints one colored line:
#   📊 █▌░░░ 35% (367k/1049k) │ 7d: ███░░ 66% (2d10h) │ Gemini 4 Carbon (Medium) │ ~/develop │ Branch: main │ 🤖 2 subagents │ $0.14 │ 116.1 tok/s
# Bar color is a smooth truecolor gradient: green (0%) → yellow (50%) → red (100%).
# Requires jq, awk, and a terminal with 24-bit color.
#
# Generation speed (tok/s) keeps a tiny per-conversation state file in
# ~/.gemini/antigravity-cli/statusline-speed/ (override via AGY_STATUSLINE_SPEED_DIR)
# tracking active generation start time and output token deltas. Re-rendering
# the same idle snapshot is idempotent and never changes the figure.

set -eu

input=$(cat)
if [ -z "${input//[[:space:]]/}" ]; then
  exit 0
fi

# Render a 5-cell bar with half-cell ▌ resolution. Color is a smooth truecolor
# gradient from green (0%) → yellow (50%) → red (100%); the empty part is a flat
# dark-gray track, and a half cell is the bar color on a track-colored background.
render_bar() {
  local pct=$1
  awk -v p="$pct" 'BEGIN {
    cells=5;
    if (p < 0) p=0; if (p > 100) p=100;
    full=int(p/20);
    rem=p - full*20;
    half=(rem >= 10 && full < cells) ? 1 : 0;
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

# Format a duration in seconds as "XdYh", "Xd", "XhYm", "Xh", or "Xm".
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
    if [ "$h" -gt 0 ]; then echo "${d}d${h}h"; else echo "${d}d"; fi
  elif [ "$h" -ge 1 ]; then
    if [ "$m" -gt 0 ]; then echo "${h}h${m}m"; else echo "${h}h"; fi
  else
    echo "${m}m"
  fi
}

fmt_k() {
  awk -v n="$1" 'BEGIN {
    if (n >= 1000) printf "%.0fk", n/1000
    else printf "%d", n
  }'
}

# Single jq pass: extracts core fields, normalizes Antigravity quota buckets
# (with fallback to Claude-style rate_limits), active subagent summary, cost,
# and portable epoch timestamps (works on both macOS BSD and Linux GNU).
parsed=$(printf '%s' "$input" | jq -r '
  def parse_iso:
    if type != "string" or length == 0 then null
    else (try (sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601) catch null)
    end;

  def short_prefix($s):
    if ($s | test("^gemini"; "i")) then "Gem"
    elif ($s | test("^claude"; "i")) then "Cld"
    elif ($s | test("^gpt|^openai"; "i")) then "GPT"
    else ($s | split("-")[0] | split("_")[0])
    end;

  (now) as $now_s |
  (($now_s * 1000) | floor) as $now_ms |

  # Context window
  (.context_window.context_window_size // 1048576) as $ctx_size |
  (if .context_window.used_percentage != null then .context_window.used_percentage
   elif .context_window.remaining_percentage != null then (100 - .context_window.remaining_percentage)
   else 0 end) as $pct |

  # Model & effort (deduplicate if display_name already ends with "(Effort)")
  (.model.display_name // .model.id // "?") as $raw_model |
  (.model.effort // .effort.level // "") as $eff |
  (if ($eff != "") and (($raw_model | ascii_downcase | endswith("(" + ($eff | ascii_downcase) + ")")) | not)
   then "\($raw_model) (\($eff))"
   else $raw_model end) as $model_str |

  # Workspace & VCS
  (.workspace.current_dir // .cwd // ".") as $cwd |
  (if .vcs != null then "1" else "0" end) as $has_vcs |
  (.vcs.branch // .vcs.client // "") as $vcs_branch |
  (if .vcs.dirty == true then "1" else "0" end) as $vcs_dirty |

  # Active subagents
  ([(.subagents // [])[]
    | select(((.status // "") | ascii_downcase) as $st
      | ($st != "" and ($st | test("^(completed|done|failed|killed|stopped|cancelled|canceled|idle|subagent_state_killed)$") | not)))
   ]) as $active_subs |
  (if ($active_subs | length) == 0 then ""
   elif ($active_subs | length) == 1 then
     ($active_subs[0].role // $active_subs[0].name // "subagent") as $r |
     (if ($active_subs[0].model // "") != "" then "🤖 \($r) (\($active_subs[0].model))" else "🤖 \($r)" end)
   else "🤖 \($active_subs | length) subagents" end) as $sub_str |

  # Cost
  (.cost.total_usd // .cost.total_cost_usd // 0) as $cost_val |
  (if ($cost_val | type) == "number" and $cost_val >= 0.01 then
     "$" + (($cost_val * 100 | round / 100) | tostring | if test("\\.[0-9]$") then . + "0" elif test("\\.") then . else . + ".00" end)
   elif ($cost_val | type) == "number" and $cost_val >= 0.001 then
     "$" + (($cost_val * 1000 | round / 1000) | tostring)
   else "" end) as $cost_str |

  # Quota buckets -> array of "bar|<label>|<used_pct>|<secs_or_empty>" or "credits|<amount>"
  (if (.quota != null and (.quota | type) == "object" and (.quota | length) > 0) then
     ([.quota | to_entries[] | select(.value.disabled != true)]
      | sort_by(
          (if .value.remaining_fraction == null then 50
           elif (.key | test("(-|_)5h$|^five_hour$|^5h$"; "i")) then 10
           elif (.key | test("(-|_)daily$|^1d$"; "i")) then 20
           elif (.key | test("(-|_)weekly$|^seven_day$|^7d$"; "i")) then 30
           else 40 end),
          .key
        )) as $entries |
     ([ $entries[] | select(.key | test("(-|_)weekly$"; "i")) ] | length) as $wk_cnt |
     ([ $entries[] | select(.key | test("(-|_)daily$"; "i")) ] | length) as $dy_cnt |
     ([ $entries[] | select(.key | test("(-|_)5h$|five_hour"; "i")) ] | length) as $fh_cnt |
     [ $entries[] |
       .key as $k | .value as $v |
       (if ($k | test("^five_hour$|^5h$"; "i")) then "5h"
        elif ($k | test("^seven_day$|^7d$"; "i")) then "7d"
        elif ($k | test("(-|_)5h$"; "i")) then (if $fh_cnt > 1 then "\(short_prefix($k)) 5h" else "5h" end)
        elif ($k | test("(-|_)weekly$"; "i")) then (if $wk_cnt > 1 then "\(short_prefix($k)) 7d" else "7d" end)
        elif ($k | test("(-|_)daily$"; "i")) then (if $dy_cnt > 1 then "\(short_prefix($k)) 1d" else "1d" end)
        else ($k | sub("(-|_)quota$"; "")) end) as $lbl |
       if $v.remaining_fraction != null then
         (((1 - $v.remaining_fraction) * 100) | if . < 0 then 0 elif . > 100 then 100 else . end | round) as $upct |
         (($v.reset_time | parse_iso) as $rt |
          if $rt != null then (($rt - $now_s) | floor | tostring)
          elif $v.reset_in_seconds != null then ($v.reset_in_seconds | floor | tostring)
          else "" end) as $rem_s |
         "bar|\($lbl)|\($upct)|\($rem_s)"
       elif ($v.remaining_amount != null and $v.remaining_amount > 0) then
         "credits|\($v.remaining_amount | floor)"
       else empty end
     ]
   elif (.rate_limits != null and (.rate_limits | type) == "object") then
     [
       (if .rate_limits.five_hour.used_percentage != null then
          "bar|5h|\(.rate_limits.five_hour.used_percentage | round)|\(if .rate_limits.five_hour.resets_at != null then ((.rate_limits.five_hour.resets_at - $now_s) | floor | tostring) else "" end)"
        else empty end),
       (if .rate_limits.seven_day.used_percentage != null then
          "bar|7d|\(.rate_limits.seven_day.used_percentage | round)|\(if .rate_limits.seven_day.resets_at != null then ((.rate_limits.seven_day.resets_at - $now_s) | floor | tostring) else "" end)"
        else empty end)
     ]
   else [] end) as $qitems |

  # Speed tracking fields
  (.conversation_id // .session_id // "") as $sid |
  (.agent_state // "idle") as $astate |
  (if .tool_confirmation_pending == true or (.pending_input_count // 0) > 0 then "1" else "0" end) as $paused |
  (.context_window.total_output_tokens // 0 | floor) as $tot_out |
  (.context_window.current_usage.output_tokens // 0 | floor) as $cur_out |
  (if .cost.total_api_duration_ms != null then (.cost.total_api_duration_ms | floor | tostring) else "" end) as $api_ms |

  [
    ($pct | tostring),
    ($ctx_size | floor | tostring),
    $model_str,
    $cwd,
    $has_vcs,
    $vcs_branch,
    $vcs_dirty,
    $sub_str,
    $cost_str,
    $sid,
    $astate,
    $paused,
    ($tot_out | tostring),
    ($cur_out | tostring),
    $api_ms,
    ($now_ms | tostring),
    ($qitems | join("\u001f"))
  ] | join("\t")
')

IFS=$'\t' read -r pct ctx_size model cwd has_vcs vcs_branch vcs_dirty sub_str cost_str sid astate paused tot_out cur_out api_ms now_ms qitems_joined <<< "$parsed"

pct_int=$(awk -v p="${pct:-0}" 'BEGIN { printf "%.0f", p }')
tokens_used=$(awk -v p="${pct:-0}" -v s="${ctx_size:-1048576}" 'BEGIN { printf "%d", p * s / 100 }')
used_k=$(fmt_k "$tokens_used")
total_k=$(fmt_k "${ctx_size:-1048576}")

# Abbreviate $HOME as ~
case "$cwd" in
  "$HOME") dir="~" ;;
  "$HOME"/*) dir="~${cwd#"$HOME"}" ;;
  *) dir="$cwd" ;;
esac

# VCS branch: prefer Antigravity's built-in .vcs payload (zero subprocesses);
# fall back to git only when .vcs was omitted.
branch="$vcs_branch"
if [ "$has_vcs" = "0" ] && [ -z "$branch" ]; then
  if git -C "$cwd" --no-optional-locks rev-parse --git-dir >/dev/null 2>&1; then
    branch=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null || true)
  fi
fi
if [ -n "$branch" ] && [ "$vcs_dirty" = "1" ]; then
  branch="${branch}*"
fi

# Generation speed (tok/s) of the latest completed model response.
# Supports both Antigravity's live state/token transitions and optional
# cost.total_api_duration_ms payloads.
SPEED_DIR="${AGY_STATUSLINE_SPEED_DIR:-${HOME}/.gemini/antigravity-cli/statusline-speed}"
speed=""
case "$sid" in *[!A-Za-z0-9_-]*) sid="" ;; esac

if [ -n "$sid" ]; then
  speed_state="${SPEED_DIR}/${sid}"
  prev_out=""
  phase_ms="0"
  prev_api=""
  last_rate=""
  if [ -f "$speed_state" ]; then
    read -r prev_out phase_ms prev_api last_rate < "$speed_state" || true
  else
    mkdir -p "$SPEED_DIR" 2>/dev/null || true
    find "$SPEED_DIR" -type f -mtime +7 -delete 2>/dev/null || true
  fi
  case "$prev_out" in ''|*[!0-9]*) prev_out="" ;; esac
  case "$phase_ms" in ''|*[!0-9]*) phase_ms="0" ;; esac
  case "$prev_api" in ''|*[!0-9]*) prev_api="" ;; esac

  new_rate="$last_rate"
  new_phase="$phase_ms"

  if [ -n "$api_ms" ]; then
    # Path A: explicit cumulative API duration (ms)
    if [ -n "$prev_api" ] && [ "$api_ms" -gt "$prev_api" ]; then
      tok_sample="$cur_out"
      if [ "${tok_sample:-0}" -le 0 ] && [ -n "$prev_out" ] && [ "$tot_out" -gt "$prev_out" ]; then
        tok_sample=$(( tot_out - prev_out ))
      fi
      r=$(awk -v t="${tok_sample:-0}" -v d=$(( api_ms - prev_api )) 'BEGIN {
        if (t >= 30 && d >= 500 && t / (d / 1000) <= 2000) printf "%.1f", t / (d / 1000)
      }')
      [ -n "$r" ] && new_rate="$r"
    fi
  else
    # Path B: Antigravity agent_state + total_output_tokens wall-clock window
    astate_lc=$(printf '%s' "$astate" | tr '[:upper:]' '[:lower:]')
    if [ "$paused" = "1" ]; then
      new_phase="0"
    elif [ -z "$prev_out" ]; then
      # First observation for this conversation: record baseline
      if [ "$astate_lc" != "idle" ]; then new_phase="$now_ms"; else new_phase="0"; fi
    elif [ "$tot_out" -gt "$prev_out" ]; then
      delta_tok=$(( tot_out - prev_out ))
      if [ "${cur_out:-0}" -gt 0 ] && [ "$cur_out" -lt "$delta_tok" ]; then
        delta_tok="$cur_out"
      fi
      if [ "$phase_ms" -gt 0 ] && [ "$now_ms" -gt "$phase_ms" ]; then
        r=$(awk -v t="$delta_tok" -v d=$(( now_ms - phase_ms )) 'BEGIN {
          if (t >= 30 && d >= 500 && t / (d / 1000) <= 2000) printf "%.1f", t / (d / 1000)
        }')
        [ -n "$r" ] && new_rate="$r"
      fi
      if [ "$astate_lc" = "idle" ]; then new_phase="0"; else new_phase="$now_ms"; fi
    else
      if [ "$astate_lc" = "idle" ]; then
        new_phase="0"
      elif [ "$phase_ms" = "0" ]; then
        new_phase="$now_ms"
      fi
    fi
  fi

  if [ "$tot_out" != "$prev_out" ] || [ "$new_phase" != "$phase_ms" ] || [ "${api_ms:-0}" != "${prev_api:-0}" ] || [ "$new_rate" != "$last_rate" ]; then
    printf '%s %s %s %s\n' "$tot_out" "$new_phase" "${api_ms:-0}" "$new_rate" > "${speed_state}.tmp.$$" 2>/dev/null \
      && mv -f "${speed_state}.tmp.$$" "$speed_state" 2>/dev/null || true
  fi
  speed="$new_rate"
fi

# Compose the status line
ctx_bar=$(render_bar "$pct_int")
line="📊 ${ctx_bar} ${pct_int}% (${used_k}/${total_k})"

if [ -n "${qitems_joined:-}" ]; then
  IFS=$'\x1f' read -r -a qarr <<< "$qitems_joined"
  for qitem in "${qarr[@]}"; do
    [ -z "$qitem" ] && continue
    IFS='|' read -r qkind qlbl qval qsec <<< "$qitem"
    if [ "$qkind" = "bar" ]; then
      qbar=$(render_bar "$qval")
      if [ -n "${qsec:-}" ]; then
        qin=$(fmt_countdown "$qsec")
        line="${line} │ ${qlbl}: ${qbar} ${qval}% (${qin})"
      else
        line="${line} │ ${qlbl}: ${qbar} ${qval}%"
      fi
    elif [ "$qkind" = "credits" ]; then
      ck=$(fmt_k "$qval")
      line="${line} │ Credits: ${ck}"
    fi
  done
fi

line="${line} │ ${model} │ ${dir}"

if [ -n "$branch" ]; then
  line="${line} │ Branch: ${branch}"
fi

if [ -n "$sub_str" ]; then
  line="${line} │ ${sub_str}"
fi

if [ -n "$cost_str" ]; then
  line="${line} │ ${cost_str}"
fi

if [ -n "$speed" ]; then
  line="${line} │ ${speed} tok/s"
fi

printf '%s' "$line"
