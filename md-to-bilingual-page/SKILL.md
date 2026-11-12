---
name: md-to-bilingual-page
description: Turn a Markdown file (a report, plan, design, research note, or anything another agent wrote) into one self-contained local HTML page in Chinese and English with a three-way switch (English, 中文, 中英对照, which opens first), then check it in a real browser and open it. Use whenever the user asks to make a .md file readable, turn it into a page, artifact, webpage or HTML, wants it in Chinese and English, or says 双语, 中英文, 做成网页, 做成页面, 转成 HTML or make an artifact from this report, even if they don't say bilingual. Use this instead of publishing to claude.ai, because the result stays a local file. Not for translating a file when no page is wanted (use baoyu-translate), and not for building a designed website or a one-off explainer with custom diagrams.
---

# Markdown to bilingual page

Turns one Markdown file into one HTML file that holds both languages, with a three-way switch at the top: English, 中文 and 中英对照. **中英对照 is the default view.** In it each paragraph and list item sits beside its translation: Chinese on the left and English on the right on a wide screen, the English straight after the Chinese on a phone. Tables, code and figures always stack, Chinese first. The page works offline, in light and dark, from a 320 px phone to a desktop. Long tables become labelled stacks on a phone, and evidence labels such as `[RUN]` become small chips.

The source file is never edited, and nothing is published. The scripts need only Python 3.9+. The browser check needs `agent-browser`.

`SKILL` below means this skill's folder.

## Do this

Don't ask the user anything along the way. Take the defaults here and say what you chose in the final report.

### 1. Read the source, whole

Find the file: the path given, or the Markdown the conversation is about. Work out its language. Whichever of Chinese and English it isn't is the language to write.

Decide the names, next to the source: `report.md` gets `report.zh.md` (or `report.en.md` if the source is Chinese) and `report.html`. If the source is in the session scratchpad, put all three in `~/claude-artifacts/` instead, because the scratchpad gets wiped.

If `report.html` already exists and wasn't built by this skill, keep it and use `report-bilingual.html`. If the translation already exists and the source has changed, update only the paragraphs that changed.

### 2. Write the other language

Read `SKILL/references/translation-brief.md` and follow it. It covers the file's shape, what stays byte for byte, the voice, Chinese typography, and how to gloss jargon for the reader.

For a source under about 2,000 words, write it yourself. For a longer one, send it to one subagent on a mid-size model (for example `model: "sonnet"`): translating is careful but ordinary work. Give it the source path, the output path and the brief's path, and tell it to use the Write tool. One subagent is enough, and don't split the file into chunks. When it reports back, read a good sample of the Chinese yourself.

### 3. Build

```bash
python3 -I SKILL/scripts/build_page.py --en report.md --zh report.zh.md --out report.html
```

If the source is Chinese, add `--source zh`. The page opens in 中英对照. `--default zh` or `--default en` opens it in one language instead, and the reader can still switch. Read every `WARNING` the build prints and deal with it. A warning that the two languages "don't pair block by block" means a paragraph was merged or split in the translation: fix the translation so both files have the same blocks, then rebuild.

### 4. Check the facts and the shape

```bash
python3 -I SKILL/scripts/check_page.py --en report.md --zh report.zh.md --page report.html
```

Fix every `FAIL` in the translation, never in the source, then rebuild. Judge every `REVIEW` line: fix it, or leave it if it's right. A `REVIEW` about parts that "could not be paired" is the same pairing problem as the build warning, so fix it too. Repeat until there are 0 hard failures.

The check holds each heading, paragraph, list item and table cell against its partner, so a changed number, a number moved to another row, a changed amount, changed or moved code, a changed link and an emptied cell all fail. It can't read meaning: a dropped hedge, a softened verdict or an added sentence passes. So read the translation against the source yourself as well, paragraph by paragraph, and in the report say the check covers facts and shape, not wording.

### 5. Look at it

```bash
python3 -I SKILL/scripts/look.py report.html --out <temp folder>/look
```

`<temp folder>` is the session's scratchpad if the environment gives one, otherwise a new folder under the system's temp directory. The screenshots never go next to the source. A long page takes a few minutes, so give the command a 5-minute timeout.

Fix each `PROBLEM` line. Then open the images it lists with the Read tool and really look. Passing numbers say nothing about whether a page reads well. Look at every sheet of the 中英对照 view at 375, since that is what the reader sees first, and at least the top of the 中英对照 view at 1280, where the two languages sit in columns and each Chinese block must be level with its own English. Then look at the top, a table-heavy section and the end of the 中文 and English sets, walking each as the reader would. Watch for a Chinese block next to the wrong English, squeezed table columns, broken words, a heading alone at the bottom of a screen, and anything that reads as translated.

If `agent-browser` isn't installed, use another real browser, or say plainly that the page wasn't looked at.

If a flaw comes from the page template rather than the translation (the stylesheet, the build script, the way a table stacks), don't patch the skill in the middle of someone else's task. Finish the page, and list the flaw in the report so the skill can be fixed separately.

### 6. Hand it over

Run `open <full path>`, unless you are a subagent or the task says not to. Give the full path and report in a few lines:

- what you built (it opens in 中英对照), and the model that wrote the translation
- check results: hard failures, and any `REVIEW` line you left and why
- anything still wrong or unverified
- one line offering to publish the page to claude.ai

## When the page needs more than the source has

Most sources need nothing extra. Two cases are worth the effort:

- **The source buries its conclusion.** A reader should get the answer first. Add a short summary at the top, built only from facts in the source.
- **The source has an ASCII diagram, or a comparison that reads better as a picture.** Replace it with a hand-drawn inline SVG in a `<figure>`, with `role="img"`, an `aria-label` and a `<figcaption>`, in each language. Use `currentColor` so it works in dark mode. Scripts and event handlers are shown as text, not run.

Never put these in the source. Copy it to `report.page.md`, make the additions there and in `report.page.zh.md`, and build from those two with `--source-name report.md`, so the footer still names the original.

## Rules that don't bend

- **Local first.** Never publish to claude.ai on your own initiative. A yes from the user covers that one page, and only then call the publish tool.
- **The source stays as it was.** Never edit, reformat or "fix" it. If it has a mistake, report the mistake.
- **No new branches, worktrees, commits or pushes** unless the user asks.
- **Facts stay facts.** Don't soften, sharpen, round or add. If something in the source looks wrong, leave it and say so in the report.
- **No secrets.** If the source quotes a token, password or key, stop and tell the user before building a page from it.
