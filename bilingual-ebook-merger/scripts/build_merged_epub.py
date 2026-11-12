#!/usr/bin/env python3
"""
Assemble the final bilingual epub from validated per-chapter alignments, and
package it as a proper .epub file.

Reuses ONE edition's full package (its content.opf, CSS, images, cover,
front/back matter, nav) as the base scaffold, and only rewrites the chapter
body files listed in the chapter map — this sidesteps having to merge
dedications, translator's notes, or other front/back matter that usually
doesn't have a clean 1:1 counterpart between editions anyway.

For each chapter, this script:
  1. Copies the base edition into --merged-dir (once, on first run).
  2. Opens the chapter file (or, for a chapter that's a sub-range of a
     shared multi-chapter "volume" file — see extract_paragraphs.py's
     *_start_id/*_end_id — the shared file, re-opened per chapter), and
     re-locates that exact chapter's original <p> tags (honoring the same
     *_start_id/*_end_id anchors used at extraction time, so this stays in
     sync even after an earlier chapter's rewrite already touched the same
     file). It inserts the new interleaved bilingual content immediately
     before the first of those <p> tags, then removes the original tags.
     Everything else in the file — headings, footnote lists, images, a
     sibling chapter's already-rewritten content — is never touched, so
     there's no "stray element" case to warn about: only the exact
     paragraphs this chapter owns are ever replaced.
  3. Emits one <p class="{source-class}"> per source-language paragraph in
     a group, then one <p class="{target-class}"> per target-language
     paragraph — in that order, per alignment group, in chapter order.
     Break-marker entries become a single <p class="{break-class}"><br/></p>
     instead of a language paragraph.
  4. Appends CSS rules for the three classes to --css-file.

Chapter map entries that share a target_file/source_file (the "volume
file" case) MUST appear in the chapter map in the same order they occur
within that file — each rewrite re-parses the file fresh and finds its own
slice via *_start_id/*_end_id, so an out-of-order entry would look for a
start marker that's already past the current write position.

After all chapters are rewritten, zips --merged-dir into --output, with the
mimetype file first and STORED (uncompressed) as the epub spec requires,
and everything else DEFLATED.

Usage:
    python3 build_merged_epub.py \\
        --work-dir work/ \\
        --chapter-map chapter_map.json \\
        --base-root /path/to/extracted_target_epub \\
        --base-lang target \\
        --merged-dir work/merged_epub \\
        --css-file stylesheet.css \\
        --output "/path/to/Bilingual Edition.epub"

Then separately validate:
    python3 validate_epub.py --epub "/path/to/Bilingual Edition.epub" \\
        --compare-original /path/to/original_target.epub
"""
import argparse
import json
import os
import shutil
import zipfile
from bs4 import BeautifulSoup

DEFAULT_CSS_TEMPLATE = """
.{source_class} {{
  display: block;
  font-family: Serif;
  font-style: italic;
  color: #5a5a5a;
  line-height: 1.6em;
  text-indent: 0;
  text-align: justify;
  margin: 0.8em 0 0.2em 0;
}}
.{target_class} {{
  display: block;
  font-family: Serif;
  line-height: 1.6em;
  text-indent: 2em;
  margin: 0 0 0.2em 0;
}}
.{break_class} {{
  display: block;
  text-align: center;
  margin: 1.2em 0;
}}
"""


def build_chapter_paragraphs(raw, align, source_class, target_class, break_class):
    source_paras = raw["source"]
    target_paras = raw["target"]
    parts = []
    for group in align:
        for i in group.get("source", []):
            p = source_paras[i]
            if p["is_break"]:
                parts.append(f'<p class="{break_class}"><br/></p>')
            else:
                parts.append(f'<p class="{source_class}">{p["raw"]}</p>')
        for j in group.get("target", []):
            p = target_paras[j]
            if p["is_break"]:
                parts.append(f'<p class="{break_class}"><br/></p>')
            else:
                parts.append(f'<p class="{target_class}">{p["raw"]}</p>')
    return "\n".join(parts)


def _is_anchor_only(p_tag):
    # Mirrors extract_paragraphs.py's is_anchor_only(): a <p> whose only
    # content is a single <a id="..."/"> link-target, and nothing else, was
    # dropped entirely at extraction time and won't reappear in the rebuilt
    # paragraph list, so it must not be treated as one of "this chapter's"
    # paragraphs here either.
    text = p_tag.get_text(strip=True)
    if text != "":
        return False
    children = [c for c in p_tag.children if not (isinstance(c, str) and c.strip() == "")]
    return len(children) == 1 and getattr(children[0], "name", None) == "a" and not children[0].find(True)


def select_paragraph_elements(soup, start_id=None, end_id=None, skip_classes=None):
    # Kept in exact lockstep with extract_paragraphs.py's function of the
    # same name (including the same skip_classes filter) — this MUST find
    # the same paragraphs, in the same order, that were extracted. If this
    # ever selects MORE tags than extraction did (e.g. because a
    # --skip-classes value used at extraction time isn't passed here too),
    # this step will decompose paragraphs that were never part of the
    # extracted/aligned content (silently deleting them, such as a
    # translator's endnotes) instead of leaving them untouched.
    skip_classes = set(skip_classes or [])
    if not start_id:
        candidates = soup.find("body").find_all("p")
    else:
        start_marker = soup.find(id=start_id)
        if start_marker is None:
            raise ValueError(f"start id {start_id!r} not found in document")
        end_marker = soup.find(id=end_id) if end_id else None
        if end_id and end_marker is None:
            raise ValueError(f"end id {end_id!r} not found in document")
        candidates = []
        for el in start_marker.find_all_next():
            if end_marker is not None and el is end_marker:
                break
            if getattr(el, "name", None) == "p":
                candidates.append(el)
    candidates = [p for p in candidates if not _is_anchor_only(p)]
    if skip_classes:
        candidates = [p for p in candidates if not (skip_classes & set(p.get("class") or []))]
    return candidates


