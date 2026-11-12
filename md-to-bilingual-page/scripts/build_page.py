#!/usr/bin/env python3
"""Builds one self-contained HTML page from a Markdown file and its translation.

    python3 -I build_page.py --en report.md --zh report.zh.md --out report.html

The page has three views, switched at the top: English, 中文 and 中英对照 (each paragraph and list item beside its
translation). 中英对照 is the default.

Standard library only, so it runs anywhere Python 3.9+ runs. Nothing is fetched: local images go
inside the page, and remote images stay as plain links. The script never edits the Markdown files.
"""
import argparse
import base64
import datetime
import hashlib
import html
import itertools
import mimetypes
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
GENERATOR = "md-to-bilingual-page"
MAX_IMAGE = 8 * 1024 * 1024
RAW_TAGS = ("figure", "svg", "details", "div", "table", "aside", "section")
INLINE_TAGS = r"</?(?:sup|sub|kbd|mark)>|<br\s*/?>"
CJK = "㐀-鿿豈-﫿"

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^`]*)$")
ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-{3,})[ \t]*$")
LI = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])(\s+)(.*)$")
QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
DELIM = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
REF_DEF = re.compile(r"^ {0,3}\[([^\]^][^\]]*)\]:\s+<?(\S+?)>?(?:\s+[\"'(](.*)[\"')])?\s*$")
RAW_OPEN = re.compile(r"^ {0,3}<(" + "|".join(RAW_TAGS) + r")\b", re.I)
UNSAFE = re.compile(r"<script|<iframe|<object|<embed|\son\w+\s*=|javascript:", re.I)

# Evidence labels used in reports: [RUN], [READ], [EST], with an optional note such as [READ, S15], [RUN, on stand-ins] or [RUN on real GitHub, 3 Nov].
TAG_WORDS = {
    "en": {"RUN": "ran", "READ": "read", "EST": "estimate", "实测": "ran", "读过": "read", "估算": "estimate"},
    "zh": {"RUN": "实测", "READ": "读过", "EST": "估算"},
}
TAG = re.compile(r"\[((?:RUN|READ|EST|实测|读过|估算)(?:[\s,，、:：][^\[\]]{0,200})?)\]")
TAG_KIND = {"RUN": " ran", "实测": " ran", "EST": " est", "估算": " est"}

warnings = []


def warn(msg):
    warnings.append(msg)


def esc(s):
    return html.escape(s, quote=False)


def attr(s):
    return html.escape(s, quote=True)


def indent_of(line):
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def keep_dates(text):
    """2026 年 9 月 28 日 stays on one line: the spaces inside a Chinese date can't break."""
    return re.sub(r"(?<=\d) (?=[年月日号])|(?<=[年月]) (?=\d)", "\u00a0", text)


def plain(rendered):
    """Text of rendered HTML, for labels and the contents list."""
    return html.unescape(re.sub(r"<[^>]+>", "", rendered)).strip()


def fence_step(fence, line):
    """The open fence after this line, and whether the line was a fence."""
    m = FENCE.match(line)
    if not m:
        return fence, False
    if fence is None:
        return m.group(1), True
    if m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
        return None, True
    return fence, False


def setext_under(prev):
    """A line of dashes under a list item, quote or bold line is a rule, not a heading."""
    return bool(prev.strip()) and not prev.lstrip().startswith(("|", "-", "*", ">", "#", "+"))


def slug(text):
    """GitHub's heading anchors, so links written for GitHub keep working."""
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


class Doc:
    """One language of the page."""

    def __init__(self, path, lang, peer_slugs=None):
        self.path, self.lang = path, lang
        self.dir = os.path.dirname(os.path.abspath(path))
        self.raw = open(path, encoding="utf-8").read()
        self.sha = hashlib.sha256(self.raw.encode("utf-8")).hexdigest()
        self.refs, self.count, self.heads, self.depth = {}, 0, [], 0
        self.peer_slugs = peer_slugs or []
        self.lines = self._prepare(self.raw)
        self.anchors = self._scan_heads()

    # ----- Before rendering -----

    def _prepare(self, text):
        text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
        lines = text.split("\n")
        if lines and lines[0].strip() == "---":  # front matter
            for k in range(1, len(lines)):
                if lines[k].strip() in ("---", "..."):
                    lines = lines[k + 1:]
                    break
        kept, fence = [], None
        for line in lines:
            fence, was = fence_step(fence, line)
            if fence is None and not was:
                d = REF_DEF.match(line)
                if d:
                    self.refs[d.group(1).lower()] = (d.group(2), d.group(3))
                    continue
            kept.append(line)
        return kept

    def _heading_lines(self):
        """(line index, level, text) of every heading outside a code block."""
        found, fence = [], None
        for i, line in enumerate(self.lines):
            fence, was = fence_step(fence, line)
            if fence or was:
                continue
            a = ATX.match(line)
            if a:
                found.append((i, len(a.group(1)), a.group(2)))
            elif i and SETEXT.match(line) and setext_under(self.lines[i - 1]):
                found.append((i - 1, 1 if line.strip()[0] == "=" else 2, self.lines[i - 1].strip()))
        return found

    def _scan_heads(self):
        seen, anchors, self.slugs = {}, {}, []
        for k, (_, _, text) in enumerate(self._heading_lines()):
            s = slug(re.sub(r"[*_`]", "", text))
            n = seen.get(s, 0)
            seen[s] = n + 1
            s = f"{s}-{n}" if n else s
            self.slugs.append(s)
            anchors[s] = k
        for k, s in enumerate(self.peer_slugs):  # a translation may keep the source's anchors
            anchors.setdefault(s, k)
        return anchors

    # ----- Inline -----

    def inline(self, text):
        stash = []
        return self._restore(self._inline(text, stash), stash)

    def _inline(self, text, stash):
        def keep(s):
            stash.append(s)
            return f"\x00{len(stash) - 1}\x00"

        def code(m):
            body = m.group(2)
            if len(body) > 2 and body[0] == " " and body[-1] == " ":
                body = body[1:-1]
            return keep(f"<code>{esc(body)}</code>")

        text = re.sub(r"(?<![\\`])(`+)(?!`)(.+?)(?<!`)\1(?!`)", code, text)
        text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>~])", lambda m: keep(esc(m.group(1))), text)
        text = re.sub(r"&(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);", lambda m: keep(m.group(0)), text)

        def image(m):
            return keep(self._image(m.group(1), m.group(2), m.group(3)))

        text = re.sub(r'!\[([^\]]*)\]\(\s*<?([^\s)>]+)>?(?:\s+"([^"]*)")?\s*\)', image, text)

        def link(m):
            return keep(self._anchor(m.group(1), m.group(2), m.group(3), stash))

        text = re.sub(r'\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*<?([^\s()<>]*(?:\([^\s()]*\)[^\s()<>]*)*)>?(?:\s+"([^"]*)")?\s*\)', link, text)

        def ref(m):
            key = (m.group(2) or m.group(1)).lower()
            if key not in self.refs:
                return m.group(0)
            return keep(self._anchor(m.group(1), *self.refs[key], stash))

        if self.refs:
            text = re.sub(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\](?:\[([^\]]*)\])?", ref, text)
        text = re.sub(r"<(https?://[^\s>]+)>", lambda m: keep(self._anchor(m.group(1), m.group(1), None, stash)), text)
        text = re.sub(INLINE_TAGS, lambda m: keep("<br>" if m.group(0).lower().startswith("<br") else m.group(0)), text, flags=re.I)
        text = TAG.sub(lambda m: keep(self._tag(m.group(1))), text)
        if self.lang == "zh":
            text = keep_dates(text)

        def bare(m):
            url = m.group(0)
            trail = ""
            while url and url[-1] in ".,;:!?)，。；：！？）":
                if url[-1] == ")" and url.count("(") >= url.count(")"):
                    break
                trail = url[-1] + trail
                url = url[:-1]
            return keep(self._anchor(url, url, None, stash)) + trail

        text = re.sub(rf"(?<![\w/\"'=])https?://[^\s<>\x00{CJK}]+", bare, text)
        return self._emphasis(esc(text))

    @staticmethod
    def _emphasis(text):
        # Simple pairing on purpose. CommonMark's flanking rules leave ** unmatched next to Chinese punctuation.
        text = re.sub(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*", r"<strong><em>\1</em></strong>", text)
        text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![A-Za-z0-9_])__(?=\S)(.+?)(?<=\S)__(?![A-Za-z0-9_])", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![A-Za-z0-9*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![A-Za-z0-9*])", r"<em>\1</em>", text)
        text = re.sub(r"(?<![A-Za-z0-9_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![A-Za-z0-9_])", r"<em>\1</em>", text)
        return re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", text)

    @staticmethod
    def _restore(text, stash):
        while "\x00" in text:
            text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
        return text

    def _tag(self, body):
        parts = [p.strip() for p in re.split(r"[,，、]", body)]
        word, rest = re.match(r"(RUN|READ|EST|实测|读过|估算)[:：]?\s*(.*)$", parts[0], re.S).groups()
        words = TAG_WORDS[self.lang]
        head = " ".join(x for x in (words.get(word, word), rest) if x)
        sep = "，" if self.lang == "zh" else ", "
        label = sep.join([head] + [words.get(p, p) for p in parts[1:]])
        return f'<span class="tag{TAG_KIND.get(word, "")}">{esc(keep_dates(label) if self.lang == "zh" else label)}</span>'

    def _anchor(self, label, url, title, stash):
        if re.match(r"\s*(javascript|data|vbscript):", url, re.I):
            return self._inline(label, stash)
        if url.startswith("#"):
            k = self.anchors.get(url[1:]) if url[1:] in self.anchors else self.anchors.get(slug(url[1:]))
            if k is None:
                warn(f"{self.lang}: link to a heading that isn't there: {url}")
            else:
                url = f"#{self.lang}-{k + 1}"
        t = f' title="{attr(title)}"' if title else ""
        text = esc(label) if re.match(r"https?://", label) else self._inline(label, stash)  # a bare address is its own label
        return f'<a href="{attr(url)}"{t}>{text}</a>'

    def _image(self, alt, src, title):
        if re.match(r"https?:", src):
            warn(f"{self.lang}: remote image left as a link, so the page stays offline: {src}")
            return f'<a href="{attr(src)}">{esc(alt or src)}</a>'
        path = os.path.normpath(os.path.join(self.dir, src))
        if not os.path.isfile(path):
            warn(f"{self.lang}: image not found: {src}")
            return esc(f"[{alt or src}]")
        size = os.path.getsize(path)
        if size > MAX_IMAGE:
            warn(f"{self.lang}: image over 8 MB left out, shrink it first: {src}")
            return esc(f"[{alt or src}]")
        kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
        data = base64.b64encode(open(path, "rb").read()).decode()
        t = f' title="{attr(title)}"' if title else ""
        return f'<img src="data:{kind};base64,{data}" alt="{attr(alt)}"{t} loading="lazy">'

    # ----- Blocks -----

    def blocks(self, lines):
        return "\n".join(self.blocks_list(lines))

    def blocks_list(self, lines):
        """Each top-level block as its own HTML string, so the two languages can be paired block by block."""
        out, i, n = [], 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = FENCE.match(line)
            if m:
                i = self._fence(lines, i, m, out)
                continue
            if line.lstrip().startswith("<!--"):
                while i < n and "-->" not in lines[i]:
                    i += 1
                i += 1
                continue
            a = ATX.match(line)
            if a:
                out.append(self._heading(len(a.group(1)), a.group(2)))
                i += 1
                continue
            if HR.match(line):
                out.append("<hr>")
                i += 1
                continue
            if QUOTE.match(line):
                i = self._quote(lines, i, out)
                continue
            if LI.match(line) and indent_of(line) <= 3:
                i = self._list(lines, i, out)
                continue
            if self._is_table(lines, i):
                i = self._table(lines, i, out)
                continue
            r = RAW_OPEN.match(line)
            if r:
                i = self._raw(lines, i, r.group(1).lower(), out)
                continue
            i = self._paragraph(lines, i, out)
        return out

    def _heading(self, level, text):
        tag = f"h{min(level, 6)}"
        body = self.inline(text)
        if self.depth:
            return f"<{tag}>{body}</{tag}>"
        self.count += 1
        self.heads.append((self.count, level, body))
        return f'<{tag} id="{self.lang}-{self.count}">{body}</{tag}>'

    @staticmethod
    def _fence(lines, i, m, out):
        mark, info = m.group(1), m.group(2).strip()
        body, i = [], i + 1
        while i < len(lines):
            c = FENCE.match(lines[i])
            if c and c.group(1)[0] == mark[0] and len(c.group(1)) >= len(mark) and not c.group(2).strip():
                i += 1
                break
            body.append(lines[i])
            i += 1
        kind = f' data-lang-name="{attr(info.split()[0])}"' if info else ""
        out.append(f"<pre{kind}><code>{esc(chr(10).join(body))}</code></pre>")
        return i

    def _quote(self, lines, i, out):
        body = []
        while i < len(lines) and lines[i].strip():
            q = QUOTE.match(lines[i])
            body.append(q.group(1) if q else lines[i])
            i += 1
        self.depth += 1
        out.append(f"<blockquote>{self.blocks(body)}</blockquote>")
        self.depth -= 1
        return i

    def _list(self, lines, i, out):
        n = len(lines)
        first = LI.match(lines[i])
        ordered = first.group(2)[0].isdigit()
        base = indent_of(lines[i])
        items, loose = [], False
        while i < n:
            m = LI.match(lines[i])
            if not m or abs(indent_of(lines[i]) - base) > 1 or m.group(2)[0].isdigit() != ordered:
                break
            content = len((m.group(1) + m.group(2) + m.group(3)).expandtabs(4))
            body = [m.group(4)]
            i += 1
            while i < n:
                line = lines[i]
                if not line.strip():
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and indent_of(lines[j]) >= max(content, 2):
                        body.extend([""] * (j - i))
                        loose = True
                        i = j
                        continue
                    break
                ind = indent_of(line)
                nested = LI.match(line) is not None and ind >= 2
                if ind >= content or nested:
                    expanded = line.expandtabs(4)
                    body.append(expanded[min(ind, content if ind >= content else ind):])
                elif LI.match(line) or ATX.match(line) or FENCE.match(line) or HR.match(line) or QUOTE.match(line) or RAW_OPEN.match(line):
                    break
                elif self._is_table(lines, i):
                    break
                else:
                    body.append(line.strip())  # a lazy continuation line
                i += 1
            items.append(body)
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j < n and j != i:
                m2 = LI.match(lines[j])
                if m2 and abs(indent_of(lines[j]) - base) <= 1 and m2.group(2)[0].isdigit() == ordered:
                    loose = True
                    i = j
                else:
                    break
            elif j >= n:
                i = j
                break
        rendered = []
        for body in items:
            box = ""
            t = re.match(r"\[( |x|X)\]\s+(.*)$", body[0])
            if t:
                box = '<span class="box">' + ("☑" if t.group(1).lower() == "x" else "☐") + "</span> "
                body = [t.group(2)] + body[1:]
            self.depth += 1
            html_item = self.blocks(body)
            self.depth -= 1
            if not loose:
                html_item = re.sub(r"^<p>(.*?)</p>", r"\1", html_item, count=1, flags=re.S)
            rendered.append(f"<li>{box}{html_item}</li>")
        tag = "ol" if ordered else "ul"
        start = int(re.sub(r"\D", "", first.group(2))) if ordered else 1
        st = f' start="{start}"' if start != 1 else ""
        out.append(f"<{tag}{st}>{''.join(rendered)}</{tag}>")
        return i

    def _is_table(self, lines, i):
        if i + 1 >= len(lines) or "|" not in lines[i] or "-" not in lines[i + 1] or not DELIM.match(lines[i + 1]):
            return False
        return len(self._cells(lines[i])) == len(self._cells(lines[i + 1]))

    @staticmethod
    def _cells(row):
        row = row.strip()
        row = row[1:] if row.startswith("|") else row
        row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
        cells, cur, tick, k = [], "", False, 0
        while k < len(row):
            ch = row[k]
            if ch == "\\" and k + 1 < len(row) and row[k + 1] == "|":
                cur += "\\|" if not tick else "|"
                k += 2
                continue
            if ch == "`":
                tick = not tick
            if ch == "|" and not tick:
                cells.append(cur.strip())
                cur = ""
            else:
                cur += ch
            k += 1
        cells.append(cur.strip())
        return cells

    def _table(self, lines, i, out):
        heads = [self.inline(c) for c in self._cells(lines[i])]
        aligns = []
        for c in self._cells(lines[i + 1]):
            aligns.append("r" if c.endswith(":") and not c.startswith(":") else "c" if c.startswith(":") and c.endswith(":") else "")
        cols = len(heads)
        aligns = (aligns + [""] * cols)[:cols]
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            cells = [self.inline(c) for c in self._cells(lines[i])]
            if len(cells) > cols:
                warn(f"{self.lang}: a table row has more cells than its header, extras dropped: {plain(cells[0])[:40]}")
            rows.append((cells + [""] * cols)[:cols])
            i += 1
        ths = "".join(f'<th scope="col"{self._align(a)}>{h}</th>' for h, a in zip(heads, aligns))
        body = []
        for row in rows:
            tds = []
            for k, (c, a, h) in enumerate(zip(row, aligns, heads)):
                if k == 0:
                    tds.append(f'<th scope="row"{self._align(a)}>{c}</th>')
                else:
                    # One wrapper, so the phone layout's grid sees a label and a value, not every piece of inline text.
                    tds.append(f'<td data-l="{attr(plain(h))}"{self._align(a)}>' + (f'<span class="v">{c}</span>' if c else "") + "</td>")
            body.append(f"<tr>{''.join(tds)}</tr>")
        shape = "two" if cols <= 2 else "many"
        out.append(f'<div class="t-wrap"><table class="t {shape}"><thead><tr>{ths}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')
        return i

    @staticmethod
    def _align(a):
        return f' class="{a}"' if a else ""

    def _raw(self, lines, i, tag, out):
        start, depth, closed = i, 0, False
        while i < len(lines):
            depth += len(re.findall(rf"<{tag}\b", lines[i], re.I)) - len(re.findall(rf"</{tag}\s*>", lines[i], re.I))
            i += 1
            if depth <= 0:
                closed = True
                break
        if not closed:  # never closed, so it is a sentence that happens to start with a tag
            return self._paragraph(lines, start, out)
        chunk = "\n".join(lines[start:i])
        if UNSAFE.search(chunk):
            warn(f"{self.lang}: raw HTML with script or event code shown as text, not run")
            out.append(f"<pre><code>{esc(chunk)}</code></pre>")
        else:
            out.append(chunk)
        return i

    def _paragraph(self, lines, i, out):
        buf, n = [], len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                break
            if buf:
                if SETEXT.match(line) and setext_under(buf[-1]):
                    out.append(self._heading(1 if line.strip()[0] == "=" else 2, " ".join(x.strip() for x in buf)))
                    return i + 1
                if ATX.match(line) or FENCE.match(line) or HR.match(line) or QUOTE.match(line) or RAW_OPEN.match(line) or self._is_table(lines, i):
                    break
                if LI.match(line) and indent_of(line) <= 3 and (not line.lstrip()[0].isdigit() or re.match(r"\s*1[.)]\s", line)):
                    break
            buf.append(line)
            i += 1
        text = ""
        for k, line in enumerate(buf):
            part = line.strip()
            hard = line.endswith("  ") or part.endswith("\\")
            part = part[:-1] if part.endswith("\\") else part
            if k and text and not text.endswith("<br>"):
                both = re.search(f"[{CJK}，。：；？！）]$", text) and re.match(f"[{CJK}（]", part)
                text += "" if both else " "
            text += part + ("<br>" if hard and k < len(buf) - 1 else "")
        out.append(f"<p>{self.inline(text)}</p>")
        return i

    # ----- The whole document -----

    def render(self):
        heads = self._heading_lines()
        title, body_lines, title_id = None, list(self.lines), f"{self.lang}-0"
        if heads and heads[0][1] == 1:
            at = heads[0][0]
            title = heads[0][2]
            setext = not ATX.match(self.lines[at])
            body_lines[at:at + (2 if setext else 1)] = [""] * (2 if setext else 1)
            rest = heads[1:]
            self.count, title_id = 1, f"{self.lang}-1"  # the title is heading 1, so anchors stay in step between languages
        else:
            rest = heads
        level = min((h[1] for h in rest), default=2)
        cuts = [h[0] for h in rest if h[1] == level]
        if cuts:
            lede_blocks = self.blocks_list(body_lines[:cuts[0]])
            spans = list(zip(cuts, cuts[1:] + [len(body_lines)]))
        else:
            lede_blocks, spans = [], [(0, len(body_lines))]
        sections = []
        for k, (a, b) in enumerate(spans):
            first = self.count + 1
            blocks = self.blocks_list(body_lines[a:b])
            sections.append({"id": f"{self.lang}-{first}", "title": self.heads_title(first), "html": "\n".join(blocks), "blocks": blocks, "n": k + 1})
        return {"title": self.inline(title) if title else "", "title_id": title_id, "lede": "\n".join(lede_blocks), "lede_blocks": lede_blocks, "sections": sections, "level": level}

    def heads_title(self, count):
        for c, _, body in self.heads:
            if c == count:
                return body
        return ""


