#!/usr/bin/env python3
"""Install the agent-relay skill into every harness's user skills folder found on this machine.

Usage: python -I install.py [--copy] [--uninstall] [--only claude,codex,opencode,droid,agy]

It links to this skill's folder (a junction on Windows, a symlink elsewhere), so edits reach every harness at once.
agy is the exception: it gets a copy, because it does not list skills behind a junction (agy 1.5.18). Run this
again after editing the skill to refresh that copy. --copy makes copies everywhere.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
NAME = SRC.name
H = Path.home()
TARGETS = {  # harness: (its home, which shows it is installed; its user skills folder)
    "claude": (H / ".claude", H / ".claude/skills"),
    "codex": (H / ".codex", H / ".codex/skills"),
    "opencode": (H / ".config/opencode", H / ".config/opencode/skills"),
    "droid": (H / ".factory", H / ".factory/skills"),
    "agy": (H / ".gemini", H / ".gemini/config/skills"),
}
COPY_ONLY = {"agy"}


def is_link(p):
    if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
        return True
    return os.name == "nt" and p.exists() and os.path.realpath(p) != os.path.abspath(p)  # junction, Python < 3.12


def remove(p):
    if is_link(p):
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", str(p)], check=True)  # removes the junction, never its target
        else:
            p.unlink()
    elif p.exists():
        shutil.rmtree(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--copy", action="store_true", help="copy instead of linking, for every harness")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--only", help="comma-separated harnesses")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else set(TARGETS)
    for kind, (home, skills) in TARGETS.items():
        dest = skills / NAME
        if kind not in only:
            continue
        if not home.exists():
            print(f"{kind:9} skipped: {home} not found")
            continue
        if dest.resolve() == SRC and not is_link(dest):
            print(f"{kind:9} {dest} is the source itself; left alone")
            continue
        if a.uninstall:
            remove(dest)
            print(f"{kind:9} removed {dest}")
            continue
        remove(dest)
        skills.mkdir(parents=True, exist_ok=True)
        if a.copy or kind in COPY_ONLY:
            shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f"{kind:9} copied to {dest}")
        elif os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(dest), str(SRC)], check=True, capture_output=True)
            print(f"{kind:9} linked {dest} -> {SRC}")
        else:
            dest.symlink_to(SRC, target_is_directory=True)
            print(f"{kind:9} linked {dest} -> {SRC}")
    print("Start a new session in each harness to pick the skill up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
