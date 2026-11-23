"""Install the rich status line as a user default through Codex app-server."""

import argparse
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
from threading import Thread


SKILL_DIR = Path(__file__).resolve().parents[1]
PROVIDER = SKILL_DIR / "assets" / "statusline.py"
SERVER = "codex-rich-statusline"


def install_provider(destination):
    if destination.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as staging:
        temporary = Path(staging.name)
    try:
        shutil.copyfile(PROVIDER, temporary)
        os.link(temporary, destination)
    except FileExistsError:
        if not destination.is_file():
            raise
    finally:
        temporary.unlink()


def read_messages(stream, messages):
    try:
        for line in stream:
            messages.put(json.loads(line))
    finally:
        messages.put(None)


def configure(process, full_access):
    messages = Queue()
    Thread(target=read_messages, args=(process.stdout, messages), daemon=True).start()

    def send(method, params=None, request_id=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if request_id is not None:
            message["id"] = request_id
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def receive(request_id):
        while True:
            response = messages.get(timeout=30)
            if response is None:
                raise RuntimeError("Codex app-server exited before responding.")
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(response["error"]["message"])
                return response["result"]

    send("initialize", {"clientInfo": {"name": "statusline-setup", "version": "1.0"}}, 1)
    receive(1)
    send("initialized")
    send("config/read", {"includeLayers": True}, 2)
    result = receive(2)
    user_layer = next(
        (layer for layer in result.get("layers", [])
         if layer["name"]["type"] == "user" and layer["name"].get("profile") is None),
        None,
    )
    if user_layer is None:
        raise RuntimeError("Codex did not report a user config layer.")

    config_file = Path(user_layer["name"]["file"])
    current = user_layer["config"]
    settings = {
        "features.tui_extensions_statusline": True,
        "tui.status_line_provider": {"server": SERVER, "tool": "statusline"},
    }
    if full_access:
        has_legacy_sandbox = "sandbox_mode" in current or "sandbox_workspace_write" in current
        if has_legacy_sandbox and "default_permissions" in current:
            raise RuntimeError("Resolve the conflicting sandbox and permission profile settings first.")
        if has_legacy_sandbox:
            settings["sandbox_mode"] = "danger-full-access"
        else:
            settings["default_permissions"] = ":danger-full-access"
        settings["approval_policy"] = "never"

    server_key = f"mcp_servers.{SERVER}"
    existing_server = current.get("mcp_servers", {}).get(SERVER)
    if existing_server is None:
        destination = config_file.parent / "statuslines" / SERVER / "statusline.py"
        install_provider(destination)
        settings[server_key] = {"command": sys.executable, "args": ["-u", str(destination)]}
    elif existing_server.get("enabled") is False:
        settings[f"{server_key}.enabled"] = True

    edits = [
        {"keyPath": key, "value": value, "mergeStrategy": "replace"}
        for key, value in settings.items()
    ]
    send("config/batchWrite", {
        "edits": edits,
        "filePath": str(config_file),
        "expectedVersion": user_layer["version"],
    }, 3)
    result = receive(3)
    if result["status"] != "ok":
        raise RuntimeError("The user config was saved, but a higher-priority config overrides it.")
    return result["filePath"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-access", action="store_true",
        help="Also default to Full Access, with no command sandbox or approval prompts.",
    )
    args = parser.parse_args()

    if not PROVIDER.is_file():
        raise RuntimeError(f"Missing provider: {PROVIDER}")

    if os.name == "nt" and shutil.which("codex.cmd"):
        command = ["cmd.exe", "/d", "/c", "codex.cmd"]
    elif executable := shutil.which("codex"):
        command = [executable]
    else:
        raise RuntimeError("Could not find Codex CLI on PATH.")

    with subprocess.Popen(
        [*command, "app-server", "--stdio"], cwd=SKILL_DIR,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
    ) as process:
        try:
            config_path = configure(process, args.full_access)
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()

    saved = "status line and Full Access defaults" if args.full_access else "status line default"
    print(f"Saved the {saved} to {config_path}.")
    print("Start a new session with: codex")


if __name__ == "__main__":
    try:
        main()
    except Empty:
        sys.exit("Setup failed: Codex app-server timed out.")
    except (OSError, RuntimeError) as error:
        sys.exit(f"Setup failed: {error}")
