#!/usr/bin/env python3
"""Opens the page in a real browser, measures the layout, and takes screenshots to look at.

    python3 -I look.py report.html --out <scratchpad>/look

Prints one line per width and view (中英对照, 中文, English), then the sheets to open. Needs agent-browser. Numbers alone don't
prove a page is readable, so the sheets still have to be looked at.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

KEY = "md-bilingual-page-view"
WIDTHS = (320, 375, 640, 768, 1024, 1280)
VIEWS = ("both", "zh", "en")
SHOTS = (("both", "light", 375, 1400), ("both", "light", 1280, 1000), ("both", "dark", 375, 1400), ("zh", "light", 375, 1400), ("en", "light", 375, 1400), ("en", "dark", 1280, 1000))
MEASURE = """JSON.stringify((() => {
  const lang = document.documentElement.dataset.lang, other = lang === 'zh' ? '.en' : lang === 'en' ? '.zh' : null;
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  // Something a parent clips or scrolls isn't sticking out, such as a long title cut off with an ellipsis in the top bar.
  const held = (e) => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) if (getComputedStyle(p).overflowX !== 'visible') return true; return false; };
  const out = [...document.querySelectorAll('body *')].filter((e) => vis(e) && e.getBoundingClientRect().right > innerWidth + 1 && !held(e)).slice(0, 5).map((e) => e.tagName + ':' + (e.textContent || '').trim().slice(0, 30));
  const wide = [...document.querySelectorAll('.t-wrap,pre')].filter((e) => vis(e) && e.scrollWidth > e.clientWidth + 1).length;
  const leak = other ? [...document.querySelectorAll(other)].filter(vis).length : 0;
  // In 中英对照 every pair shows both cells, and on a wide screen the Chinese sits left of the English.
  const unpaired = lang === 'both' ? [...document.querySelectorAll('.pair')].filter((p) => ![...p.children].every(vis)).length : 0;
  const small = [...document.querySelectorAll('main *')].filter((e) => vis(e) && [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(e).fontSize) < 12).length;
  const text = document.querySelector('main').innerText;
  return { lang, page: document.documentElement.scrollWidth, win: document.documentElement.clientWidth, height: document.documentElement.scrollHeight, out, scrollers: wide, leak, unpaired, small,
           cjk: lang === 'en' ? (text.match(/[\\u3400-\\u9fff]/g) || []).length : 0, title: document.title };
})())"""
# The switch must keep the reader in the same section: 中英对照 to 中文, 中文 to English, English to 中英对照.
SWITCH = """(() => {
  const d = document.documentElement, from = d.dataset.lang, to = { both: 'zh', zh: 'en', en: 'both' }[from];
  const secs = [...document.querySelectorAll('[data-sec]')];
  if (secs.length < 3) return 'skipped';
  const target = secs[Math.floor(secs.length / 2)];
  window.scrollTo(0, target.getBoundingClientRect().top + scrollY - 40);
  const before = target.dataset.sec;
  document.querySelector('[data-set="' + to + '"]').click();
  const after = secs.filter((s) => s.getBoundingClientRect().top <= 60).pop();
  return (before === (after && after.dataset.sec) ? 'ok' : 'moved from section ' + before + ' to ' + (after && after.dataset.sec)) + ' (to ' + to + ')';
})()"""


class Browser:
    def __init__(self, tool, session):
        self.tool, self.session = tool, session

    def __call__(self, *args):
        r = subprocess.run([self.tool, "--session", self.session, *map(str, args)], capture_output=True, text=True, timeout=60)
        return r.stdout.strip()

    def value(self, script):
        raw = self("eval", script)
        try:
            v = json.loads(raw)
            return json.loads(v) if isinstance(v, str) and v[:1] in "{[" else v
        except ValueError:
            return raw


def show(ab, url, lang, media, width, height):
    ab("set", "media", media)
    ab("set", "viewport", width, height)
    ab("open", url)
    ab("wait", 200)
    ab("eval", f"localStorage.setItem('{KEY}','{lang}');location.reload()")
    ab("wait", 350)


def sheets(paths, out, stem):
    try:
        from PIL import Image
    except ImportError:
        return paths
    made = []
    for k in range(0, len(paths), 3):
        group = [Image.open(p).convert("RGB") for p in paths[k:k + 3]]
        w = sum(i.width for i in group) + 10 * (len(group) - 1)
        sheet = Image.new("RGB", (w, max(i.height for i in group)), (255, 0, 255))
        x = 0
        for im in group:
            sheet.paste(im, (x, 0))
            x += im.width + 10
        path = os.path.join(out, f"sheet-{stem}-{k // 3:02d}.png")
        sheet.save(path)
        made.append(path)
    return made


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("page")
    ap.add_argument("--out", required=True, help="a scratch folder for the screenshots")
    args = ap.parse_args()
    tool = shutil.which("agent-browser")
    if not tool:
        sys.exit("agent-browser isn't installed, so nothing was checked. Use another real browser, or say plainly that the page wasn't looked at.")
    os.makedirs(args.out, exist_ok=True)
    for old in glob.glob(os.path.join(args.out, "*.png")):
        os.remove(old)
    url = "file://" + os.path.abspath(args.page)
    ab = Browser(tool, f"mdpage{os.getpid()}")
    problems = 0
    try:
        for width in WIDTHS:
            for lang in VIEWS:
                show(ab, url, lang, "light", width, 800)
                m = ab.value(MEASURE)
                if not isinstance(m, dict):
                    print(width, lang, "could not measure:", str(m)[:200])
                    problems += 1
                    continue
                bad = m["page"] > m["win"] or m["out"] or m["leak"] or m["unpaired"] or m["lang"] != lang or m["small"] or m["cjk"] > 40
                problems += 1 if bad else 0
                print(f"{'PROBLEM' if bad else 'ok':8}{width:5} {lang} page {m['page']}/{m['win']} height {m['height']} sticking-out {m['out']} other-language {m['leak']} unpaired {m['unpaired']} small-text {m['small']} scrolling-boxes {m['scrollers']} chinese-in-english {m['cjk']}")
        for lang in VIEWS:
            show(ab, url, lang, "light", 375, 800)
            res = str(ab.value(SWITCH))
            problems += 0 if res.startswith(("ok", "skipped")) else 1
            print(f"switch from {lang} keeps the place: {res}")
        made = []
        for lang, media, width, height in SHOTS:
            show(ab, url, lang, media, width, height)
            total = int(ab.value("document.documentElement.scrollHeight") or 0)
            y, k, shots = 0, 0, []
            while True:
                ab("eval", f"window.scrollTo(0,{y})")
                ab("wait", 80)
                path = os.path.join(args.out, f"{lang}-{media}-{width}-{k:03d}.png")
                ab("screenshot", path)
                shots.append(path)
                if y + height >= total:  # this frame reached the bottom of the page
                    break
                y = min(y + height - 80, total - height)
                k += 1
            stem = f"{lang}-{media}-{width}"
            made.extend(sheets(shots, args.out, stem) if width < 640 else shots)
            print(f"{stem}: {len(shots)} screenshots")
        ab("eval", f"localStorage.removeItem('{KEY}')")
    finally:
        ab("close")
    print(f"\nProblems: {problems}. To look at ({len(made)} images):")
    for p in made:
        print(p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
