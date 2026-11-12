#!/usr/bin/env python3
"""Compares a Markdown file with its translation, then checks the built page. Read-only.

    python3 -I check_page.py --en report.md --zh report.zh.md --page report.html

FAIL lines must be fixed. REVIEW lines need a judgement: fix them, or leave them if they are right.
Exit code 1 when anything fails.

The two files are compared piece by piece: each heading, paragraph, list item and table cell against its
partner, so a number that changed, or moved to another row, fails even when the page's totals still match.
Meaning isn't checked. Only reading the translation against the source finds a changed claim.
"""
import argparse
import collections
import contextlib
import hashlib
import html
import html.parser
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_page as B  # noqa: E402

CJK = B.CJK
MONTHS = {"Jan": 1, "January": 1, "Feb": 2, "February": 2, "Mar": 3, "March": 3, "Apr": 4, "April": 4, "May": 5, "Jun": 6, "June": 6, "Jul": 7, "July": 7,
          "Aug": 8, "August": 8, "Sep": 9, "Sept": 9, "September": 9, "Oct": 10, "October": 10, "Nov": 11, "November": 11, "Dec": 12, "December": 12}
TONE = "进行 关于 对于 基于 作为 以及 此外 然而 因此 其 该 被 赋能 闭环 抓手 底层逻辑 沉淀 打造 助力 痛点 令牌".split()
MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "千": 1e3, "万": 1e4, "M": 1e6, "million": 1e6, "百万": 1e6, "亿": 1e8, "B": 1e9, "billion": 1e9}
SCALED = re.compile(r"(?<![\w.,])(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|百万|[kKMB千万亿])(?![A-Za-z0-9])")
SHOWN = 10  # lines of one kind, so a badly broken file doesn't bury the rest
fails = 0


def fail(msg):
    global fails
    fails += 1
    print("FAIL  ", msg)


def review(msg):
    print("REVIEW", msg)


def rendered(path, lang):
    d = B.Doc(path, lang)
    with contextlib.redirect_stdout(io.StringIO()):
        r = d.render()
    return d, r["title"] + "\n" + r["lede"] + "\n" + "\n".join(s["html"] for s in r["sections"])


def text_of(h, drop_code=True):
    h = re.sub(r"<pre[^>]*>.*?</pre>", " ", h, flags=re.S)
    if drop_code:
        h = re.sub(r"<code>.*?</code>", " ", h, flags=re.S)
    h = re.sub(r'<span class="tag[^"]*">.*?</span>', " ", h, flags=re.S)
    h = re.sub(r"<[^>]+>", "\n", h)
    return html.unescape(h)


def excerpts(pattern, text, limit=6):
    hits = [text[max(0, m.start() - 10):m.end() + 10].replace("\n", " ").strip() for m in re.finditer(pattern, text)]
    return len(hits), hits[:limit]


def in_date_order(text):
    """3 Nov 2026 becomes 2026 11 3, the order Chinese writes it, so a date doesn't look like a moved number."""
    text = re.sub(rf"\b(\d{{1,2}})\s+({MONTH})\b\.?(?:,?\s+(\d{{4}})\b)?", lambda m: f" {m.group(3) or ''} {MONTHS[m.group(2)]} {m.group(1)} ", text)
    text = re.sub(rf"\b({MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}})\b)?", lambda m: f" {m.group(3) or ''} {MONTHS[m.group(1)]} {m.group(2)} ", text)
    text = re.sub(rf"\b({MONTH})\s+(\d{{4}})\b", lambda m: f" {m.group(2)} {MONTHS[m.group(1)]} ", text)
    return re.sub(rf"\b(?!May\b)({MONTH})\b", lambda m: str(MONTHS[m.group(1)]), text)  # "May" alone is usually the verb


