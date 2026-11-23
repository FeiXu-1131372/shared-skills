---
name: codex-rich-statusline
description: Install, configure, or troubleshoot a rich status line in the Codex CLI terminal. Shows colored context usage, 5-hour and weekly quota with reset timers, model and reasoning effort, directory, Git branch, and permissions. Use when the user asks to customize Codex /statusline or see context or quota usage in the Codex footer.
---

# Rich Codex status line

Install [the Python provider](assets/statusline.py) for a footer styled after [claude-rich-statusline](../claude-rich-statusline/SKILL.md).

```text
📊 █▌░░░ 32% (320k/1,000k) │ 5h: █░░░░ 24% (2h32m) │ 7d: ██▌░░ 56% (4d7h) │ GPT-6.2 Sol (xhigh) │ ~/work/repo │ Branch: main
» Workspace · Approve for me
```

Each five-cell meter shows the percentage used. Its fill moves from green through yellow to red, and limit countdowns update while Codex polls the provider. Context counts describe the current context window. Missing quota, context, reasoning, and Git information is omitted. Codex supplies the permission profile and approval policy for the second line.

The provider reads the displayed thread snapshot over local MCP stdio. Its only optional subprocess reads the local Git branch and caches the result briefly. Codex’s provider snapshot lacks the response timing and shell count needed for those two Claude footer fields. Use `/ps` to inspect background terminals.

## Install

1. Run `codex --version` and check for Codex CLI 0.171.0 or later. Check for Python 3.8 or later on the machine hosting the Codex app server. Git is optional.
2. Copy `assets/statusline.py` from this skill to a stable path on the app-server host, then register it under `codex-rich-statusline`. The commands below use the user Codex directory. Reuse a matching registration. Check with the user before overwriting a provider file they customized.
3. Enable the feature with `codex features enable tui_extensions_statusline` or enable **Custom status line** in `/experimental`. Restart Codex and open a new conversation so its MCP connection picks up the provider.
4. Open `/statusline`, press **Enter** on **Choose a status line provider**, then choose **Rich Codex status line**. Check that the footer updates when changing threads.

### macOS or Linux

```bash
provider_dir="${CODEX_HOME:-$HOME/.codex}/statuslines/codex-rich-statusline"
provider="$provider_dir/statusline.py"
mkdir -p "$provider_dir"
[ -e "$provider" ] || cp "/absolute/path/to/codex-rich-statusline/assets/statusline.py" "$provider"
codex mcp add codex-rich-statusline -- python3 -u "$provider"
```

### Windows PowerShell

```powershell
$python = (Get-Command python.exe -ErrorAction Stop).Source
$codexDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$providerDir = Join-Path $codexDir 'statuslines\codex-rich-statusline'
$provider = Join-Path $providerDir 'statusline.py'
New-Item -ItemType Directory -Path $providerDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $provider)) {
    Copy-Item -LiteralPath 'C:\path\to\codex-rich-statusline\assets\statusline.py' -Destination $provider
}
codex mcp add codex-rich-statusline -- $python -u $provider
```

Registration edits the user `config.toml`. Choosing the provider persists the selection under `tui.status_line_provider`. When working from a sandbox that cannot edit it, run the registration in the user's normal terminal. For a one-launch setup, pass the server and selection as CLI overrides. Use literal TOML strings for absolute paths.

```bash
codex --enable tui_extensions_statusline \
  -c "mcp_servers.codex-rich-statusline={command='python3',args=['-u','/absolute/path/to/statusline.py']}" \
  -c "tui.status_line_provider={server='codex-rich-statusline',tool='statusline'}"
```

## Verify or troubleshoot

- Run `codex mcp get codex-rich-statusline` to verify the registered interpreter and script paths. Send a JSON-RPC `tools/list` request to the script over stdin and check that it advertises `ui://codex-rich-statusline/footer`.
- Open a fresh thread if it is absent from the provider picker. Press **F2** after a provider failure for diagnostic details, then reselect it in `/statusline` to resume polling.
- For color or label changes, edit the constants or `render` in the provider. Restart the Codex session after editing.
- To remove it, select the built-in provider in `/statusline` and run `codex mcp remove codex-rich-statusline`. You can then delete the installed copy under `statuslines/codex-rich-statusline`.

The [Codex provider guide](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/skills/src/assets/samples/create-statusline/SKILL.md) documents the protocol and snapshot contract.
