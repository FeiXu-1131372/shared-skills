#!/usr/bin/env python3
"""
Extract ordered paragraph lists from matching chapter files in two extracted
epubs, ready for cross-language alignment.

For every chapter listed in the chapter map, pulls every <p> out of the
<body> of both the source-language file and the target-language file, and
records for each paragraph:
  - "raw":  the original inner HTML (so inline formatting / footnote links
            survive into the merged book untouched)
  - "text": plain text, for a human or subagent to read when aligning
  - "is_break": True for a paragraph that is empty or contains only a <br/>
            (a typographic scene break, not real content)

Purely structural anchor-only paragraphs (e.g. <p><a id="anchor..."/></p>,
used by some epub tools to mark link targets) are dropped entirely — they
carry no signal, not even a break marker.

Some editions (particularly ones converted from Word/PDF by a low-quality
tool) litter an empty, content-free <p/> after nearly EVERY real paragraph
as a markup artifact, not a deliberate scene break — this script's summary
table will show a break count close to the real-paragraph count for that
side (e.g. 162 breaks across 322 total, versus a normal book's handful of
breaks per chapter). Rendering one of those as a visual "scene break" after
every single paragraph would make the merged book unreadable. Pass
--source-drop-empty and/or --target-drop-empty to discard empty paragraphs
on that side entirely (as if they were anchor-only) instead of preserving
them as break markers, once you've confirmed by eye that they're noise and
not real widely-spaced scene dividers.

Some editions also render translator footnotes as ordinary <p class="...">
elements at the body level (often styled e.g. class="footnote") rather than
in a <ol>/<li> list — those never got picked up by find_all("p") in an
older version of this script only because they happened to be excluded by
a chapter boundary; the LAST chapter of a shared multi-chapter file (see
*_start_id/*_end_id below) has no such boundary on its far side, so its
"through the end of the file" range can silently swallow a whole book's
worth of endnotes as if they were that chapter's own narrative paragraphs
(inflating its paragraph count far beyond what any real translation-split
would explain — a red flag alongside the break-density warning). Pass
--source-skip-classes/--target-skip-classes with a comma-separated list of
CSS class names (e.g. "footnote") to exclude any <p> carrying one of those
classes entirely, the same way anchor-only paragraphs are excluded.

Chapter map format (JSON), one entry per chapter, in reading order:
    [
      {"chapter": "1", "source_file": "OEBPS/Text/content008.xhtml",
                        "target_file": "OEBPS/Text/Ch1.xhtml"},
      {"chapter": "2", "source_file": "OEBPS/Text/content009.xhtml",
                        "target_file": "OEBPS/Text/Ch2.xhtml"},
      ...
    ]
File paths are relative to --source-root / --target-root respectively.

Some editions (especially omnibus/"volume" epubs of classic novels) pack
MULTIPLE chapters into one file instead of one file per chapter — e.g. a
translated edition with 5 giant "Book N" files, each containing a dozen-plus
chapters marked only by internal <h2>/<h3> headings. To handle that, an
entry may add optional *_start_id / *_end_id keys naming the `id` attribute
of the heading element that starts (and, optionally, the one that starts
the NEXT chapter and therefore ends this one) that language's slice of the
shared file:
    {"chapter": "8", "source_file": "content/split_10.html",
                      "target_file": "OEBPS/Text/chapter4.xhtml",
                      "target_start_id": "c008", "target_end_id": "c009"}
Only paragraphs strictly between target_start_id (exclusive) and
target_end_id (exclusive) are extracted for that chapter. Omit *_end_id on
the last chapter of a shared file to mean "through the end of the file".
Omit *_start_id/*_end_id entirely (as in the simple example above) to mean
"the whole file is this one chapter" — the common case, and fully backward
compatible with chapter maps that don't use this feature at all.

Usage:
    python3 extract_paragraphs.py \
        --chapter-map chapter_map.json \
        --source-root /path/to/extracted_source_epub \
        --target-root /path/to/extracted_target_epub \
        --out-dir work/
"""
import argparse
import json
import os
from bs4 import BeautifulSoup


def is_anchor_only(p_tag, text):
    if text != "":
        return False
    children = [c for c in p_tag.children if not (isinstance(c, str) and c.strip() == "")]
    if len(children) == 1 and getattr(children[0], "name", None) == "a" and not children[0].find(True):
        return True
    return False


def select_paragraph_elements(soup, start_id=None, end_id=None):
    """Return the ordered list of "real" (non-anchor-only) <p> tags that
    make up one chapter's content: either the whole document body (when no
    start_id is given — the common one-file-per-chapter case), or just the
    slice strictly between start_id (exclusive) and end_id (exclusive, or
    end of document if end_id is None) — for a chapter that's a sub-range
    of a shared multi-chapter file."""
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
    return [p for p in candidates if not is_anchor_only(p, p.get_text(strip=True))]


