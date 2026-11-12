---
name: bilingual-ebook-merger
description: Combine two single-language epub editions of the same book (e.g. an English original and its Chinese/Japanese/Spanish/French/etc. translation) into one bilingual epub that alternates a source-language paragraph with its translated counterpart, styled so the two languages are visually distinct. Use this whenever the user has two epub files of the same book in different languages and wants them merged, combined, interleaved, or turned into a "parallel text," "bilingual edition," "中英对照," "对照版," or reading aid for language learning — even if they just say "combine these two ebooks" or "make one book with English then Chinese" without naming the skill directly. Also applies to any language pair, not just English/Chinese.
---

# Bilingual Ebook Merger

Two editions of the same novel almost never have matching paragraph counts
per chapter — translators split long paragraphs, merge short ones, or turn
quoted verse into one line per paragraph. Naively zipping paragraph N of one
edition with paragraph N of the other drifts out of sync the moment counts
diverge, and every paragraph after that point pairs the wrong sentences.
This skill instead aligns each chapter semantically (via one subagent per
chapter, running in parallel) and validates the result before it ever
touches the final book, so the merge is provably complete and in the right
order — not just plausible-looking.

`{baseDir}` below means this SKILL.md's own directory — resolve it to the
actual path before running any script.

## Pipeline

```
epub A ─┐                                                    ┌─→ merged.epub
        ├─ extract_paragraphs.py ─→ per-chapter alignment ───┤
epub B ─┘        (chapter map)     subagents + validation    └─→ validate_epub.py
```

### Step 0 — Clarify scope before doing any heavy lifting

Ask the user (a single AskUserQuestion call covering all three is fine):

1. **Alignment method.** Recommend per-chapter subagent alignment (this
   skill's whole point) over naive sequential 1:1 pairing — mention that
   paragraph counts practically never match exactly, so sequential pairing
   will silently misalign everything after the first drift point.
2. **Scope.** Bilingual for the main chapters only (recommended) vs. also
   trying to interleave shared front matter (intro/dedication) if both
   editions have an equivalent. Whichever edition's front/back matter is
   *not* shared (translator's notes, afterword, etc.) stays untouched either
   way — see Step 5.
3. **Styling.** A subtle visual distinction between the two languages
   (recommended — e.g. one italic/muted, the other normal) vs. no
   distinction at all.

Also ask which edition should serve as the **base scaffold** — i.e. whose
cover, front matter, CSS, and metadata carry over untouched, with only the
chapter bodies rewritten. Default recommendation: whichever edition's prose
is the reader's primary language (the one they'll read first / more
fluently).

### Step 1 — Extract both epubs

An epub is just a zip file:

```bash
mkdir -p /tmp/bilingual-merge/{source_epub,target_epub}
cd /tmp/bilingual-merge/source_epub && unzip -o -q "/path/to/source-language.epub"
cd /tmp/bilingual-merge/target_epub && unzip -o -q "/path/to/target-language.epub"
```

"Source" and "target" here just mean "the two editions" — pick whichever
labeling makes sense (e.g. source = original language, target = translation).
The rest of this skill uses those two names throughout; don't rename them
per-language (no en/zh-specific variable names) since the same pipeline
works for any language pair.

### Step 2 — Build the chapter map

Run `python3 {baseDir}/scripts/list_toc.py <extracted_epub_dir>` on both
editions to print each one's table of contents (title + file href, in
order). The two editions will almost certainly use different filenames
(e.g. `content008.xhtml` vs `Ch1.xhtml`) — match chapters by their title
(roman numerals, "Chapter N", translated chapter titles, etc.), not by
filename or position, since front matter before chapter 1 can differ in
length between editions.

Write the result as `chapter_map.json`, one entry per chapter, in reading
order:

```json
[
  {"chapter": "1", "source_file": "OEBPS/Text/content008.xhtml", "target_file": "OEBPS/Text/Ch1.xhtml"},
  {"chapter": "2", "source_file": "OEBPS/Text/content009.xhtml", "target_file": "OEBPS/Text/Ch2.xhtml"}
]
```

Paths are relative to each edition's extracted root. Skip front/back matter
here — this map only covers the chapters that will become bilingual.

### Step 3 — Extract paragraphs

```bash
python3 {baseDir}/scripts/extract_paragraphs.py \
  --chapter-map chapter_map.json \
  --source-root /tmp/bilingual-merge/source_epub \
  --target-root /tmp/bilingual-merge/target_epub \
  --out-dir work/
```

This writes `work/ch<N>_raw.json` per chapter, with each paragraph's raw
inner HTML (so inline formatting and footnote links survive), its plain
text, and whether it's a typographic break marker (empty paragraph or one
containing only a `<br/>`) rather than real content. It prints a per-chapter
paragraph-count table — skim it for chapters where the two counts differ a
lot (a sign of heavy splitting/merging, or occasionally a sign the chapter
map itself is wrong for that entry).

### Step 4 — Generate alignment prompts

```bash
python3 {baseDir}/scripts/make_alignment_prompts.py \
  --work-dir work/ \
  --source-lang "English" \
  --target-lang "Chinese" \
  --book-title "Stoner, by John Williams"
```