def stem_title(path):
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"\.(zh|en)$", "", name)
    return re.sub(r"[-_]+", " ", re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name)).strip().capitalize()


def contents(docs):
    """One link per section, with both titles inside, so it points at the same place in every view."""
    links = []
    for k, (z, e) in enumerate(itertools.zip_longest(docs["zh"]["sections"], docs["en"]["sections"])):
        zt, et = plain((z or {}).get("title", "")), plain((e or {}).get("title", ""))
        if zt or et:
            links.append(f'<a href="#s-{k + 1}"><span class="zh">{esc(zt or et)}</span><span class="en">{esc(et or zt)}</span></a>')
    if len(links) < 4:
        return ""
    return f'<details class="menu"><summary><span class="zh">目录</span><span class="en">Contents</span></summary><nav aria-label="目录 / Contents">{"".join(links)}</nav></details>'


LANG_CODE = {"zh": "zh-Hans", "en": "en"}
LIST_OPEN = re.compile(r"^<(ul|ol)\b([^>]*)>")
WIDE = re.compile(r"^<(?:pre|figure|svg|details|div|table|aside|section)\b")


def cell(lang, inner):
    return f'<div class="{lang}" lang="{LANG_CODE[lang]}">{inner}</div>'


def split_items(html_):
    """The items of a rendered list, one string each, or None when the list isn't a plain run of <li>."""
    m = LIST_OPEN.match(html_)
    if not m or not html_.endswith(f"</{m.group(1)}>"):
        return None
    inner = html_[m.end():-(len(m.group(1)) + 3)]
    items, depth, start = [], 0, 0
    for t in re.finditer(r"<li>|</li>", inner):
        if t.group(0) == "</li>":
            depth -= 1
            if depth == 0:
                items.append(inner[start:t.start()])
            elif depth < 0:
                return None
        else:
            if depth == 0:
                start = t.end()
            depth += 1
    if depth or "".join(f"<li>{x}</li>" for x in items) != inner:
        return None
    return m.group(1), m.group(2), items