def parse_paragraphs(filepath, start_id=None, end_id=None, drop_empty=False, skip_classes=None):
    with open(filepath, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    skip_classes = set(skip_classes or [])
    paras = []
    for p in select_paragraph_elements(soup, start_id, end_id):
        if skip_classes and skip_classes & set(p.get("class") or []):
            continue
        # Some editions (the same malformed Word/PDF-to-epub conversions that
        # litter empty sibling <p/> artifacts — see --source-drop-empty above)
        # also leave a <p> nested INSIDE another <p>'s content, which is never
        # valid HTML/XHTML. A lenient parser silently auto-closes the outer
        # <p> when it hits the nested one, but re-wrapping that same inner
        # HTML in a fresh <p class="..."> for the merged book reproduces the
        # nesting literally and produces invalid, unpredictable-to-render
        # markup. Flatten any nested <p> into its parent's content before
        # extracting — this only removes the (invalid) tag boundary, it does
        # not drop any text the nested <p> contained.
        for nested_p in p.find_all("p"):
            nested_p.unwrap()
        # Word-exported HTML routinely gives <a> tags both id="..." (still
        # valid) and a legacy name="..." (obsolete outside <a name> used as
        # a pre-HTML5 link target). Some XHTML doctypes reject "name" on <a>
        # outright; since the id already serves as the anchor and nothing in
        # the merged book ever links via the old name, drop it rather than
        # letting an edition-specific legacy attribute fail validation in a
        # document with a different, stricter doctype.
        for a in p.find_all("a"):
            if a.has_attr("name"):
                del a["name"]
        text = p.get_text(strip=True)
        if text == "" and drop_empty:
            continue
        paras.append({
            "raw": p.decode_contents(),
            "text": text,
            "is_break": text == "",
        })
    return paras


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapter-map", required=True)
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--target-root", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source-drop-empty", action="store_true",
                     help="discard empty paragraphs on the source side entirely instead of keeping them as break markers")
    ap.add_argument("--target-drop-empty", action="store_true",
                     help="discard empty paragraphs on the target side entirely instead of keeping them as break markers")
    ap.add_argument("--source-skip-classes", default="",
                     help="comma-separated CSS class names (e.g. footnote) to exclude entirely on the source side")
    ap.add_argument("--target-skip-classes", default="",
                     help="comma-separated CSS class names (e.g. footnote) to exclude entirely on the target side")
    args = ap.parse_args()

    source_skip = [c.strip() for c in args.source_skip_classes.split(",") if c.strip()]
    target_skip = [c.strip() for c in args.target_skip_classes.split(",") if c.strip()]

    chapter_map = json.load(open(args.chapter_map, encoding="utf-8"))
    os.makedirs(args.out_dir, exist_ok=True)

    print(f"{'chapter':>10}  {'source paras':>12}  {'target paras':>12}  {'src breaks':>10}  {'tgt breaks':>10}")
    high_density_warnings = []
    for entry in chapter_map:
        ch = entry["chapter"]
        source_path = os.path.join(args.source_root, entry["source_file"])
        target_path = os.path.join(args.target_root, entry["target_file"])
        source_paras = parse_paragraphs(source_path, entry.get("source_start_id"), entry.get("source_end_id"), args.source_drop_empty, source_skip)
        target_paras = parse_paragraphs(target_path, entry.get("target_start_id"), entry.get("target_end_id"), args.target_drop_empty, target_skip)

        data = {"chapter": ch, "source": source_paras, "target": target_paras}
        out_path = os.path.join(args.out_dir, f"ch{ch}_raw.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

        n_src_breaks = sum(1 for p in source_paras if p["is_break"])
        n_tgt_breaks = sum(1 for p in target_paras if p["is_break"])
        print(f"{ch:>10}  {len(source_paras):>12}  {len(target_paras):>12}  {n_src_breaks:>10}  {n_tgt_breaks:>10}")

        for label, n_breaks, n_total, dropped in (
            ("source", n_src_breaks, len(source_paras), args.source_drop_empty),
            ("target", n_tgt_breaks, len(target_paras), args.target_drop_empty),
        ):
            if not dropped and n_total > 0 and n_breaks / n_total > 0.15:
                high_density_warnings.append((ch, label, n_breaks, n_total))

    if high_density_warnings:
        print(f"\nWARNING: {len(high_density_warnings)} chapter/side combination(s) have break markers making up "
              f">15% of paragraphs — this usually means markup noise (a bad Word/PDF-to-epub conversion leaving an "
              f"empty <p/> after every real paragraph), not real scene breaks. Inspect one with e.g.:\n"
              f'  python3 -c "import json; d=json.load(open(\'{args.out_dir}/ch<N>_raw.json\')); '
              f'[print(i, p[\'text\'][:60] or \'BREAK\') for i,p in enumerate(d[\'<source|target>\'][:20])]"\n'
              f"If it's noise, rerun with --source-drop-empty/--target-drop-empty rather than proceeding — "
              f"otherwise every chapter will get a visual scene-break after nearly every paragraph:")
        for ch, label, n_breaks, n_total in high_density_warnings:
            print(f"    chapter {ch} ({label}): {n_breaks}/{n_total} paragraphs are breaks")


if __name__ == "__main__":
    main()
