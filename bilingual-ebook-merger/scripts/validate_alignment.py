#!/usr/bin/env python3
"""
Validate that every ch<N>_alignment.json in a work directory fully and
correctly covers its corresponding ch<N>_raw.json — every source paragraph
index and every target paragraph index must appear exactly once, in
non-decreasing order, across all groups. This is what catches a subagent
mistake (dropped paragraph, duplicated paragraph, reordering) before it gets
baked into the final book.

Tolerates alignment files that got saved with a leading/trailing markdown
code fence (```json ... ```) around the JSON array.

Usage:
    python3 validate_alignment.py --work-dir work/

Exits non-zero if any chapter fails.
"""
import argparse
import glob
import json
import os
import re
import sys


def load_json_tolerant(path):
    raw = open(path, encoding="utf-8").read().strip()
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    args = ap.parse_args()

    raw_files = sorted(glob.glob(os.path.join(args.work_dir, "ch*_raw.json")))
    if not raw_files:
        print(f"No ch*_raw.json files found in {args.work_dir}")
        sys.exit(1)

    all_ok = True
    for raw_path in raw_files:
        m = re.search(r"ch(.+)_raw\.json$", os.path.basename(raw_path))
        ch = m.group(1)
        align_path = os.path.join(args.work_dir, f"ch{ch}_alignment.json")

        if not os.path.exists(align_path):
            print(f"Chapter {ch:>4}: MISSING  (no {align_path})")
            all_ok = False
            continue

        raw = json.load(open(raw_path, encoding="utf-8"))
        try:
            align = load_json_tolerant(align_path)
        except json.JSONDecodeError as e:
            print(f"Chapter {ch:>4}: FAIL  invalid JSON in {align_path}: {e}")
            all_ok = False
            continue

        n_source = len(raw["source"])
        n_target = len(raw["target"])
        source_seen, target_seen = [], []
        for g in align:
            source_seen.extend(g.get("source", []))
            target_seen.extend(g.get("target", []))

        ok = True
        problems = []
        if source_seen != list(range(n_source)):
            ok = False
            expected, got = set(range(n_source)), set(source_seen)
            problems.append(
                f"SOURCE mismatch: missing={sorted(expected - got)} "
                f"dup_or_extra={sorted(got - expected)} "
                f"len_seen={len(source_seen)} vs n_source={n_source}"
            )
            if sorted(source_seen) == list(range(n_source)):
                problems.append("SOURCE indices present but out of order")
        if target_seen != list(range(n_target)):
            ok = False
            expected, got = set(range(n_target)), set(target_seen)
            problems.append(
                f"TARGET mismatch: missing={sorted(expected - got)} "
                f"dup_or_extra={sorted(got - expected)} "
                f"len_seen={len(target_seen)} vs n_target={n_target}"
            )
            if sorted(target_seen) == list(range(n_target)):
                problems.append("TARGET indices present but out of order")

        status = "OK" if ok else "FAIL"
        print(f"Chapter {ch:>4}: {status}  (source {n_source}, target {n_target}, groups {len(align)})")
        for p in problems:
            print("    ", p)
        all_ok = all_ok and ok

    if not all_ok:
        print("\nOne or more chapters failed validation. Re-dispatch the alignment subagent for those "
              "chapters (or fix the JSON by hand) before building the merged epub.")
        sys.exit(1)
    print("\nAll chapters validated OK.")


if __name__ == "__main__":
    main()
