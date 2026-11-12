---
name: view-md
description: Open a local markdown file in the browser as a clean, readable page, so the user can read it comfortably instead of in the terminal. Use whenever the user's message is essentially just a file path or link, usually relative to the project (for example `docs/notes/example-report.md`, a `[report](docs/x.md)` link, a bare file name, or a path with `:12` or `#Heading` on the end), or when they say open / show / view / let me read / 打开 / 给我看 a note, report, spec, plan or .md file. Also use it right after you finish writing a report or markdown document the user will want to read. Do NOT use it when the path comes with a job to do (edit, fix, review, summarise, run, commit): then just do the job.
---

# View a markdown file

The user reads long markdown reports much more comfortably as a rendered page than in the terminal, and the files come from many different folders. So this skill does not rely on any app or vault: it renders the file to a standalone HTML page and opens it in the default browser. It works for any path on the machine.

## Do this

Run the helper from the project directory (the session cwd) with the path exactly as the user wrote it:

```bash
python3 ~/.claude/skills/view-md/scripts/view_md.py "docs/notes/example-report.md"
```

The script handles the fiddly parts: it strips chat decoration (backticks, `[text](path)`, `:line`), resolves a relative path against the cwd and the git root, and falls back to finding a file by its tail or bare name. It then renders the page and opens it. Read the final `RESULT:` line and tell the user in one sentence what opened, with the full source path.

| Exit | Meaning | What to do |
|---|---|---|
| 0 | rendered and opened | Say what opened. Nothing else needed. |
| 2 | file not found | Say so and show where you looked. Don't guess at a similar file. |
| 3 | several files match | List them and ask which one. |
| 6 | `markdown-it-py` missing | Tell the user to run `pip3 install markdown-it-py`. |

Anything that isn't markdown (html, json, a folder) is passed to the macOS default app and the script says so.

## What the page gives the reader

Readable column with a CJK-friendly font and a dark mode, a contents list on the left for wide windows built from the h2/h3 headings, tables, code blocks, checklists, images (resolved relative to the source file), and front matter folded away. Relative links to other `.md` files are rendered too (up to 40 pages), so the user can click from one note to the next and back. A `#Heading` on the end of the path jumps to that section. Scripts inside the markdown are blocked.

Pages are written to `~/.cache/view-md/`, one per source file, and overwritten on each run. A rendered page is a snapshot: after the source changes, run the script again, because reloading the browser tab alone won't pick up the edit.

## Notes

- A markdown link whose path contains a space only works with angle brackets, `[x](<my folder/a.md>)`. That is standard markdown, not a bug in the script.
- To render without opening a browser (checking output, screenshots) pass `--no-open`.
- The page is plain HTML and CSS, so any browser works.
