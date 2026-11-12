#!/usr/bin/env python3
"""Render a local markdown file to a clean standalone HTML page and open it.

Usage: view_md.py <path> [--no-open]

Works for any path on the machine: no vault, no app setup. Pages are written to
~/.cache/view-md/ (one file per source, overwritten on each run). Relative links to
other .md files are rendered too (up to MAX_PAGES) so reading can hop between notes.

Exit codes (the last line printed is always "RESULT: ..."):
  0  rendered (and opened, unless --no-open)
  2  file not found
  3  more than one file matches; the candidates are listed
  6  markdown-it-py is missing
"""
import argparse
import hashlib
import html
import os
import re
import subprocess
import sys
import unicodedata
import urllib.parse

try:
    from markdown_it import MarkdownIt
except ImportError:
    MarkdownIt = None

CACHE = os.path.expanduser("~/.cache/view-md")
MAX_PAGES = 40
MD_EXTS = {".md", ".markdown", ".mdown"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__"}


# ---------- finding the file ----------

def clean(raw):
    """Strip chat decoration: [text](path), `path`, quotes, file://, :line. -> (path, fragment)"""
    s = raw.strip()
    m = re.fullmatch(r"\[[^\]]*\]\(([^)]*)\)", s)
    if m:
        s = m.group(1)
    s = s.strip().strip("`'\"<>").strip()
    if s.startswith("file://"):
        s = urllib.parse.unquote(s[len("file://"):])
    frag = ""
    if "#" in s:
        s, frag = s.split("#", 1)
    s = re.sub(r":\d+(:\d+)?$", "", s)
    return unicodedata.normalize("NFC", os.path.expanduser(s)), frag


def git_root(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def locate(path):
    if os.path.isabs(path):
        return [os.path.realpath(path)] if os.path.exists(path) else []
    cwd = os.path.realpath(os.getcwd())  # realpath also drops a trailing slash
    roots = [cwd]
    top = git_root(cwd)
    if top and os.path.realpath(top) != cwd:
        roots.append(os.path.realpath(top))
    for r in roots:
        cand = os.path.join(r, path)
        if os.path.exists(cand):
            return [os.path.realpath(cand)]
    # Fall back to matching the tail of the path anywhere under the roots (bare name,
    # or a path missing its first folders).
    tail = os.sep + path.strip(os.sep)
    found = []
    for r in roots[::-1]:
        for dirpath, dirnames, filenames in os.walk(r):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                full = os.path.join(dirpath, name)
                if unicodedata.normalize("NFC", full).endswith(tail):
                    found.append(os.path.realpath(full))
        if found:
            break
    return sorted(set(found))


# ---------- rendering ----------

def out_path(src):
    h = hashlib.sha1(src.encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(os.path.basename(src))[0])[:60]
    return os.path.join(CACHE, f"{stem}-{h}.html")


def slugify(text, seen):
    s = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-") or "section"
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else f"{s}-{n}"


def split_frontmatter(text):
    m = re.match(r"\A---\n(.*?\n)---\n", text, re.S)
    return (m.group(1), text[m.end():]) if m else (None, text)


def render_one(src, queue, queued):
    """Render src to its cache page; append newly discovered linked .md files to queue."""
    with open(src, encoding="utf-8", errors="replace") as f:
        text = f.read()
    front, body = split_frontmatter(text)
    base = os.path.dirname(src)

    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    tokens = md.parse(body)

    headings, seen = [], {}
    for i, t in enumerate(tokens):
        if t.type == "heading_open":
            label = tokens[i + 1].content
            slug = slugify(re.sub(r"[`*_]", "", label), seen)
            t.attrSet("id", slug)
            headings.append((int(t.tag[1]), slug, re.sub(r"[`*_]", "", label)))
        if t.type != "inline" or not t.children:
            continue
        for c in t.children:
            if c.type == "image":
                s = c.attrGet("src") or ""
                if s and not re.match(r"[a-z][a-z0-9+.-]*:", s, re.I):
                    c.attrSet("src", "file://" + urllib.parse.quote(
                        os.path.normpath(os.path.join(base, urllib.parse.unquote(s)))))
            elif c.type == "link_open":
                href = c.attrGet("href") or ""
                if not href or href.startswith("#") or re.match(r"[a-z][a-z0-9+.-]*:", href, re.I):
                    continue
                target, _, frag = href.partition("#")
                full = os.path.normpath(os.path.join(base, urllib.parse.unquote(target)))
                if not os.path.isfile(full):
                    continue
                if os.path.splitext(full)[1].lower() in MD_EXTS:
                    full = os.path.realpath(full)
                    if full not in queued and len(queued) < MAX_PAGES:
                        queued.add(full)
                        queue.append(full)
                    page = out_path(full) if full in queued else full
                    href = "file://" + urllib.parse.quote(page) + ("#" + frag if frag else "")
                else:
                    href = "file://" + urllib.parse.quote(full)
                c.attrSet("href", href)

    content = md.renderer.render(tokens, md.options, {})
    content = re.sub(r"(<li[^>]*>\s*(?:<p>)?)\[([ xX])\]\s",
                     lambda m: m.group(1) + '<input type="checkbox" disabled'
                     + (" checked" if m.group(2) != " " else "") + "> ", content)

    title = next((h[2] for h in headings if h[0] == 1), os.path.basename(src))
    toc_items = [h for h in headings if h[0] in (2, 3)]
    toc = ""
    if len(toc_items) >= 3:
        toc = "<nav class=toc><div class=toc-h>目录</div>" + "".join(
            f'<a class=l{lvl} href="#{html.escape(slug)}">{html.escape(label)}</a>'
            for lvl, slug, label in toc_items) + "</nav>"
    fm = (f"<details class=fm><summary>文档头信息</summary><pre>{html.escape(front)}</pre></details>"
          if front else "")

    page = PAGE.format(title=html.escape(title), toc=toc,
                       path=html.escape(src.replace(os.path.expanduser("~"), "~")),
                       fm=fm, content=content, css=CSS)
    os.makedirs(CACHE, exist_ok=True)
    dest = out_path(src)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(page)
    return dest


CSS = """
:root{--bg:#fbfaf7;--fg:#24211c;--muted:#7a7468;--line:#e4dfd3;--accent:#8a3b12;
--code-bg:#f1eee6;--quote:#b9a98a;--th:#f1eee6}
@media (prefers-color-scheme:dark){:root{--bg:#1c1b19;--fg:#e6e2d9;--muted:#9a9487;
--line:#3a3833;--accent:#e0a070;--code-bg:#2a2926;--quote:#6b5f48;--th:#2a2926}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.85 -apple-system,"PingFang SC",
"Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
.wrap{display:grid;grid-template-columns:minmax(0,1fr);max-width:46rem;margin:0 auto;padding:28px 20px 96px}
.toc{display:none}
@media (min-width:1160px){
.wrap{grid-template-columns:230px minmax(0,46rem);max-width:none;gap:56px;justify-content:center}
.toc{display:block;position:sticky;top:28px;align-self:start;max-height:calc(100vh - 56px);
overflow:auto;font-size:13.5px;line-height:1.5;padding-right:8px}}
.toc-h{color:var(--muted);font-size:12px;letter-spacing:.08em;margin-bottom:8px}
.toc a{display:block;color:var(--muted);text-decoration:none;padding:3px 0}
.toc a.l3{padding-left:14px;font-size:12.5px}.toc a:hover{color:var(--accent)}
.src{color:var(--muted);font-size:12.5px;margin-bottom:6px;word-break:break-all}
h1,h2,h3,h4{line-height:1.4;margin:2.1em 0 .6em;scroll-margin-top:16px}
h1{font-size:1.9em;margin-top:.4em}h2{font-size:1.45em;padding-bottom:.25em;border-bottom:1px solid var(--line)}
h3{font-size:1.2em}h4{font-size:1.05em;color:var(--muted)}
p,ul,ol,table,pre,blockquote,details{margin:0 0 1.1em}
a{color:var(--accent)}
ul,ol{padding-left:1.6em}li{margin:.25em 0}li>p{margin:.3em 0}
blockquote{margin-left:0;padding:.1em 1.1em;border-left:3px solid var(--quote);color:var(--muted)}
hr{border:0;border-top:1px solid var(--line);margin:2em 0}hr+h2{margin-top:1.2em}
code{font:.88em ui-monospace,"SF Mono",Menlo,monospace;background:var(--code-bg);padding:.12em .38em;border-radius:4px}
pre{background:var(--code-bg);padding:14px 16px;border-radius:8px;overflow:auto;line-height:1.55}
pre code{background:none;padding:0;font-size:.85em}
table{border-collapse:collapse;display:block;overflow-x:auto;font-size:.94em;line-height:1.6}
th,td{border:1px solid var(--line);padding:7px 12px;text-align:left;vertical-align:top}
th{background:var(--th)}
img{max-width:100%;height:auto;border-radius:4px}
input[type=checkbox]{margin-right:.4em}
.fm{font-size:13px;color:var(--muted)}.fm pre{font-size:12.5px}
@media print{.toc{display:none}body{background:#fff;color:#000}}
"""

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src file: data: https: http:; style-src 'unsafe-inline'; font-src data:">
<title>{title}</title><style>{css}</style></head>
<body><div class="wrap">{toc}<main><div class="src">{path}</div>{fm}{content}</main></div></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    path, frag = clean(args.path)
    matches = locate(path) if path else []
    if not matches:
        print(f"RESULT: not found: {path} (looked under {os.getcwd()})")
        return 2
    if len(matches) > 1:
        print("RESULT: ambiguous, more than one match:")
        for m in matches:
            print("  " + m)
        return 3
    src = matches[0]

    if os.path.isdir(src) or os.path.splitext(src)[1].lower() not in MD_EXTS:
        print(f"RESULT: {src} is not markdown; handed to the macOS default app")
        if not args.no_open:
            subprocess.run(["open", src])
        return 0
    if MarkdownIt is None:
        print("RESULT: python package markdown-it-py is missing; run: pip3 install markdown-it-py")
        return 6

    queue, queued = [src], {src}
    dests = {}
    while queue:
        cur = queue.pop(0)
        dests[cur] = render_one(cur, queue, queued)

    # Pages rendered before a later link target was discovered already point at the right
    # cache name (names are derived from the source path), so no second pass is needed.
    dest = dests[src]
    anchor = slugify(frag, {}) if frag else ""
    url = "file://" + urllib.parse.quote(dest) + ("#" + urllib.parse.quote(anchor) if anchor else "")
    if not args.no_open:
        subprocess.run(["open", url])
    extra = len(dests) - 1
    print(f"RESULT: rendered {src} -> {dest}"
          + (f" (+{extra} linked page{'s' if extra != 1 else ''})" if extra else "")
          + ("" if args.no_open else " and opened in the default browser"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
