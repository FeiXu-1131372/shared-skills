# shared-skills

A small collection of reusable AI coding agent skills.

## What's a skill?

A [skill](https://docs.claude.com/en/docs/claude-code/skills) is a folder containing a `SKILL.md` (with YAML frontmatter describing when to trigger and what to do) plus optional bundled scripts and assets. Agents load skill metadata at session start and pull in the body when relevant prompts come in. The format is shared: Claude Code reads `~/.claude/skills`, Factory Droid reads `~/.factory/skills`.

## Skills in this repo

| Skill | What it does |
|---|---|
| [`claude-rich-statusline`](./claude-rich-statusline/) | Installs a feature-rich **Claude Code** status line showing context window %, 5h + weekly rate-limit consumption with reset countdowns, model with its reasoning effort, working directory, git branch, and the generation speed of the latest response (tok/s). Optionally restyles the subagent rows into aligned columns (model and effort, elapsed time, tokens, measured tok/s) with a small mod: `/plugin install rich-agent-rows --marketplace FeiXu-1131372/shared-skills` (Claude Code 2.1.326+). |
| [`codex-rich-statusline`](./codex-rich-statusline/) | Installs a rich **Codex CLI** footer through a local MCP provider. Shows colored context, 5h and weekly usage with reset countdowns, model and reasoning effort, directory, Git branch, and permissions. |
| [`droid-rich-statusline`](./droid-rich-statusline/) | Installs the same style of status line for **Factory Droid**: context window % (from Droid's compaction meter), the Factory plan's 5h / weekly / monthly consumption with reset countdowns, the working directory, and the generation speed of the latest model call (tok/s). Works on macOS, Linux and Windows. |
| [`release-claude-limits-gh`](./release-claude-limits-gh/) | Releases [`FeiXu-1131372/claude-switchboard`](https://github.com/FeiXu-1131372/claude-switchboard) from `main`: updates versions and changelog, waits for CI on the final commit, builds installers in a draft, and verifies assets and updater signatures. Keeps its historical skill name for existing invocations. Specific to that repo — copy & adapt for your own Tauri release flow. |
| [`open-claude-here`](./open-claude-here/) | Windows only. Generates a "Open `<Backend>` Claude Here" Explorer right-click launcher for running Claude Code against an alternate Anthropic-API-compatible backend (GLM, Kimi, DeepSeek, MiniMax presets included, or a custom one) in whichever folder you right-clicked. |
| [`bilingual-ebook-merger`](./bilingual-ebook-merger/) | Combines two single-language epubs of the same book (any language pair) into one bilingual epub that alternates a source paragraph with its translation. Aligns chapter by chapter with subagents, then validates the alignment and the built epub. Needs `beautifulsoup4` and `lxml`; `epubcheck` (with Java) is optional. |
| [`gemini-image`](./gemini-image/) | Generates an image with **your own Gemini Pro subscription** by driving the signed-in Gemini web chat in a headless browser (no API key, no pop-up window) and saves the full-size file. Supports reference photos and several saved Google accounts. macOS, needs Chrome and the `agent-browser` CLI. |
| [`human-cover-letter`](./human-cover-letter/) | Writes, rewrites or reviews a job cover letter so it is short, true, specific and sounds like one real person wrote it. Ships a pattern list of AI tells and two checkers (letter and CV). Defaults to New Zealand spelling and tone. Python standard library only. |
| [`md-to-bilingual-page`](./md-to-bilingual-page/) | Turns a Markdown file plus its translation into one self-contained offline HTML page with an English / 中文 / side-by-side switch, checks that every number, date and hedge survived the translation, and checks the layout in a real browser. The checker's style rules (for example `你` not `您`) are one author's preferences; loosen them in `scripts/check_page.py`. |
| [`rednote-replay-download`](./rednote-replay-download/) | Finds the playback URL of Xiaohongshu (Rednote) livestream replays, live streams, video notes and event pages through your own logged-in Chrome (`agent-browser`), then downloads with `yt-dlp` / `ffmpeg`. |
| [`relay-api-check`](./relay-api-check/) | Tests a third-party LLM relay (base URL + key): auth, model list, Anthropic and OpenAI protocols, and whether real Claude Code and Codex calls work. Writes a report and remembers the endpoint in a local `chmod 600` env file. Python standard library only; instructions are partly in Chinese. |
| [`view-md`](./view-md/) | Opens a local Markdown file in the browser as a clean, readable page, so long reports are easier to read than in the terminal. macOS (`open`); needs `markdown-it-py`. |

Claude Code passes rate limits to its status line script. Codex includes available limits in the thread snapshot it sends to the MCP provider. Factory Droid uses a background worker that reads its credential file and caches usage from Factory's billing limits API.

### Read before you use

Some of these automate other people's services. They are shared as working examples; what you do with them is on you.

- `gemini-image` drives the Gemini consumer web app with your own login. That may not be covered by Google's terms for the app, and anything you type or attach (including reference photos) goes to Google. Use a spare profile if in doubt.
- `rednote-replay-download` saves video the platform does not offer a download button for. Use it for your own content or content you have permission to keep, and follow the platform's terms. The page internals it reads can change without notice.
- `relay-api-check` stores relay keys in a plaintext env file (mode 600) on your machine. Resellers of model access may breach the model vendors' terms; the skill only tests connectivity and does not take a view on that.
- `bilingual-ebook-merger` is for people who already own both editions. It does not touch DRM.

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
