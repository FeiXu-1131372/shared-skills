---
name: codex-rich-statusline
description: Install, configure, or troubleshoot the rich Codex CLI footer. Use for persistent status line setup from the plain codex command, or to show context and rate-limit usage in the terminal.
---

# Rich Codex status line

The [Python provider](assets/statusline.py) renders five-cell green-to-red usage bars, reset countdowns, the active model and reasoning effort, the working directory, Git branch, and permissions.

```text
📊 █▌░░░ 32% (320k/1,000k) │ 5h: █░░░░ 24% (2h32m) │ 7d: ██▌░░ 56% (4d7h) │ GPT-6.2 Sol (xhigh) │ ~/work/repo │ Branch: main
» Workspace · Approve for me
```

Codex supplies the displayed thread's data over local MCP stdio. The provider omits unavailable fields and uses Git when it is on PATH. The Codex snapshot lacks response timing and a background shell count. Use `/ps` to inspect background terminals.

## Install once

Run the [installer](scripts/install.py) from this skill directory on the machine hosting the Codex app server. It requires Codex CLI 0.171.0 or later and Python 3.8 or later.

```powershell
python .\scripts\install.py
```

On macOS and Linux, run `python3 scripts/install.py`. The installer copies the provider to `statuslines/codex-rich-statusline/statusline.py` under the user Codex directory, reuses an existing registration or provider file, and saves the MCP registration, feature flag, and provider selection to the user `config.toml`. If the current session cannot write that config, run the installer from a normal terminal on the app-server host.

Start a fresh session with plain `codex`. Use `/statusline` → **Choose a status line provider** to switch providers later.

### Optional Full Access default

Pass `--full-access` only when the user explicitly requests Full Access for future sessions. It removes the local command sandbox and approval prompts.

```powershell
python .\scripts\install.py --full-access
```

The installer sets `default_permissions = ":danger-full-access"` and `approval_policy = "never"`. With a legacy sandbox configuration it sets `sandbox_mode = "danger-full-access"` in place of `default_permissions`. Use `/status` in a new session to see the effective mode. To undo the permission change, restore the prior values of those keys in `config.toml`.

## Verify and update

- Run `codex mcp get codex-rich-statusline` to see the registered Python executable and provider path. Edit that provider file to change colors or labels, then restart Codex so the Python process reloads it.
- If the footer falls back, press **F2** to inspect the failure and reselect **Rich Codex status line** to resume polling.
- To uninstall, select the built-in provider in `/statusline`, then run `codex mcp remove codex-rich-statusline`. The installed provider copy can then be deleted.

The [Codex provider guide](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/skills/src/assets/samples/create-statusline/SKILL.md) describes the MCP protocol and snapshot fields.
