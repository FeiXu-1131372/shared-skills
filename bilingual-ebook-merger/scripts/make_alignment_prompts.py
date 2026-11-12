#!/usr/bin/env python3
"""
Turn each ch<N>_raw.json (produced by extract_paragraphs.py) into a
self-contained prompt file that a subagent can Read and follow to produce a
paragraph-alignment JSON array for that chapter.

Writing the prompt straight into a file (rather than pasting the paragraph
lists into the Task/Agent dispatch call) keeps the orchestrating
conversation's context small — the numbered paragraph lists for a long
chapter can run to tens of thousands of characters.

Usage:
    python3 make_alignment_prompts.py \
        --work-dir work/ \
        --source-lang English \
        --target-lang "Chinese" \
        --book-title "Stoner, by John Williams"
"""
import argparse
import glob
import json
import os
import re

INSTRUCTIONS = """You are aligning paragraphs between two editions of the same book{book_clause} — the {source_lang} edition and the {target_lang} edition, chapter {ch}. Below are two numbered lists of paragraphs in original reading order: SOURCE ({source_lang}) and TARGET ({target_lang}). Some entries show literally "[BREAK]" — this denotes a typographic scene-break (blank space) in that edition, not real content.

Produce a JSON array of alignment groups that together cover ALL entries from both lists exactly once each, in order (indices must be non-decreasing across the array, no repeats, no omissions, both lists fully consumed). Each group has the shape {{"source": [SOURCE indices], "target": [TARGET indices]}}.

Most groups will be one SOURCE index paired with one TARGET index (straightforward 1:1 paragraph correspondence). But translators sometimes split one long paragraph into two, merge two short ones, or reformat quoted verse/poetry into one line per paragraph, so some groups may have multiple indices on one side and one (or more) on the other, e.g. {{"source": [12], "target": [13, 14]}} when SOURCE paragraph 12 corresponds to TARGET paragraphs 13-14, or {{"source": [40, 41], "target": [45]}} when two SOURCE paragraphs correspond to one TARGET paragraph.

A "[BREAK]" entry normally forms its own group with only that single index populated on its side, e.g. {{"source": [], "target": [7]}}, UNLESS a break also appears at the corresponding point in the other language, in which case pair them: {{"source": [3], "target": [3]}} (only if 3 is actually a break in both; otherwise keep separate).

Read the actual paragraph text to judge correct pairing by meaning and content — don't just assume index i in SOURCE maps to index i in TARGET, since the lists drift out of sync once a split/merge happens earlier in the chapter. Position will usually be very close since translations preserve narrative order, but trust content over position when they conflict. If you don't read both languages, use cognates, proper nouns, numbers, dialogue punctuation, and paragraph length/position as evidence — the two lists are always in the same narrative order, so a mismatch is local (nearby), not a full reshuffle.

Output ONLY the JSON array. No explanation, no markdown code fences, no other text.

SOURCE paragraphs ({n_source} total):
{source_list}

TARGET paragraphs ({n_target} total):
{target_list}
"""


def render_list(paras):
    lines = []
    for i, p in enumerate(paras):
        t = "[BREAK]" if p["is_break"] else p["text"]
        t = t.replace("\n", " ")
        lines.append(f"{i}: {t}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--source-lang", required=True, help='e.g. "English"')
    ap.add_argument("--target-lang", required=True, help='e.g. "Chinese"')
    ap.add_argument("--book-title", default=None, help='optional, e.g. "Stoner, by John Williams"')
    args = ap.parse_args()

    book_clause = f" ({args.book_title})" if args.book_title else ""

    raw_files = sorted(glob.glob(os.path.join(args.work_dir, "ch*_raw.json")))
    if not raw_files:
        print(f"No ch*_raw.json files found in {args.work_dir} — run extract_paragraphs.py first.")
        return

    for raw_path in raw_files:
        m = re.search(r"ch(.+)_raw\.json$", os.path.basename(raw_path))
        ch = m.group(1)
        data = json.load(open(raw_path, encoding="utf-8"))
        source_list = render_list(data["source"])
        target_list = render_list(data["target"])
        prompt = INSTRUCTIONS.format(
            book_clause=book_clause,
            ch=ch,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            n_source=len(data["source"]),
            n_target=len(data["target"]),
            source_list=source_list,
            target_list=target_list,
        )
        out_path = os.path.join(args.work_dir, f"ch{ch}_prompt.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"ch{ch}: prompt {len(prompt)} chars -> {out_path}")


if __name__ == "__main__":
    main()
