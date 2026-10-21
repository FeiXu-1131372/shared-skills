# shared-skills

A small collection of reusable AI coding agent skills.

## What's a skill?

A [skill](https://docs.claude.com/en/docs/claude-code/skills) is a folder containing a `SKILL.md` (with YAML frontmatter describing when to trigger and what to do) plus optional bundled scripts and assets. Agents load skill metadata at session start and pull in the body when relevant prompts come in. The format is shared: Claude Code reads `~/.claude/skills`, Factory Droid reads `~/.factory/skills`.

## Skills in this repo

| Skill | What it does |
|---|---|
| [`claude-rich-statusline`](./claude-rich-statusline/) | Installs a feature-rich **Claude Code** status line showing context window %, 5h + weekly rate-limit consumption with reset countdowns, session duration, model, and git branch. |
| [`droid-rich-statusline`](./droid-rich-statusline/) | Installs the same style of status line for **Factory Droid**: context window % (from Droid's compaction meter), the Factory plan's 5h / weekly / monthly consumption with reset countdowns, and the working directory. Works on macOS, Linux and Windows. |
| [`release-claude-limits-gh`](./release-claude-limits-gh/) | Cuts and publishes a new GitHub release of [`FeiXu-1131372/claude-limits`](https://github.com/FeiXu-1131372/claude-limits) from `main`: bumps the version files, commits, tags, pre-creates the release record so the CI workflow appends bundle assets, and watches the build. Specific to that repo — copy & adapt for your own Tauri release flow. |
| [`open-claude-here`](./open-claude-here/) | Windows only. Generates a "Open `<Backend>` Claude Here" Explorer right-click launcher for running Claude Code against an alternate Anthropic-API-compatible backend (GLM, Kimi, DeepSeek, MiniMax presets included, or a custom one) in whichever folder you right-clicked. |

The two statusline skills are siblings, not duplicates. Claude Code hands its rate limits to the script directly; Droid hands over nothing, so `droid-rich-statusline` ships a small background worker that reads the credential file and polls Factory's billing limits API into a cache. See that skill's `SKILL.md` for the full picture.

## Installing a skill

Pick whichever fits your workflow:

### Option A — Symlink into your skills directory

```bash
git clone https://github.com/FeiXu-1131372/shared-skills.git ~/dev/shared-skills

# Claude Code
ln -s ~/dev/shared-skills/claude-rich-statusline ~/.claude/skills/claude-rich-statusline

# Factory Droid
ln -s ~/dev/shared-skills/droid-rich-statusline ~/.factory/skills/droid-rich-statusline
```

Restart the agent. The skill will appear in the available-skills list and trigger on its description match.

### Option B — Point the agent at the skill folder

Inside a session, give it the path:

```
/skill /path/to/shared-skills/droid-rich-statusline
```

(or just ask the agent to "use the droid-rich-statusline skill at <path>").

### Option C — Install once, throw away the clone

```bash
git clone https://github.com/FeiXu-1131372/shared-skills.git /tmp/shared-skills
# In the agent:
#   "Install the droid-rich-statusline skill from /tmp/shared-skills"
```

The agent reads the SKILL.md, runs the install steps, and you can delete `/tmp/shared-skills` afterwards.

## Contributing

Skills here aim to be:

- **Self-contained** — one folder, no cross-dependencies between skills.
- **Idempotent on install** — if the user already has files in place, the skill asks before overwriting.
- **Honest about side effects** — every file the skill writes or edits is documented in `SKILL.md`.

## License

MIT — see [LICENSE](./LICENSE).