def pair_list(z, e):
    """A list pairs item by item, so each step sits beside its translation under one number."""
    a, b = split_items(z), split_items(e)
    if not a or not b or a[0] != b[0] or len(a[2]) != len(b[2]):
        return None
    items = "".join(f'<li><div class="pair">{cell("zh", x)}{cell("en", y)}</div></li>' for x, y in zip(a[2], b[2]))
    return f"<{a[0]}{a[1]}>{items}</{a[0]}>"


def tag_of(block):
    m = re.match(r"<(\w+)", block)
    return m.group(1).lower() if m else ""


def pair_blocks(zb, eb, where):
    """Chinese and English blocks of one section, interleaved. They pair when the shape matches, which the translation brief requires."""
    if len(zb) != len(eb) or any(tag_of(x) != tag_of(y) for x, y in zip(zb, eb)):
        warn(f"{where}: the two languages don't pair block by block in 中英对照 (中文 {len(zb)} blocks, English {len(eb)}), so this part shows as one Chinese group and one English group")
        return f'<div class="pair stack" data-group="1">{cell("zh", chr(10).join(zb))}{cell("en", chr(10).join(eb))}</div>'
    out = []
    for z, e in zip(zb, eb):
        if z == e and z.strip() == "<hr>":
            out.append(z)
            continue
        item = pair_list(z, e) if LIST_OPEN.match(z) else None
        if item is None:
            wide = " stack" if WIDE.match(z) or WIDE.match(e) else ""
            item = f'<div class="pair{wide}">{cell("zh", z)}{cell("en", e)}</div>'
        out.append(item)
    return "\n".join(out)