def values(text):
    """Every number in reading order. 14k, 14,000 and 1.4 万 are all 14000, and 03 is 3."""
    text = SCALED.sub(lambda m: f"{float(m.group(1).replace(',', '')) * SCALE[m.group(2)]:.0f}", in_date_order(text))
    found = []
    for n in re.findall(r"\d+(?:[.,:]\d+)*", text):
        n = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", n)
        found.append((n.lstrip("0") or "0") if n.isdigit() else n)
    return found


class Pieces(html.parser.HTMLParser):
    """Rendered HTML as its blocks in reading order, so each one can be held against its partner."""

    BLOCK = set("h1 h2 h3 h4 h5 h6 p li th td figcaption".split())
    EDGE = set("ul ol table tr blockquote div figure section details".split())
    Piece = collections.namedtuple("Piece", "kind text full code")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.kind, self.text, self.full, self.code = [], None, [], [], []
        self.in_code, self.in_pre = 0, 0

    def flush(self, kind):
        full = "".join(self.full).strip()
        if full or self.kind in ("td", "th"):
            self.found.append(self.Piece(self.kind or "text", "".join(self.text).strip(), full, collections.Counter(self.code)))
        self.kind, self.text, self.full, self.code = kind, [], [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK or tag in self.EDGE:
            self.flush(tag if tag in self.BLOCK else None)
        elif tag == "pre":
            self.in_pre += 1
        elif tag == "code":
            self.in_code += 1
            self.code.append("")

    def handle_endtag(self, tag):
        if tag in self.BLOCK or tag in self.EDGE:
            self.flush(None)
        elif tag == "pre":
            self.in_pre -= 1
        elif tag == "code":
            self.in_code -= 1

    def handle_data(self, data):
        if self.in_pre:
            return
        self.full.append(data)
        if self.in_code:
            self.code[-1] += data
        else:
            self.text.append(data)


def pieces(rendered_html):
    p = Pieces()
    p.feed(rendered_html)
    p.flush(None)
    return p.found


def where(text):
    return re.sub(r"\s+", " ", text)[:44]


def capped(kind, lines, say):
    for line in lines[:SHOWN]:
        say(f"{kind}: {line}")
    if len(lines) > SHOWN:
        say(f"{kind}: {len(lines) - SHOWN} more like this")


def compare_pieces(a, b, same_code):
    """Each piece of the English against the same piece of the Chinese."""
    changed, cells, code_moved, small, added, reordered, stray = [], [], [], [], [], [], []
    for x, y in zip(a, b):
        if x.kind in ("td", "th") and bool(x.full) != bool(y.full):
            cells.append(where(x.full or y.full))
        if same_code and x.code != y.code:
            code_moved.append(f"{list((x.code - y.code).elements())[:3]} at: {where(y.full)}")
        vx, vy = values(x.text), values(y.text)
        gone, extra = collections.Counter(vx) - collections.Counter(vy), collections.Counter(vy) - collections.Counter(vx)
        long_gone = [k for k in gone if len(re.sub(r"\D", "", k)) > 1]
        if long_gone or (gone and extra):
            changed.append(f"English has {sorted(gone.elements())}, Chinese has {sorted(extra.elements()) or 'neither'}, at: {where(y.full)}")
        elif gone:
            small.append(f"{sorted(gone.elements())} at: {where(y.full)}")
        elif extra:
            added.append(f"{sorted(extra.elements())} at: {where(y.full)}")
        elif vx != vy:
            reordered.append(f"{vx} against {vy} at: {where(y.full)}")
        lower = x.full.lower()
        odd = sorted({w for w in re.findall(r"[A-Za-z][A-Za-z'’-]+", y.text) if w.lower() not in lower})
        if odd:
            stray.append(f"{odd[:5]} at: {where(y.full)}")
    capped("number changed or moved", changed, fail)
    capped("table cell filled in one language only", cells, fail)
    capped("inline code in a different place", code_moved, fail)
    capped("single digit missing from the Chinese (fine if written as a word)", small, review)
    capped("number only in the Chinese (fine for a word such as 'three' written as a digit)", added, review)
    capped("numbers in a different order (fine if the sentence was turned round)", reordered, review)
    capped("English word only in the Chinese (a gloss, or a row out of place?)", stray, review)


def compare(en, zh):
    # Structure: the translation must have the same shape, or the two pages drift apart.
    for tag in "h2 h3 h4 h5 h6 table tr li pre blockquote img".split():
        a, b = len(re.findall(rf"<{tag}\b", en)), len(re.findall(rf"<{tag}\b", zh))
        if a != b:
            fail(f"<{tag}> count: English {a}, Chinese {b}")
    for name, pattern in (("cells", r"<t[dh]\b"), ("evidence labels", r'<span class="tag')):
        a, b = len(re.findall(pattern, en)), len(re.findall(pattern, zh))
        if a != b:
            fail(f"{name}: English {a}, Chinese {b}")
    for kind in ("tag ran", "tag est"):
        a, b = en.count(f'class="{kind}"'), zh.count(f'class="{kind}"')
        if a != b:
            fail(f"'{kind}' labels: English {a}, Chinese {b}")

    # Code, addresses and links are the same in both languages.
    code = lambda h: collections.Counter(re.findall(r"<code>(.*?)</code>", re.sub(r"<pre[^>]*>.*?</pre>", "", h, flags=re.S), flags=re.S))
    ca, cb = code(en), code(zh)
    if ca != cb:
        fail(f"inline code differs. Only English: {list((ca - cb).elements())[:8]}. Only Chinese: {list((cb - ca).elements())[:8]}")
    links = lambda h: collections.Counter(u for u in re.findall(r'<a href="([^"]*)"', h) if not u.startswith("#"))
    la, lb = links(en), links(zh)
    if la != lb:
        fail(f"links differ. Only English: {list((la - lb).elements())[:6]}. Only Chinese: {list((lb - la).elements())[:6]}")
    pa, pb = re.findall(r"<pre[^>]*>(.*?)</pre>", en, flags=re.S), re.findall(r"<pre[^>]*>(.*?)</pre>", zh, flags=re.S)
    changed = sum(1 for x, y in zip(pa, pb) if x != y)
    if changed:
        review(f"{changed} code block(s) differ. Fine only if a diagram's labels were translated on purpose.")

    # Facts: every amount carries over, and every number stays in its own piece of the page.
    te, tz = text_of(en), text_of(zh)
    money = lambda t: collections.Counter(s.rstrip(".,") for s in re.findall(r"(?:US|NZ|AU|HK|S)?\$\s?\d[\d,.]*|[€£¥]\s?\d[\d,.]*", t))
    ma, mb = money(te), money(tz)
    if ma != mb:
        fail(f"money differs. Only English: {dict(ma - mb)}. Only Chinese: {dict(mb - ma)}")
    pa_, pb_ = pieces(en), pieces(zh)
    if [p.kind for p in pa_] == [p.kind for p in pb_]:
        compare_pieces(pa_, pb_, ca == cb)
    else:
        review("the two files don't line up piece by piece (a split or merged paragraph?), so numbers were compared for the whole page only and a number moved between rows won't show")
        na, nb = collections.Counter(values(te)), collections.Counter(values(tz))
        if na - nb:
            fail(f"numbers missing from the Chinese: {dict(na - nb)}")
        if nb - na:
            review(f"numbers only in the Chinese: {dict(nb - na)}")
    words, chars = len(re.findall(r"[A-Za-z][A-Za-z'-]*", te)), len(re.findall(f"[{CJK}]", tz))
    if words > 40 and not 1.0 <= chars / words <= 3.0:
        review(f"length looks off: {words} English words, {chars} Chinese characters. Check nothing was dropped or added.")

    # Chinese typography.
    plain = tz
    for label, pattern in (
        ("half-width punctuation after Chinese", rf"[{CJK}][,.;:?!()]"),
        ("half-width punctuation before Chinese", rf"[,;:?!(]\s*[{CJK}]"),
        ("straight double quote in Chinese text", rf'"[{CJK}]|[{CJK}]"'),
        ("dash or ellipsis in Chinese text", r"[—–…]"),
    ):
        n, hits = excerpts(pattern, plain)
        if n:
            fail(f"{label}: {n}, e.g. {hits}")
    n, hits = excerpts(rf"[{CJK}][A-Za-z0-9$]|[A-Za-z0-9%$][{CJK}]", plain)
    if n:
        fail(f"no space between Chinese and a Latin letter or digit: {n}, e.g. {hits}")
    n, hits = excerpts("您", plain, 3)
    if n:
        fail(f"您 in the Chinese, the reader is 你: {n}, e.g. {hits}")
    for word in TONE:
        n, hits = excerpts(word, plain, 3)
        if n > 3 or (n and len(word) > 1):
            review(f"translation tone? {word} x{n}: {hits}")
    runs = sorted(set(m.group(0) for m in re.finditer(r"[A-Za-z][A-Za-z'’\-]*(?:[ ,.]+[A-Za-z][A-Za-z'’\-]*){3,}", plain)))
    if runs:
        review(f"runs of four or more English words left in the Chinese: {runs[:8]}")
    n, hits = excerpts(f"[{CJK}]", te)
    if n:
        review(f"Chinese left in the English: {n}, e.g. {hits[:4]}")


def check_page(path, en_doc, zh_doc):
    if not os.path.exists(path):
        fail(f"no page at {path}")
        return
    s = open(path, encoding="utf-8").read()
    for lang, doc in (("zh", zh_doc), ("en", en_doc)):
        m = re.search(rf'<meta name="source-{lang}" content="([0-9a-f]+)"', s)
        if not m or m.group(1) != hashlib.sha256(doc.raw.encode("utf-8")).hexdigest():
            fail(f"the page is out of date: {lang} Markdown changed since the build")
    head = s[:s.index("<main")]
    if re.search(r"<link\b|<script[^>]+src=|@import|url\(\s*[\"']?https?:", head) or re.search(r"""(?:src)=["']https?:""", s):
        fail("the page loads something from outside, so it won't work offline")
    if "{{" in re.sub(r"<(?:pre|code)[^>]*>.*?</(?:pre|code)>", "", s, flags=re.S):
        fail("an unfilled placeholder is in the page")
    if "/bin/zsh" in s and "/bin/zsh" not in en_doc.raw:
        fail("the shell ate a $0: write the translation with the Write tool, not a heredoc")
    # One set of sections serves all three views, and every block sits in a Chinese cell and an English one.
    secs = len(re.findall(r"<section data-sec=", s))
    for lang, doc in (("zh", zh_doc), ("en", en_doc)):
        with contextlib.redirect_stdout(io.StringIO()):
            n = len(doc.render()["sections"])
        if n != secs:
            fail(f"the {lang} Markdown has {n} sections and the page has {secs}, so the language switch can't keep the reader's place")
    zc, ec = len(re.findall(r'<div class="zh" lang="zh-Hans">', s)), len(re.findall(r'<div class="en" lang="en">', s))
    if not zc or zc != ec:
        fail(f"中文 and English cells don't match: {zc} against {ec}")
    loose = len(re.findall(r'data-group="1"', s))
    if loose:
        review(f"{loose} part(s) of the page could not be paired block by block in 中英对照 and show as one Chinese group and one English group. Make the two files the same shape: no merged or split paragraphs, the same list items.")
    print(f"Page: {os.path.getsize(path) // 1024} KB, {secs} sections, {zc} paired blocks.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--en", required=True)
    ap.add_argument("--zh", required=True)
    ap.add_argument("--page", required=True)
    args = ap.parse_args()
    en_doc, en = rendered(args.en, "en")
    zh_doc, zh = rendered(args.zh, "zh")
    compare(en, zh)
    check_page(args.page, en_doc, zh_doc)
    print("Checked: page shape, inline code, links, money, and every number piece by piece. Not checked: meaning. A changed claim, a dropped hedge or an added sentence only shows when someone reads the translation against the source.")
    print(f"Hard failures: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
