#!/bin/bash
# statusline-daemon.sh — background worker for the thin-reader variant.
# Installs to: ~/.claude/statusline-daemon.sh
#
# Every INTERVAL seconds this daemon:
#   1. Reads the last JSON snapshot written by statusline.sh.
#   2. Recomputes the display line (so countdowns tick even when Claude is idle).
#   3. Atomically writes the result to the cache file, plus an "identity" file
#      so the thin reader can tell whether the cache belongs to the current
#      session (same session_id / cwd / model / effort / ctx size) or is stale.
#
# Run as a launchd user agent (macOS) or systemd user service (Linux). See
# com.user.claude-statusline-daemon.plist / claude-statusline-daemon.service.
# Do not run this script directly in interactive shells.

INTERVAL=30
SNAPSHOT_FILE="${HOME}/.claude/statusline_snapshot.json"
CACHE_FILE="${HOME}/.claude/statusline_cache.txt"
CACHE_ID_FILE="${HOME}/.claude/statusline_cache_id.txt"
COMPUTE_SCRIPT="${HOME}/.claude/statusline-compute.sh"
CACHE_TMP="${CACHE_FILE}.tmp"
CACHE_ID_TMP="${CACHE_ID_FILE}.tmp"

# Ensure the .claude directory exists.
mkdir -p "${HOME}/.claude"

while true; do
  if [ -s "$SNAPSHOT_FILE" ]; then
    # Compute into a temp file first, then rename — atomic on same filesystem.
    if bash "$COMPUTE_SCRIPT" < "$SNAPSHOT_FILE" > "$CACHE_TMP" 2>/dev/null; then
      # Recompute identity from the same snapshot the cache was just built from
      # so reader and daemon agree on what the cache represents.
      new_id=$(jq -r '
        [
          .session_id // "",
          .workspace.current_dir // "",
          .model.id // .model.display_name // "",
          .effort.level // "",
          (.context_window.context_window_size // 0 | tostring),
          (.cost.total_api_duration_ms // 0 | floor | tostring)
        ] | join("|")
      ' < "$SNAPSHOT_FILE" 2>/dev/null || true)
      printf '%s' "$new_id" > "$CACHE_ID_TMP"
      mv -f "$CACHE_TMP" "$CACHE_FILE"
      mv -f "$CACHE_ID_TMP" "$CACHE_ID_FILE"
    fi
  fi
  sleep "$INTERVAL"
done
