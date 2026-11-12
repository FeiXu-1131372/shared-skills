#!/usr/bin/env python3
"""Check a cover letter for length, long sentences and machine-sounding patterns.

Usage: check_letter.py letter.txt [--max-words 280] [--max-sentence 25]
       cat letter.txt | check_letter.py -

Prints a short report. A flag means "look here", never "this is wrong".
Exit code is 0 either way, so it can sit in a loop.
"""
import re
import sys

PHRASES = [
    r"i am writing to", r"i am excited", r"i'm excited", r"i am thrilled", r"i am passionate",
    r"passionate", r"results[- ]driven", r"results[- ]oriented", r"team player", r"go-getter",
    r"pivotal", r"crucial", r"testament", r"vital role", r"stands as", r"serves as", r"functions as",
    r"boasts", r"leverag", r"spearhead", r"showcas", r"foster", r"cutting[- ]edge", r"robust",
    r"seamless", r"delve", r"tapestry", r"landscape", r"journey", r"synerg", r"holistic",
    r"in summary", r"overall,", r"in conclusion", r"look forward to the opportunity",
    r"align(s|ed)? with your", r"great fit", r"commitment to excellence", r"innovative approach",
    r"thank you for (your )?(time and )?consideration",
]
TAILS = r",\s+(highlighting|showcasing|demonstrating|reflecting|underscoring|ensuring|emphasi[sz]ing)\b"
NOT_BUT = r"\bnot (just|only|merely)\b.{0,80}\b(but|and also)\b|\bmore than (just )?\w+(\s\w+){0,4},\s+(it|they)('s|'re| is| are)\b"
TRIPLE = r"\b[\w'-]+(?: [\w'-]+){0,2},\s+[\w'-]+(?: [\w'-]+){0,2},?\s+and\s+[\w'-]+"
AMERICAN = r"\b(optimiz\w*|organiz\w*|prioritiz\w*|utiliz\w*|analyz\w*|color\w*|center\w*|behavior\w*|favor\w*|program(?!me)\w*|license\b)"


def sentences(text):
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z\"'(])", flat) if s.strip()]


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict(zip([a for a in argv[1:] if a.startswith("--")],
                    [argv[i + 1] for i, a in enumerate(argv[1:], 1) if a.startswith("--") and i + 1 < len(argv)]))
    max_words = int(opts.get("--max-words", 280))
    max_sent = int(opts.get("--max-sentence", 25))
    if not args:
        print(__doc__)
        return 0
    text = sys.stdin.read() if args[0] == "-" else open(args[0], encoding="utf-8").read()
    body = re.sub(r"```", "", text)
    words = re.findall(r"\S+", body)
    sents = sentences(body)
    lens = [len(s.split()) for s in sents]
    low = body.lower()
    flags = []

    for p in PHRASES:
        for m in re.finditer(p, low):
            flags.append(("phrase", m.group(0)))
    for m in re.finditer(TAILS, low):
        flags.append(("-ing tail", m.group(0).strip(", ")))
    for m in re.finditer(NOT_BUT, low):
        flags.append(("not-just-but", m.group(0)[:60]))
    for m in re.finditer(TRIPLE, low):
        flags.append(("list of three", m.group(0)[:60]))
    for m in re.finditer(AMERICAN, low):
        flags.append(("American spelling", m.group(0)))
    if "—" in body or "–" in body or " -- " in body:
        flags.append(("dash", "em or en dash found"))
    if "**" in body or re.search(r"^#{1,6} ", body, re.M):
        flags.append(("markdown", "bold or heading marks will show as symbols in many application boxes"))
    bullets = len(re.findall(r"^\s*[-*•] ", body, re.M))
    if bullets:
        flags.append(("bullets", f"{bullets} bullet lines; fine only for a screener reading a checklist"))
    headings = [l.strip() for l in body.splitlines() if l.strip() and len(l.split()) <= 7 and not re.search(r"[.,:;!?]$", l.strip()) and not re.match(r"(kia ora|dear|hello|hi|kind regards|regards|thanks|yours)\b", l.strip(), re.I) and len(l.split()) > 1 and l.strip() != l.strip().title() + "x"]
    headings = [h for h in headings if not re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+$", h)]
    if headings:
        flags.append(("heading lines", f"{len(headings)} short heading-like lines, e.g. '{headings[0]}'; plain prose reads more like a person"))
    if re.search(r"\[[A-Z][^\]]*\]", body):
        flags.append(("placeholder", "square-bracket placeholder left in"))
    if re.search(r"^\s*[-*•] .{0,40}\.\s", body, re.M):
        flags.append(("label bullets", "bullets that start with a short label then a sentence"))

    avg = sum(lens) / len(lens) if lens else 0
    long_ones = [(n, s) for n, s in zip(lens, sents) if n > max_sent]
    contractions = len(re.findall(r"\b\w+(n't|'m|'d|'ve|'ll|'re)\b|\b(it|that|there|what|let|here)'s\b", body, re.I))
    short = sum(1 for n in lens if n <= 8)

    print(f"Words: {len(words)} (target under {max_words})" + ("   <-- over" if len(words) > max_words else ""))
    print(f"Sentences: {len(sents)}, average {avg:.1f} words, longest {max(lens) if lens else 0}, very short (8 or fewer): {short}")
    print(f"Contractions: {contractions}")
    for n, s in long_ones:
        print(f"  LONG ({n}): {s[:90]}...")
    if flags:
        print("Flags:")
        seen = set()
        for kind, what in flags:
            if (kind, what) in seen:
                continue
            seen.add((kind, what))
            print(f"  {kind}: {what}")
    else:
        print("Flags: none")
    if short == 0 and len(sents) > 5:
        print("Note: no very short sentences; the rhythm may read as even and machine-made.")
    if contractions == 0 and len(sents) > 5:
        print("Note: no contractions; read it aloud and see whether that is how the person speaks.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
