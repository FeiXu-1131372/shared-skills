#!/bin/bash
# Antigravity CLI (agy) statusline — thin reader (performance variant).
# Installs to: ~/.gemini/antigravity-cli/statusline.sh
#
# Antigravity pipes fresh StatusLineData JSON here on every state/UI update. We:
#   1. Persist the JSON snapshot so the background daemon can recompute quota
#      countdowns (from reset_time) every 30s even while agy is idle.
#   2. Check whether the daemon's cached line matches the current session/turn
#      identity — if conversation, model, effort, cwd, context usage, output
#      tokens, agent_state, VCS, subagents, or cost changed, recompute fresh
#      immediately so tok/s and bars never lag.
#   3. Print the cached or freshly computed line to stdout.

set -eu

AGY_DIR="${AGY_CLI_DIR:-${HOME}/.gemini/antigravity-cli}"
SNAPSHOT_FILE="${AGY_DIR}/statusline_snapshot.json"
CACHE_FILE="${AGY_DIR}/statusline_cache.txt"
CACHE_ID_FILE="${AGY_DIR}/statusline_cache_id.txt"
COMPUTE_SCRIPT="${AGY_DIR}/statusline-compute.sh"

input=$(cat)
if [ -z "${input//[[:space:]]/}" ]; then
  exit 0
fi

mkdir -p "$AGY_DIR" 2>/dev/null || true
printf '%s\n' "$input" > "$SNAPSHOT_FILE"

new_id=$(printf '%s' "$input" | jq -r '
  [
    (.conversation_id // .session_id // ""),
    (.workspace.current_dir // .cwd // ""),
    (.model.id // .model.display_name // ""),
    (.model.effort // .effort.level // ""),
    (.context_window.context_window_size // 0 | tostring),
    (.context_window.used_percentage // 0 | tostring),
    (.context_window.total_output_tokens // 0 | floor | tostring),
    (.agent_state // "idle"),
    (.vcs.branch // .vcs.client // ""),
    (if .vcs.dirty == true then "1" else "0" end),
    ((.subagents // []) | map(.status // "") | join(",")),
    ((.cost.total_usd // .cost.total_cost_usd // 0) | tostring),
    ((.cost.total_api_duration_ms // 0) | floor | tostring)
  ] | join("|")
')

old_id=""
if [ -f "$CACHE_ID_FILE" ]; then
  old_id=$(cat "$CACHE_ID_FILE" 2>/dev/null || true)
fi

if [ -s "$CACHE_FILE" ] && [ "$new_id" = "$old_id" ]; then
  cat "$CACHE_FILE"
  exit 0
fi

fresh=$(printf '%s' "$input" | bash "$COMPUTE_SCRIPT")
printf '%s' "$fresh" > "$CACHE_FILE"
printf '%s' "$new_id" > "$CACHE_ID_FILE"
printf '%s' "$fresh"
