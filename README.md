# shared-skills

A small collection of reusable Claude Code skills.

## What's a skill?

A [skill](https://docs.claude.com/en/docs/claude-code/skills) is a folder containing a `SKILL.md` (with YAML frontmatter describing when to trigger and what to do) plus optional bundled scripts and assets. Claude Code loads skill metadata at session start and pulls in the body when relevant prompts come in.

## Skills in this repo

| Skill | What it does |
|---|---|
| [`claude-rich-statusline`](./claude-rich-statusline/) | Installs a feature-rich Claude Code status line showing context window %, 5h + weekly rate-limit consumption with reset countdowns, session duration, model, and git branch. |
| [`release-claude-limits-gh`](./release-claude-limits-gh/) | Cuts and publishes a new GitHub release of [`FeiXu-1131372/claude-limits`](https://github.com/FeiXu-1131372/claude-limits) from `main`: bumps the version files, commits, tags, pre-creates the release record so the CI workflow appends bundle assets, and watches the build. Specific to that repo — copy & adapt for your own Tauri release flow. |
| [`open-claude-here`](./open-claude-here/) | Windows only. Generates a "Open `<Backend>` Claude Here" Explorer right-click launcher for running Claude Code against an alternate Anthropic-API-compatible backend (GLM, Kimi, DeepSeek, MiniMax presets included, or a custom one) in whichever folder you right-clicked. |

## Installing a skill

Pick whichever fits your workflow:

### Option A — Symlink into your Claude Code skills directory

```bash
git clone https://github.com/FeiXu-1131372/shared-skills.git ~/dev/shared-skills
ln -s ~/dev/shared-skills/claude-rich-statusline ~/.claude/skills/claude-rich-statusline
```

Restart Claude Code. The skill will appear in `available_skills` and trigger on its description match.

### Option B — Tell Claude Code to use it directly

Inside a Claude Code session, point it at the skill folder:

```
/skill /path/to/shared-skills/claude-rich-statusline
```

(or just ask Claude Code to "use the claude-rich-statusline skill at <path>").

### Option C — Install once, throw away the clone

For one-off use of `claude-rich-statusline`:

```bash
git clone https://github.com/FeiXu-1131372/shared-skills.git /tmp/shared-skills
# In Claude Code:
#   "Install the claude-rich-statusline skill from /tmp/shared-skills"
```

Claude Code will read the SKILL.md, run the install steps, and you can delete `/tmp/shared-skills` afterwards.

## Contributing

Skills here aim to be:

- **Self-contained** — one folder, no cross-dependencies between skills.
- **Idempotent on install** — if the user already has files in place, the skill asks before overwriting.
- **Honest about side effects** — every file the skill writes or edits is documented in `SKILL.md`.

## License

MIT — see [LICENSE](./LICENSE).