This writes one self-contained `work/ch<N>_prompt.txt` per chapter, each
containing the full alignment instructions plus that chapter's two numbered
paragraph lists. Writing these to disk (instead of pasting paragraph lists
into the subagent dispatch call) keeps your own context small — a long
chapter's two paragraph lists can run to tens of thousands of characters,
and you're about to do this for every chapter at once.

### Step 5 — Dispatch one alignment subagent per chapter, in parallel, in the background

For every chapter in the chapter map, launch a subagent (general-purpose
type is fine) with a prompt like:

> Read the file `work/ch<N>_prompt.txt` in full. It contains instructions
> plus two numbered paragraph lists from the same book chapter. Follow the
> instructions exactly and produce the JSON alignment array it asks for.
> Your final response must be ONLY that JSON array (no prose, no code
> fences, no explanation before or after).

Launch all of them with `run_in_background: true` in the same turn so they
run concurrently rather than one at a time — for a 17-chapter novel this is
the difference between a few minutes and the better part of an hour.

As each chapter's completion notification arrives, write its JSON result
straight to `work/ch<N>_alignment.json` right away — don't hold every
chapter's result in your own conversation waiting for the last one to
finish, especially for a long book. Subagents sometimes wrap the JSON in a
markdown code fence despite instructions not to; strip a leading/trailing
` ```json ... ``` ` before writing the file (or just save it as-is —
`validate_alignment.py` tolerates the fence too).

### Step 6 — Validate the alignment

```bash
python3 {baseDir}/scripts/validate_alignment.py --work-dir work/
```

This confirms that for every chapter, the concatenation of all `"source"`
indices across alignment groups exactly equals every index from 0 to
n_source-1 in order (and likewise for `"target"`) — no paragraph dropped,
duplicated, or reordered. This is the check that catches a subagent mistake
before it's baked into the final book. If a chapter fails, re-dispatch the
alignment subagent for just that chapter (its prompt file is still there)
rather than re-running everything.

If you're curious whether the alignment is actually good (not just
complete), spot-check a chapter with an unusual grouping — e.g. one
`"source"` index mapped to several `"target"` indices is often quoted
verse broken into one line per paragraph in translation, which is exactly
the kind of case naive sequential pairing gets wrong.

### Step 7 — Build and package the merged epub

```bash
python3 {baseDir}/scripts/build_merged_epub.py \
  --work-dir work/ \
  --chapter-map chapter_map.json \
  --base-root /tmp/bilingual-merge/target_epub \
  --base-lang target \
  --merged-dir work/merged_epub \
  --css-file stylesheet.css \
  --output "/path/to/Book Title (Bilingual).epub"
```

`--base-root`/`--base-lang` is whichever edition the user chose in Step 0 to
serve as the scaffold — its cover, metadata, front/back matter, and CSS file
all carry over untouched; only the mapped chapter files get rewritten with
interleaved bilingual paragraphs. `--css-file` is the stylesheet (relative
to the base edition's root) to append the new paragraph classes to — find
it by checking which `.css` the chapter files actually `<link>` to, don't
guess. The script uses sensible default class names/styles (one language
italic and muted gray, the other normal weight) unless overridden — see
`--source-class`/`--target-class`/`--css-block` in its `--help`.

Under the hood it also zips the result correctly: the epub's `mimetype`
entry must be first in the archive and stored with no compression, or some
readers will refuse to open the file — this is handled automatically, not
something to redo by hand.

### Step 8 — Validate the output

```bash
python3 {baseDir}/scripts/validate_epub.py \
  --epub "/path/to/Book Title (Bilingual).epub" \
  --compare-original /path/to/the-base-edition-original.epub
```

This checks every chapter file is well-formed XML (epub content must be
strict XHTML — a file that "looks fine" to a lenient HTML parser can still
break real e-readers) and, if `epubcheck` is installed
(`brew install epubcheck`, needs Java — offer to install it if missing),
runs it against both the new epub and the original base edition. Comparing
against the original is what separates "pre-existing quirks in the source
book" (safe to ignore — not something this merge should try to fix) from
"errors this merge introduced" (must fix before calling it done).

## Troubleshooting

- **A chapter's paragraph counts are wildly different even after excluding
  break markers** (e.g. one has 2x the other): double-check the chapter map
  — this is a common symptom of two chapters being mismatched (off-by-one
  in the chapter list, or a prologue counted as "chapter 1" in only one
  edition).
- **`build_merged_epub.py` prints a `stray element` warning**: some chapter
  has a non-paragraph element (an inline image, an `<hr/>`) sitting between
  two `<p>` tags at the body's top level. It gets dropped from the rebuild
  since it isn't part of either paragraph list. Open that chapter's output
  file and re-insert it by hand if it matters (illustration plates, a
  mid-chapter divider that isn't just a blank line, etc.).
- **The two editions have a different number of chapters** (e.g. one merges
  what the other splits into two): treat that as its own chapter-map entry
  problem — either add a synthetic combined entry pointing both
  `source_file`/`target_file` at a concatenation of the split files, or map
  the extra chapter to itself with the other side left as prose-only. This
  is rarer than within-chapter paragraph splitting and needs a judgment
  call about how the user wants it presented.
