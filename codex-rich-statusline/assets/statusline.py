"""Render a Claude-style Codex CLI footer over MCP stdio."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time


URI = "ui://codex-rich-statusline/footer"
STATE_KEY = "com.openai/codex-statusline-state"
TOOL = {
    "name": "statusline",
    "title": "Rich Codex status line",
    "description": "Render the current Codex thread's terminal footer.",
    "inputSchema": {"type": "object", "properties": {}},
    "_meta": {"openai/ui": {"entrypoints": [{"type": "statusline", "resourceUri": URI}]}},
}
RESOURCE = {"uri": URI, "name": "Codex footer", "mimeType": "application/json"}
TEXT = "#a6a6a6"
TRACK = "#3e3e3e"
SEPARATOR = " │ "
branch_cwd = None
branch_name = ""
branch_expires_at = 0.0


def colored(value, color=TEXT):
    return {"type": "text", "props": {"color": color}, "children": [value]}


def percent_bar(percentage):
    value = max(0, min(round(percentage), 100))
    red = round(min(value / 50, 1) * 255)
    green = round(min((100 - value) / 50, 1) * 255)
    blocks, half = divmod(value // 10, 2)
    fill = "█" * blocks + "▌" * half
    track = "█" * (5 - blocks - half)
    return [colored(fill, f"#{red:02x}{green:02x}00"), colored(track, TRACK)]


def token_count(value):
    return f"{value / 1000:,.0f}k" if value >= 1000 else str(value)


def countdown(reset_at, now):
    if reset_at <= now:
        return "now"
    minutes = int(reset_at - now) // 60
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d{hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h{minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


def find_git():
    executable = "git.exe" if os.name == "nt" else "git"
    for entry in os.get_exec_path():
        directory = Path(entry)
        if directory.is_absolute():
            candidate = directory / executable
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


GIT = find_git()


def current_branch(cwd):
    global branch_cwd, branch_name, branch_expires_at
    if GIT is None:
        return ""
    now = time.monotonic()
    if cwd != branch_cwd or now >= branch_expires_at:
        branch_cwd = cwd
        branch_expires_at = now + 5
        branch_name = ""
        try:
            result = subprocess.run(
                [GIT, "branch", "--show-current"], cwd=cwd, capture_output=True,
                timeout=0.3, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                branch_name = result.stdout.strip()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return branch_name


def short_path(cwd):
    user_dir = Path(os.path.expanduser("~"))
    try:
        relative = Path(cwd).relative_to(user_dir)
    except ValueError:
        return cwd
    return "~" if relative == Path(".") else str(Path("~") / relative)


def permission_segments(thread):
    permissions = thread.get("permissions") or {}
    approval = thread.get("approval") or {}
    policy = approval.get("policy")
    if policy == "never":
        mode = "No approval prompts"
    elif approval.get("reviewer") == "auto-review":
        mode = "Approve for me"
    else:
        mode = "Ask for approval" if policy else None

    labels = [label for label in (permissions.get("display_name"), mode) if label]
    color = "#ff5f74" if permissions.get("type") == "disabled" else "#73dbe2"
    return ["\n", colored("» " + " · ".join(labels), color)] if labels else []


def limit_label(minutes, default):
    if not minutes:
        return default
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def render(state):
    thread = state.get("thread", {})
    model = thread.get("model", {})
    context = thread.get("usage", {}).get("context", {})
    used = context.get("used_tokens")
    total = context.get("context_window_size")
    percentage = context.get("used_percentage")
    if percentage is None and used is not None and total:
        percentage = 100 * used / total

    segments = []
    if percentage is not None:
        counts = f" ({token_count(used)}/{token_count(total)})" if used is not None and total else ""
        segments.append(["📊 ", *percent_bar(percentage), colored(f" {percentage:.0f}%{counts}")])

    rate_limits = state.get("account", {}).get("rate_limits", [])
    codex_limits = next((limit for limit in rate_limits if limit.get("limit_id") == "codex"), {})
    now = time.time()
    for field, default_label in (("primary_limit", "5h"), ("secondary_limit", "7d")):
        limit = codex_limits.get(field) or {}
        used_percent = limit.get("used_percent")
        if used_percent is None:
            continue
        label = limit_label(limit.get("window_minutes"), default_label)
        reset_at = limit.get("resets_at")
        reset = f" ({countdown(reset_at, now)})" if reset_at is not None else ""
        segments.append([
            colored(f"{label}: "), *percent_bar(used_percent), colored(f" {used_percent:.0f}%{reset}"),
        ])

    name = model.get("display_name") or model.get("id") or "Codex"
    effort = model.get("reasoning_level")
    segments.append([colored(f"{name} ({effort})" if effort else name)])
    cwd = thread.get("workspace", {}).get("cwd")
    if cwd:
        segments.append([colored(short_path(cwd))])
        if branch := current_branch(cwd):
            segments.append([colored(f"Branch: {branch}")])

    children = []
    for segment in segments:
        if children:
            children.append(colored(SEPARATOR))
        children.extend(segment)
    children.extend(permission_segments(thread))
    return {"type": "text", "children": children}


def respond(method, params):
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "claude-style-statusline", "version": "1.0.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call" and params.get("name") == TOOL["name"]:
        return {"content": [{"type": "text", "text": f"Status line resource: {URI}"}]}
    if method == "resources/list":
        return {"resources": [RESOURCE]}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read" and params.get("uri") == URI:
        state = params.get("_meta", {}).get(STATE_KEY, {})
        content = {"uri": URI, "mimeType": RESOURCE["mimeType"], "text": json.dumps(render(state))}
        return {"contents": [content]}
    raise KeyError(method)


def main():
    for line in sys.stdin.buffer:
        reply = {"jsonrpc": "2.0", "id": None}
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                reply["error"] = {"code": -32600, "message": "Invalid request"}
            elif "id" not in request:
                continue
            else:
                reply["id"] = request["id"]
                reply["result"] = respond(request["method"], request.get("params") or {})
        except (json.JSONDecodeError, UnicodeDecodeError):
            reply["error"] = {"code": -32700, "message": "Parse error"}
        except KeyError:
            reply["error"] = {"code": -32601, "message": "Unknown method or resource"}
        except (AttributeError, TypeError, ValueError):
            reply["error"] = {"code": -32602, "message": "Invalid params"}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