def rewrite_chapter_file(path, new_paragraphs_html, start_id=None, end_id=None, skip_classes=None):
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    tags = select_paragraph_elements(soup, start_id, end_id, skip_classes)
    if not tags:
        where = f" between id={start_id!r} and id={end_id!r}" if start_id else ""
        raise ValueError(f"No (non-anchor-only) <p> tags found in {path}{where} — can't tell where to insert merged content")

    # Insert the new bilingual content as siblings immediately before this
    # chapter's first original paragraph, then remove the originals. Every
    # other element in the file — the heading, a footnote list, an inline
    # image, a neighboring chapter's own paragraphs in a shared "volume"
    # file — is never touched, since we only ever act on the exact <p> tags
    # this chapter owns.
    new_fragment = BeautifulSoup(new_paragraphs_html, "html.parser")
    tags[0].insert_before(*list(new_fragment.contents))
    for t in tags:
        t.decompose()

    with open(path, "w", encoding="utf-8") as f:
        f.write(str(soup))


def zip_epub(src_dir, out_path):
    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        mimetype_path = os.path.join(src_dir, "mimetype")
        zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        for root, _dirs, files in os.walk(src_dir):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, src_dir)
                if rel == "mimetype":
                    continue
                zf.write(full, rel, compress_type=zipfile.ZIP_DEFLATED)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--chapter-map", required=True)
    ap.add_argument("--base-root", required=True, help="extracted epub dir to use as the scaffold (read-only)")
    ap.add_argument("--base-lang", required=True, choices=["source", "target"],
                     help='whether --base-root is the "source_file" or "target_file" edition in the chapter map')
    ap.add_argument("--merged-dir", required=True, help="working copy of base-root that gets modified")
    ap.add_argument("--css-file", required=True, help="path to stylesheet, relative to --merged-dir, to append rules to")
    ap.add_argument("--output", required=True, help="final .epub path to write")
    ap.add_argument("--source-class", default="bilingual-source")
    ap.add_argument("--target-class", default="bilingual-target")
    ap.add_argument("--break-class", default="bilingual-break")
    ap.add_argument("--css-block", default=None, help="path to a custom CSS file to append instead of the built-in default")
    ap.add_argument("--force", action="store_true", help="overwrite --merged-dir if it already exists")
    ap.add_argument("--skip-classes", default="",
                     help="comma-separated CSS class names excluded at extraction time on the --base-lang side "
                          "(e.g. footnote) — MUST match whatever --source-skip-classes/--target-skip-classes was "
                          "passed to extract_paragraphs.py for this same side, so this script leaves that content "
                          "untouched instead of deleting it")
    args = ap.parse_args()

    skip_classes = [c.strip() for c in args.skip_classes.split(",") if c.strip()]
    chapter_map = json.load(open(args.chapter_map, encoding="utf-8"))

    if os.path.exists(args.merged_dir):
        if not args.force:
            print(f"{args.merged_dir} already exists. Pass --force to overwrite, "
                  f"or point --merged-dir somewhere fresh.")
            return
        shutil.rmtree(args.merged_dir)
    shutil.copytree(args.base_root, args.merged_dir)

    file_key = f"{args.base_lang}_file"
    id_prefix = args.base_lang  # "source" or "target" — matches *_start_id/*_end_id keys
    for entry in chapter_map:
        ch = entry["chapter"]
        raw = json.load(open(os.path.join(args.work_dir, f"ch{ch}_raw.json"), encoding="utf-8"))
        align = json.load(open(os.path.join(args.work_dir, f"ch{ch}_alignment.json"), encoding="utf-8"))
        new_html = build_chapter_paragraphs(raw, align, args.source_class, args.target_class, args.break_class)
        chapter_path = os.path.join(args.merged_dir, entry[file_key])
        start_id = entry.get(f"{id_prefix}_start_id")
        end_id = entry.get(f"{id_prefix}_end_id")
        rewrite_chapter_file(chapter_path, new_html, start_id, end_id, skip_classes)
        print(f"Chapter {ch}: rewrote {chapter_path}" + (f" [{start_id}:{end_id}]" if start_id else ""))

    css_path = os.path.join(args.merged_dir, args.css_file)
    if args.css_block:
        css_addition = open(args.css_block, encoding="utf-8").read()
    else:
        css_addition = DEFAULT_CSS_TEMPLATE.format(
            source_class=args.source_class, target_class=args.target_class, break_class=args.break_class
        )
    with open(css_path, "a", encoding="utf-8") as f:
        f.write(css_addition)
    print(f"Appended bilingual CSS rules to {css_path}")

    zip_epub(args.merged_dir, args.output)
    print(f"\nWrote {args.output} ({os.path.getsize(args.output)} bytes)")
    print("Next: run validate_epub.py to sanity-check the result.")


if __name__ == "__main__":
    main()
