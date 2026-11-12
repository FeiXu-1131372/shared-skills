#!/usr/bin/env python3
"""
List the table of contents of an extracted epub, in reading order, so you can
match chapters between two editions before building a chapter map.

Works with either toc.ncx (epub2) or a nav.xhtml (epub3) — tries both and
prints whichever it finds. Output is "order | title | href" one per line.

Usage:
    python3 list_toc.py /path/to/extracted_epub_root
"""
import sys
import os
import re
import glob
from bs4 import BeautifulSoup


def find_toc_file(root):
    ncx = glob.glob(os.path.join(root, "**", "*.ncx"), recursive=True)
    if ncx:
        return ncx[0], "ncx"
    nav_candidates = glob.glob(os.path.join(root, "**", "nav.xhtml"), recursive=True)
    if nav_candidates:
        return nav_candidates[0], "nav"
    return None, None


def list_ncx(path):
    raw = open(path, encoding="utf-8").read()
    try:
        soup = BeautifulSoup(raw, "xml")
        navpoints = soup.find_all("navPoint")
    except Exception:
        navpoints = []
    if not navpoints:
        # fall back to a parser that doesn't require lxml; tag names get
        # lowercased, so look for "navpoint" instead
        soup = BeautifulSoup(raw, "html.parser")
        navpoints = soup.find_all("navpoint")
    entries = []
    for navpoint in navpoints:
        label_tag = navpoint.find("text")
        content_tag = navpoint.find("content")
        if label_tag is None or content_tag is None:
            continue
        order = navpoint.get("playOrder", "")
        entries.append((order, label_tag.get_text(strip=True), content_tag.get("src", "")))
    return entries


def list_nav(path):
    soup = BeautifulSoup(open(path, encoding="utf-8").read(), "html.parser")
    entries = []
    for i, a in enumerate(soup.find_all("a")):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if href:
            entries.append((str(i), title, href))
    return entries


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 list_toc.py /path/to/extracted_epub_root", file=sys.stderr)
        sys.exit(1)
    root = sys.argv[1]
    path, kind = find_toc_file(root)
    if not path:
        print("No toc.ncx or nav.xhtml found under", root, file=sys.stderr)
        sys.exit(1)
    entries = list_ncx(path) if kind == "ncx" else list_nav(path)
    print(f"# TOC source: {path} ({kind})")
    for order, title, href in entries:
        print(f"{order}\t{title}\t{href}")


if __name__ == "__main__":
    main()
