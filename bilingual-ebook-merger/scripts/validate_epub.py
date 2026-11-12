#!/usr/bin/env python3
"""
Sanity-check a built epub:
  1. Every .xhtml/.html file inside is well-formed XML (epub content must be
     strict XHTML, not just lenient-HTML-parser-acceptable).
  2. If `epubcheck` is installed (`brew install epubcheck`, needs Java), run
     it on the new epub. If --compare-original is given, also run epubcheck
     on that original file, so pre-existing errors in the source book (not
     introduced by this merge) can be told apart from new ones.

epubcheck is optional — if it's not on PATH, this script skips straight to
reporting well-formedness results and says how to install it.

Usage:
    python3 validate_epub.py --epub "/path/to/Bilingual Edition.epub" \\
        --compare-original /path/to/original_target_edition.epub
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from lxml import etree


def check_wellformed(extracted_dir):
    bad = []
    checked = 0
    for f in glob.glob(os.path.join(extracted_dir, "**", "*.xhtml"), recursive=True) + \
              glob.glob(os.path.join(extracted_dir, "**", "*.html"), recursive=True):
        checked += 1
        try:
            etree.parse(f)
        except Exception as e:
            bad.append((f, str(e)))
    return checked, bad


def normalize_error(line):
    # epubcheck embeds the full path to the .epub file being checked in
    # every error line (e.g. "ERROR(RSC-005): /tmp/a/book.epub/OEBPS/..."),
    # so comparing raw lines between two different epub files never matches
    # even when the underlying error is identical. Strip everything between
    # the error code and the last ".epub/" so what remains is just the code,
    # the in-archive path, and the message.
    prefix_end = line.find("): ")
    if prefix_end == -1:
        return line
    code, rest = line[:prefix_end + 3], line[prefix_end + 3:]
    idx = rest.rfind(".epub/")
    if idx != -1:
        rest = rest[idx + len(".epub/"):]
    return code + rest


def run_epubcheck(epub_path):
    try:
        result = subprocess.run(["epubcheck", epub_path], capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return None
    output = result.stdout + result.stderr
    errors = [line for line in output.splitlines() if line.startswith("ERROR")]
    return {"returncode": result.returncode, "errors": errors, "raw": output}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epub", required=True)
    ap.add_argument("--compare-original", default=None, help="path to the original single-language epub, for a baseline error comparison")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        extract_dir = os.path.join(tmp, "extracted")
        with zipfile.ZipFile(args.epub) as zf:
            zf.extractall(extract_dir)
        checked, bad = check_wellformed(extract_dir)

    print(f"Well-formedness: checked {checked} XHTML/HTML files")
    if bad:
        print(f"  {len(bad)} FAILED:")
        for f, e in bad:
            print(f"    {f}: {e}")
    else:
        print("  all well-formed")

    if not shutil.which("epubcheck"):
        print("\nepubcheck not found on PATH — install with `brew install epubcheck` (needs Java) "
              "for a more thorough structural validation. Skipping.")
        sys.exit(1 if bad else 0)

    print(f"\nRunning epubcheck on {args.epub} ...")
    new_result = run_epubcheck(args.epub)
    print(f"  {len(new_result['errors'])} error(s)")
    for e in new_result["errors"]:
        print(f"    {e}")

    if args.compare_original:
        print(f"\nRunning epubcheck on original {args.compare_original} for comparison ...")
        orig_result = run_epubcheck(args.compare_original)
        print(f"  {len(orig_result['errors'])} error(s)")
        new_normalized = {normalize_error(e) for e in new_result["errors"]}
        orig_normalized = {normalize_error(e) for e in orig_result["errors"]}
        new_only = new_normalized - orig_normalized
        if new_only:
            print(f"\n{len(new_only)} error(s) in the new epub NOT present in the original "
                  f"(these were introduced by the merge — investigate):")
            for e in sorted(new_only):
                print(f"    {e}")
        else:
            print("\nNo new errors beyond what the original already had — the merge didn't introduce any regressions.")

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
