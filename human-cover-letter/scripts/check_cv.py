#!/usr/bin/env python3
"""Check a CV (plain text, Markdown or .docx) against NZ/AU CV rules and machine-sounding patterns.

Usage: check_cv.py cv.docx [--ad ad.txt]
       check_cv.py cv.txt

Prints sections found, length, long entries, skills size, buzzwords and AI patterns, and (with --ad)
which technology terms in the ad do not appear on the CV. A flag means "look here", not "wrong".
Exit code is always 0.
"""
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_letter import PHRASES, TAILS, NOT_BUT, AMERICAN  # noqa: E402

CV_PHRASES = [
    r"responsible for", r"duties (included|include)", r"worked on", r"helped with", r"assisted (with|in)",
    r"hard[- ]?working", r"detail[- ]oriented", r"self[- ]starter", r"proven track record",
    r"excellent (communication|interpersonal)", r"fast learner", r"quick learner", r"think outside the box",
    r"dynamic", r"motivated", r"enthusiastic", r"strong (work ethic|communicator)",
]
SECTIONS = {
    "summary": r"^(summary|profile|personal statement|about me)$",
    "skills": r"^(key skills|skills|core skills|technical skills)$",
    "experience": r"^(experience|work history|employment|work experience|professional experience)$",
    "education": r"^(education|qualifications|education and qualifications)$",
    "referees": r"^(referees|references)$",
}


def load(path):
    if path.lower().endswith(".docx"):
        x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "ignore")
        out = []
        for p in re.findall(r"<w:p[ >].*?</w:p>", x, re.S):
            t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
            if t.strip():
                out.append(re.sub(r"<[^>]+>", "", t))
        return "\n".join(out)
    return open(path, encoding="utf-8").read()


def split_sections(lines):
    cur, got = None, {}
    for ln in lines:
        s = ln.strip().strip("#* ").lower()
        hit = next((k for k, pat in SECTIONS.items() if re.match(pat, s)), None)
        if hit:
            cur = hit
            got.setdefault(cur, [])
            continue
        if cur:
            got[cur].append(ln)
    return got


def tech_terms(text):
    pats = [r"\b[A-Z][A-Za-z]*[A-Z0-9][A-Za-z0-9]*\b", r"\bC#|\bF#|\.NET\b", r"\b[A-Z]{2,}\b",
            r"\b(Angular|React|Docker|Kubernetes|Azure|AWS|Python|Terraform|Snowflake|PostgreSQL|Blazor|Kafka|RabbitMQ|GraphQL|Node\.js|TypeScript|JavaScript|Redis|MongoDB|Java|Go|Rust)\b"]
    found = set()
    for p in pats:
        for m in re.finditer(p, text):
            found.add(m.group(0))
    return found


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    ad = None
    if "--ad" in argv:
        ad = open(argv[argv.index("--ad") + 1], encoding="utf-8").read()
        args = [a for a in args if a != argv[argv.index("--ad") + 1]]
    if not args:
        print(__doc__)
        return 0
    text = load(args[0])
    lines = [l for l in text.splitlines() if l.strip()]
    words = re.findall(r"\S+", text)
    sec = split_sections(lines)
    low = text.lower()

    print(f"Words: {len(words)} (two pages is about 600 to 900)" + ("   <-- long" if len(words) > 950 else ""))
    print("Sections found: " + ", ".join(k for k in SECTIONS if k in sec) or "none")
    missing = [k for k in SECTIONS if k not in sec]
    if missing:
        print("Sections missing: " + ", ".join(missing))

    summ = " ".join(sec.get("summary", []))
    sw = len(summ.split())
    if summ:
        first = re.split(r"(?<=[.!?])\s+", summ.strip())[0]
        print(f"Summary: {sw} words (aim 50 to 100). First sentence: {first[:120]}")
        n_i = len(re.findall(r"\bI\b", summ))
        print(f"  First-person 'I' in summary: {n_i}")

    skills = sec.get("skills", [])
    items = sum(len([i for i in re.split(r",|;", re.sub(r"\([^)]*\)", "", l.split(":", 1)[-1])) if i.strip()]) for l in skills)
    print(f"Key skills: {len(skills)} lines, about {items} items (a short list the ad's words lead is easier to read; over 30 items is a lot)")

    long_entries = [(len(l.split()), l.strip()) for l in sec.get("experience", []) + sec.get("education", []) if len(l.split()) > 30]
    if long_entries:
        print("Long experience lines (over 30 words; one idea per bullet):")
        for n, l in long_entries:
            print(f"  {n}: {l[:100]}...")
    pron = [l.strip() for l in sec.get("experience", []) if re.search(r"\bI\b", l)]
    if pron:
        print(f"Experience lines with 'I' ({len(pron)}); CV bullets usually start with a verb. e.g. {pron[0][:80]}...")

    flags = set()
    for p in PHRASES + CV_PHRASES:
        for m in re.finditer(p, low):
            flags.add(("phrase", m.group(0)))
    for m in re.finditer(TAILS, low):
        flags.add(("-ing tail", m.group(0).strip(", ")))
    for m in re.finditer(NOT_BUT, low):
        flags.add(("not-just-but", m.group(0)[:50]))
    for m in re.finditer(AMERICAN, low):
        flags.add(("American spelling", m.group(0)))
    if "—" in text or "–" in text:
        flags.add(("dash", "em or en dash found"))
    if "**" in text:
        flags.add(("markdown", "bold marks in a CV file"))
    if re.search(r"\[[A-Z][^\]]*\]", text):
        flags.add(("placeholder", "square-bracket placeholder left in"))
    print("Flags:" if flags else "Flags: none")
    for kind, what in sorted(flags):
        print(f"  {kind}: {what}")

    head = "\n".join(lines[:3])
    print("Contact:", "email ok" if re.search(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", head) else "no email in the first 3 lines",
          "| phone", "in +64 form" if "+64" in head else "not in +64 form or missing")
    exp = " ".join(sec.get("experience", []))
    month_year = len(re.findall(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}\b", exp))
    print(f"Dates in experience: {month_year} month-and-year dates (bare years look evasive)")
    edu = [l.strip() for l in sec.get("education", [])]
    print(f"Education lines: {len(edu)}" + ("; none mentions 'in progress'" if edu and not any('progress' in e.lower() for e in edu) else ""))

    if ad:
        ad_terms = tech_terms(ad)
        cv_low = low
        absent = sorted(t for t in ad_terms if t.lower() not in cv_low and len(t) > 1)
        present = sorted(t for t in ad_terms if t.lower() in cv_low and len(t) > 1)
        print(f"Ad terms on the CV ({len(present)}): " + ", ".join(present[:40]))
        print(f"Ad terms NOT on the CV ({len(absent)}): " + ", ".join(absent[:40]) + "  (add only if true)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
