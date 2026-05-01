#!/bin/bash
# Claude Code statusline — thin reader (performance variant).
# Installs to: ~/.claude/statusline.sh
#
# Claude Code pushes fresh JSON here on every status-line tick. We:
#   1. Persist the JSON snapshot so the background daemon can recompute
#      countdowns on a 30-second timer even when Claude is idle.
#   2. Decide whether the daemon's cached line is still valid for THIS
#      session — if the user has switched session_id, cwd, model, or
#      context-window size, the cache is stale and we must recompute now
#      (otherwise the new session shows the previous session's data until
#      the daemon's next 30s tick).
#   3. Print the result (cache or fresh) to stdout.

set -eu

SNAPSHOT_FILE="${HOME}/.claude/statusline_snapshot.json"
CACHE_FILE="${HOME}/.claude/statusline_cache.txt"
CACHE_ID_FILE="${HOME}/.claude/statusline_cache_id.txt"
COMPUTE_SCRIPT="${HOME}/.claude/statusline-compute.sh"

input=$(cat)

# Persist the latest snapshot so the daemon stays up-to-date.
printf '%s\n' "$input" > "$SNAPSHOT_FILE"

# Identity = the fields that make a cached render belong to one specific
# session. If any of these change, the cached line is wrong (different model
# name / different /200k vs /1000k / different cwd, etc.).
new_id=$(printf '%s' "$input" | jq -r '
  [
    .session_id // "",
    .workspace.current_dir // "",
    .model.id // .model.display_name // "",
    (.context_window.context_window_size // 0 | tostring)
  ] | join("|")
')

old_id=""
if [ -f "$CACHE_ID_FILE" ]; then
  old_id=$(cat "$CACHE_ID_FILE" 2>/dev/null || true)
fi

if [ -s "$CACHE_FILE" ] && [ "$new_id" = "$old_id" ]; then
  # Same session — daemon's cache has fresher countdowns than we'd compute now.
  cat "$CACHE_FILE"
  exit 0
fi

# Session identity changed (or no cache yet) — compute fresh, update both
# cache and id so subsequent ticks within this session can fast-path again.
fresh=$(printf '%s' "$input" | bash "$COMPUTE_SCRIPT")
printf '%s' "$fresh" > "$CACHE_FILE"
printf '%s' "$new_id" > "$CACHE_ID_FILE"
printf '%s' "$fresh"