def article(docs, titles):
    zh, en = docs["zh"], docs["en"]
    lede = pair_blocks(zh["lede_blocks"], en["lede_blocks"], "the opening") if zh["lede"].strip() or en["lede"].strip() else ""
    lede = f'<div class="lede">{lede}</div>' if lede else ""
    secs = []
    for k, (z, e) in enumerate(itertools.zip_longest(zh["sections"], en["sections"])):
        z, e = z or {"blocks": []}, e or {"blocks": []}
        secs.append(f'<section data-sec="{k + 1}" id="s-{k + 1}">{pair_blocks(z["blocks"], e["blocks"], f"section {k + 1}")}</section>')
    hero = (f'<header class="hero"><div class="wrap"><h1 class="zh" lang="zh-Hans" id="{zh["title_id"]}">{titles["zh"]}</h1>'
            f'<h1 class="en" lang="en" id="{en["title_id"]}">{titles["en"]}</h1></div></header>')
    return f'<article class="doc">{hero}<div class="wrap body">{lede}\n{chr(10).join(secs)}</div></article>'


def page(args, zh, en, docs, titles):
    css = open(os.path.join(ASSETS, "page.css"), encoding="utf-8").read()
    js = open(os.path.join(ASSETS, "page.js"), encoding="utf-8").read()
    default = args.default
    today = datetime.date.today()
    src = os.path.basename(args.source_name or (args.en if args.source == "en" else args.zh))
    other = os.path.basename(args.zh if args.source == "en" else args.en)
    foot_zh = f"由 <code>{esc(src)}</code> 生成，译文在 <code>{esc(other)}</code>，{keep_dates(f'{today.year} 年 {today.month} 月 {today.day} 日')}。本地页面，不从网上加载任何东西。"
    foot_en = f"Built from <code>{esc(src)}</code>, with the translation in <code>{esc(other)}</code>, on {today.day} {today.strftime('%b %Y')}. A local page that loads nothing from the internet."
    code = "en" if default == "en" else "zh-Hans"
    title_both = f"{plain(titles['zh'])} / {plain(titles['en'])}"
    shown = {"zh": plain(titles["zh"]), "en": plain(titles["en"]), "both": title_both}[default]
    on = lambda v: "true" if default == v else "false"
    return f"""<!doctype html>
<html lang="{code}" data-lang="{default}" data-title-zh="{attr(plain(titles['zh']))}" data-title-en="{attr(plain(titles['en']))}" data-title-both="{attr(title_both)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="generator" content="{GENERATOR}">
<meta name="source-zh" content="{zh.sha}">
<meta name="source-en" content="{en.sha}">
<title>{esc(shown)}</title>
<style>
{css}</style>
<noscript><style>.lang {{ display: none; }}</style></noscript>
<script>
{js}</script>
</head>
<body>
<header class="top"><div class="wrap top-in">
{contents(docs)}
<a class="brand" href="#top"><span class="zh">{titles['zh']}</span><span class="en">{titles['en']}</span></a>
<div class="lang" role="group" aria-label="语言 / Language"><button type="button" data-set="en" aria-pressed="{on('en')}" lang="en">English</button><button type="button" data-set="zh" aria-pressed="{on('zh')}" lang="zh-Hans">中文</button><button type="button" data-set="both" aria-pressed="{on('both')}" lang="zh-Hans">中英对照</button></div>
</div></header>
<main id="top">
{article(docs, titles)}
</main>
<footer class="foot"><div class="wrap"><p class="zh">{foot_zh}</p><p class="en">{foot_en}</p></div></footer>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zh", required=True, help="the Chinese Markdown file")
    ap.add_argument("--en", required=True, help="the English Markdown file")
    ap.add_argument("--out", required=True, help="the HTML file to write")
    ap.add_argument("--source", choices=("zh", "en"), default="en", help="which file is the original (default en)")
    ap.add_argument("--source-name", help="file to name in the footer as the original, when a working copy was built from it")
    ap.add_argument("--default", choices=("both", "zh", "en"), default="both", help="view shown first: both = 中英对照, side by side (default both)")
    ap.add_argument("--force", action="store_true", help="overwrite a page this script did not build")
    args = ap.parse_args()
    if os.path.exists(args.out) and not args.force:
        head = open(args.out, encoding="utf-8", errors="replace").read(4000)
        if f'name="generator" content="{GENERATOR}"' not in head:
            sys.exit(f"STOP: {args.out} exists and was not built by this script. Choose another --out, or look at it and pass --force.")
    en = Doc(args.en, "en")
    zh = Doc(args.zh, "zh", peer_slugs=en.slugs)
    en.peer_slugs = zh.slugs
    en.anchors = en._scan_heads()
    docs = {"zh": zh.render(), "en": en.render()}
    titles = {}
    for lang, doc in (("zh", zh), ("en", en)):
        titles[lang] = docs[lang]["title"] or esc(stem_title(doc.path))
    if len(docs["zh"]["sections"]) != len(docs["en"]["sections"]):
        warn(f"section counts differ: zh {len(docs['zh']['sections'])}, en {len(docs['en']['sections'])}. The language switch can't keep the reader's place.")
    out = page(args, zh, en, docs, titles)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"{args.out}  {len(out.encode()) // 1024} KB, {len(docs['en']['sections'])} sections")
    for w in warnings:
        print("WARNING", w)


if __name__ == "__main__":
    main()
