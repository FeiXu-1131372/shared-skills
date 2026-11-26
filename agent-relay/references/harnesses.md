# Harness details (measured 26 Nov 2026 on Windows 11)

Versions tested: Claude Code 2.1.322, Codex CLI 0.171.0, OpenCode 2.2.5, Factory Droid 1.17.2, agy 1.5.18.
Each harness passed four checks:
1. `new`, then `send` with context kept (a code word was recalled on resume);
2. the agent inside the harness ran `whoami` and named its own session correctly;
3. it ran `tell` back to the caller's inbox;
4. it ran `new` into the next harness, in the ring Claude → Codex → OpenCode → Droid → agy → Claude.

## What `--access` maps to

| kind | read | write | full |
|---|---|---|---|
| claude | `--permission-mode default` (tools that need approval are denied in print mode) | `--permission-mode acceptEdits --allowedTools Bash` | `--permission-mode bypassPermissions` |
| codex | `sandbox_mode="read-only"` | `sandbox_mode="workspace-write"`, plus the relay home as a writable root | `sandbox_mode="danger-full-access"` |
| opencode | (no flag: permission asks are refused) | `--auto` | `--auto` |
| droid | (no `--auto`: read-only) | `--auto medium` | `--auto high` |
| agy | `--mode plan` | default mode (runs the commands its policy finds safe) | `--dangerously-skip-permissions` |

Codex always gets `approval_policy="never"` when `--access` is given, because `exec` cannot ask. With no `--access`
on a resumed session, Codex uses its own `config.toml`, which may be full access.

## How an agent finds its own session (used by `whoami`)

| kind | variable set for the agent's tools | folder looked up from |
|---|---|---|
| claude | `CLAUDE_CODE_SESSION_ID` | `~/.claude/projects/*/<id>.jsonl` (`cwd`) |
| codex | `CODEX_THREAD_ID` | `~/.codex/sessions/**/rollout-*<id>.jsonl`, first line |
| opencode | `OPENCODE_SESSION_ID` | `opencode api session.get` → `location.directory` |
| droid | `FACTORY_SESSION_ID` | `~/.factory/sessions/*/<id>.jsonl`, `session_start.cwd` |
| agy | `ANTIGRAVITY_CONVERSATION_ID` | not stored, so the shell's current folder is used |

Child processes inherit their parent's variables. An OpenCode agent started from Claude Code also sees
`CLAUDE_CODE_SESSION_ID`. When several are set, `whoami` picks the harness that is the nearest ancestor process. The
relay also strips these variables, and the harness's tokens, from every agent it starts.

## Faults found and handled

- **OpenCode takes its project folder from `PWD`, not from the process's working folder.** A session started from a
  shell in another folder was filed there. The relay sets `PWD` for every child.
- **Codex's Windows sandbox fails with "os error 3"** when `codex-resources\codex-windows-sandbox-setup.exe` sits
  past `MAX_PATH`: a pnpm global store path was 265 characters. The relay picks a `codex.exe` whose helper path fits.
  It never runs the npm or pnpm `.cmd` shim, because message text through `cmd.exe` is unsafe.
- **Droid `--auto low` cannot run a script** ("insufficient permission"), so `write` uses `medium`.
- **Headless agy denies every command in `--mode accept-edits`.** `--mode auto` is not offered to every account
  ("not available for this account; continuing in the default mode"). The relay reports agy's `denied_actions`
  instead of returning an unexplained empty reply.
- **A model may refuse a relayed request that looks like data extraction.** An OpenCode/DeepSeek agent declined to
  print environment variables when the header claimed an authority it could not check. Keep the header plain, state
  the purpose, and do not claim to speak for the user.

## Long messages

Windows limits a command line to 32,767 characters. A message over 24,000 characters therefore takes a different
route in each harness:
- Claude Code: stdin, always.
- Codex: stdin, with `-` as the prompt.
- Droid: `exec -f <file>`.
- OpenCode: `run -f <file>`, attached to a short message.
- agy: a pointer to a file.

A 34.5k-character message was read correctly by Codex, OpenCode and Droid.

## Compared with acpx (ACP), 26 Nov 2026

The same machine was tested with acpx 0.22.0, a headless Agent Client Protocol client with profiles for all five
harnesses. Out of the box, `claude` and `droid` worked. `codex` needed `--model`. The `opencode` profile ran a
different OpenCode build through `npx`, which refused the shared database. The `antigravity` profile wanted
`agy_acp_server.exe`, and a custom agent command on Windows needs an argv-array config.

A four-party relay panel on "switch the runners to acpx?" voted unanimously to keep the native runners. Its reasons
were native session IDs, real sandboxes behind `--access`, and no Node dependency. It suggested acpx as a test
client, and an opt-in ACP backend for Droid first.

## Session storage, for finding an id by hand

- Claude Code: `~/.claude/projects/<folder slug>/<session id>.jsonl`. Resume runs in that folder.
- Codex: `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<thread id>.jsonl`.
- OpenCode: `opencode session list`, or `opencode api session.get --param sessionID=<id>` (on Git Bash, set
  `MSYS_NO_PATHCONV=1`).
- Droid: `~/.factory/sessions/-<folder with : \ / turned into ->/<id>.jsonl`, with the model in `<id>.settings.json`.
- agy: `~/.gemini/antigravity-cli/conversations/<id>.db`.
