---
name: open-claude-here
description: Generate a Windows Explorer right-click launcher ("Open <Backend> Claude Here") that opens Claude Code in the clicked folder against an alternate Anthropic-API-compatible backend (GLM, Kimi, DeepSeek, MiniMax presets included, or a fully custom one). Use when the user wants a right-click/context-menu shortcut to launch Claude Code with a specific backend in a specific folder, or mentions GLM/Kimi/DeepSeek/MiniMax together with Claude Code and "right-click"/"context menu"/"Explorer".
user-invokable: true
args:
  - name: backend
    description: Which backend to generate a launcher for. One of the built-in presets (glm, kimi, deepseek, deepseek-flash, minimax) or `custom`.
    required: false
---

# Open Claude Here

Windows-only. Generates a per-backend `.bat` launcher plus matching Explorer
right-click context-menu (`.reg`) entries, so you can right-click any folder
(or empty space inside one) and open Claude Code there, pointed at a chosen
Anthropic-API-compatible backend instead of the default Anthropic API.

All the real work is done by `assets/New-ClaudeHereLauncher.ps1` — a
deterministic generator, not something re-derived by hand each time.

## Built-in presets

| Backend | `-BackendName` | `-BaseUrl` | `-Model` | `-SmallFastModel` |
|---|---|---|---|---|
| GLM | `GLM` | `https://api.z.ai/api/anthropic` | `glm-5.2[1m]` | `glm-5-turbo` |
| Kimi | `Kimi` | `https://api.kimi.com/coding/` | `k3[1m]` | `kimi-for-coding-highspeed` |
| DeepSeek | `DeepSeek` | `https://api.deepseek.com/anthropic` | `deepseek-v4-pro[1m]` | `deepseek-v4-flash` |
| DeepSeek-Flash | `DeepSeek-Flash` | `https://api.deepseek.com/anthropic` | `deepseek-v4-flash[1m]` | `deepseek-v4-flash[1m]` |
| MiniMax | `MiniMax` | `https://api.minimaxi.com/anthropic` | `MiniMax-M2.7-highspeed` | `MiniMax-M2.7-highspeed` |

These cover the common case. Some backends support extra tuning env vars
(e.g. DeepSeek's `CLAUDE_CODE_EFFORT_LEVEL`, `CLAUDE_CODE_SUBAGENT_MODEL`) —
the generator only writes the common var set shared by all backends; add
anything backend-specific by hand-editing the generated `.bat` afterward.

For a backend not listed, use `custom`: ask the user for a name, base URL,
and model id(s) directly.

## Steps

1. **Determine the backend.** Use `args.backend` if given, otherwise ask the
   user which preset (or `custom`).
2. **Get the API token.** Always ask the user for it directly in
   conversation — never invent or reuse one from elsewhere. Pass it to the
   script via `-AuthToken`.
3. **Determine the target folder** — where the generated `.bat`/`.reg` files
   should live (e.g. wherever the user already keeps similar launcher
   scripts). Ask if unclear; don't assume.
4. **Run the generator**, always passing `-AuthToken` explicitly:

   ```powershell
   pwsh assets/New-ClaudeHereLauncher.ps1 `
     -BackendName "GLM" `
     -BaseUrl "https://api.z.ai/api/anthropic" `
     -Model "glm-5.2[1m]" `
     -SmallFastModel "glm-5-turbo" `
     -AuthToken "<token from the user>" `
     -TargetDir "C:\path\to\scripts\folder"
   ```

   Omit `-SmallFastModel` to reuse `-Model` for it. Add `-Force` only if the
   user has confirmed overwriting an existing same-named launcher.

   **Never rely on the script's interactive token prompt when calling it
   from an agent context** — Claude Code's shell tools run non-interactively
   (no stdin), so the `Read-Host` fallback in the script will hang if
   `-AuthToken` is omitted. That fallback exists solely for a human running
   the script by hand from a real console.

5. **Report the next step to the user**: double-click the generated
   `Add-Claude-Context-Menu.reg` in the target folder to install the menu
   entries (HKCU scope, no admin needed, one-time per machine). The skill
   does not import the `.reg` itself — registry writes are left as an
   explicit, visible action for the user to take.

## Side effects (every run)

- Writes `<Backend>-Claude-Here.bat` to the target folder — **contains the
  API token in plaintext.** This file must never be committed to a shared
  or public repo; keep it local only.
- Creates or appends to `Add-Claude-Context-Menu.reg` and
  `Uninstall-Claude-Context-Menu.reg` in the target folder — no secrets in
  these, they only reference the `.bat` file's path. Safe to share, though
  there's rarely a reason to.
- Does **not** touch the Windows registry directly. Nothing is installed
  until the user double-clicks the `.reg` file themselves.
- Idempotent: if a launcher for that backend name already exists, the
  script asks before overwriting (or skips, without `-Force`). If that
  backend's context-menu entries are already registered, it leaves them
  alone rather than duplicating them.

## Uninstalling

Double-click `Uninstall-Claude-Context-Menu.reg` in the target folder to
remove exactly the menu entries this skill added. It doesn't delete the
`.bat` files — remove those manually if desired.
