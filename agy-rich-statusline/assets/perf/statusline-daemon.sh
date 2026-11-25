#!/bin/bash
# statusline-daemon.sh — background worker for the Antigravity statusline thin-reader variant.
# Installs to: ~/.gemini/antigravity-cli/statusline-daemon.sh
#
# Every INTERVAL seconds this daemon:
#   1. Reads the latest StatusLineData JSON snapshot written by statusline.sh.
#   2. Recomputes the display line against current wall-clock time (so quota
#      reset_time countdowns keep ticking even while agy is idle).
#   3. Atomically updates statusline_cache.txt + statusline_cache_id.txt.
#
# Run as a launchd user agent (macOS) or systemd user service (Linux).

INTERVAL=30
AGY_DIR="${AGY_CLI_DIR:-${HOME}/.gemini/antigravity-cli}"
SNAPSHOT_FILE="${AGY_DIR}/statusline_snapshot.json"
CACHE_FILE="${AGY_DIR}/statusline_cache.txt"
CACHE_ID_FILE="${AGY_DIR}/statusline_cache_id.txt"
COMPUTE_SCRIPT="${AGY_DIR}/statusline-compute.sh"
CACHE_TMP="${CACHE_FILE}.tmp"
CACHE_ID_TMP="${CACHE_ID_FILE}.tmp"

mkdir -p "$AGY_DIR"

while true; do
  if [ -s "$SNAPSHOT_FILE" ]; then
    if bash "$COMPUTE_SCRIPT" < "$SNAPSHOT_FILE" > "$CACHE_TMP" 2>/dev/null; then
      new_id=$(jq -r '
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
      ' < "$SNAPSHOT_FILE" 2>/dev/null || true)
      printf '%s' "$new_id" > "$CACHE_ID_TMP"
      mv -f "$CACHE_TMP" "$CACHE_FILE"
      mv -f "$CACHE_ID_TMP" "$CACHE_ID_FILE"
    fi
  fi
  sleep "$INTERVAL"
done
