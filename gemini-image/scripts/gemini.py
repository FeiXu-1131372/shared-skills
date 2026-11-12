#!/usr/bin/env python3
"""Generate images in the Gemini web chat (gemini.google.com) with the user's own
signed-in Google account, driven by agent-browser. Headless by default.

  gemini.py status                 signed in? does the account still have Gemini Pro?  exit 0 yes, 2 signed out, 4 no Pro
  gemini.py login [--fresh]        one-time sign-in in a plain Chrome window; --fresh replaces a lapsed profile
  gemini.py generate "prompt" [--ratio 16:9] [--out PATH] [--model pro|flash|default]
                                   (model picker is switched to Pro on every run unless told otherwise)
  gemini.py keepalive              visit Gemini so Google keeps refreshing the login
  gemini.py accounts [--check]     saved accounts; --check tests each one for a real Gemini Pro plan
  gemini.py describe CHAT_URL      ask Gemini, in the chat that made a picture, to describe that picture
                                   object by object and list what looks wrong (text only; nothing is uploaded)

Several Google accounts: add --account NAME (or set GEMINI_ACCOUNT) to any command above.
"main" (the default) is the original profile; any other NAME (letters and digits, up to 12 chars, stored in lower case) gets
its own profile, lock, browser session and download folder, so runs on different accounts
can go in parallel. One run per account at a time.

Why login uses a plain Chrome window: Google refuses sign-in in any browser that
reports navigator.webdriver=true (every automated browser does). Cookies saved by
a plain Chrome on the same profile folder are accepted by the automated one later.

The profile folder holds the Google session: keep it outside any project, never
commit or share it. Standard library only.
"""
import argparse
import concurrent.futures
import fcntl
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".agent-browser-profiles")
PROFILE = os.path.join(ROOT, "gemini")
DL_DIR = os.path.join(ROOT, "gemini-downloads")  # where Chrome drops downloads before we move them
LOCK = os.path.join(ROOT, "gemini.lock")
SESSION = "gemini"  # own agent-browser session, so other automations never collide with it
ACCOUNT = "main"
# Last known health of each account (email, model, Pro yes/no). Not credentials: no cookies.
# It saves opening five browsers just to answer "which of these can still make a Pro image?".
REGISTRY = os.path.join(ROOT, "gemini-accounts.json")
_MAIN = (PROFILE, LOCK, SESSION, DL_DIR)  # the original account, kept even after use_account() rebinds the names


def account_paths(name):
    """(profile, lock, session, downloads) for an account. 'main' keeps the original names;
    others are gemini-acct-<name>, which can never be a prefix-clash with 'gemini'."""
    name = (name or "").strip().lower()  # "Work" and "work" are the same account
    if not re.fullmatch(r"[a-z0-9]{1,12}", name):
        raise Fail("account name must be 1-12 letters or digits (case does not matter)")
    if name == "main":
        return _MAIN
    base = f"gemini-acct-{name}"
    return (os.path.join(ROOT, base), os.path.join(ROOT, base + ".lock"), base,
            os.path.join(ROOT, base + "-downloads"))


def use_account(name):
    """Point every path below at one account. Called once, before any work."""
    global PROFILE, LOCK, SESSION, DL_DIR, ACCOUNT
    PROFILE, LOCK, SESSION, DL_DIR = account_paths(name)
    ACCOUNT = name.strip().lower()


# One Chrome binary for both sign-in and automation: a profile written by a newer
# Chrome cannot be opened by an older one, so never mix binaries.
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
APP_URL = "https://gemini.google.com/app"
LOGIN_URL = "https://accounts.google.com/ServiceLogin?continue=" + APP_URL
RATIOS = ("1:1", "9:16", "3:4", "4:3", "16:9")

os.environ["PATH"] = os.environ.get("PATH", "") + ":/opt/homebrew/bin"  # sandboxed shells lack it

# Only ever dismiss promo cards with these labels. Buttons like "Get started" or
# "...open consent screen" connect other Google apps to Gemini: that is the user's call.
SAFE_DISMISS = re.compile(r'button "(Acknowledge and close[^"]*|Not now|No thanks|Maybe later)"')
REFUSAL = re.compile(r"can't|cannot|unable|not able|sorry|policy|limit|try again|quota|无法|不能|抱歉|上限|限制", re.I)


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


# ---------- agent-browser plumbing ----------

def ab(*args, input=None, check=True, timeout=90):
    cmd = ["agent-browser", "--session", SESSION, *args]
    p = subprocess.run(cmd, input=input, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise Fail(f"agent-browser {' '.join(args[:2])} failed: {(p.stdout + p.stderr).strip()[:300]}")
    return p.stdout


def js(expr):
    out = ab("eval", "--stdin", input=expr, check=False).strip()
    try:
        v = json.loads(out)
        return json.loads(v) if isinstance(v, str) else v
    except (ValueError, TypeError):
        return None


def snap():
    return ab("snapshot", "-i", check=False)


def refs(pattern, snapshot=None):
    """All refs on lines matching pattern, in page order."""
    s = snapshot if snapshot is not None else snap()
    return [m.group(1) for line in s.splitlines() if re.search(pattern, line)
            for m in [re.search(r"ref=(e\d+)", line)] if m]


def click(pattern, last=False):
    r = refs(pattern)
    if not r:
        raise Fail(f"control not found on page: {pattern}")
    ab("click", "@" + (r[-1] if last else r[0]))


def chrome_mains():
    """(pid, is_automated) for each Chrome main process using our profile."""
    out = subprocess.run(["ps", "-axo", "pid,command"], capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        # the trailing check keeps ".../gemini" from matching ".../gemini-acct-b"
        if cmd.startswith(CHROME) and re.search(re.escape(f"--user-data-dir={PROFILE}") + r"(\s|$)", cmd) \
                and "--type=" not in cmd:
            res.append((int(pid), "--remote-debugging-port" in cmd))
    return res


def launch(url):
    """Make sure the headless automated browser is up on the Gemini profile."""
    if not os.path.exists(CHROME):
        raise Fail(f"Chrome not found at {CHROME}")
    os.makedirs(DL_DIR, exist_ok=True)
    os.makedirs(PROFILE, exist_ok=True)
    os.chmod(PROFILE, 0o700)
    mains = chrome_mains()
    if any(not auto for _, auto in mains):
        raise Fail("a plain Chrome window is still open on the Gemini profile (the login window?). Quit it first.")
    if mains:
        ab("open", url)
        return
    p = subprocess.run(["agent-browser", "--session", SESSION, "--executable-path", CHROME,
                        "--profile", PROFILE, "--download-path", DL_DIR, "open", url],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise Fail("could not start browser: " + (p.stdout + p.stderr).strip()[:300])


def dismiss_blockers():
    """Close promo cards that cover the page. Allowlist only (see SAFE_DISMISS)."""
    for _ in range(4):
        s = snap()
        if 'textbox "Enter a prompt' in s:
            return
        m = SAFE_DISMISS.search(s)
        if not m:
            return
        refs_ = refs(re.escape(m.group(0)), s)
        if not refs_:
            return
        ab("click", "@" + refs_[0], check=False)
        time.sleep(1.5)


def page_state():
    """ready | signed_out | blocked"""
    dismiss_blockers()
    s = snap()
    if 'textbox "Enter a prompt' in s and "mode picker" in s:
        return "ready"
    if 'button "Sign in"' in s or 'link "Sign in"' in s:
        return "signed_out"
    return "blocked"


def open_gemini():
    launch(APP_URL)
    time.sleep(3)
    st = page_state()
    for _ in range(3):  # slow first paint
        if st != "blocked":
            break
        time.sleep(3)
        st = page_state()
    return st


def with_lock(fn, close_after=True, wait=0):
    """Run fn while holding the profile lock. The browser is closed (flushing cookies, freeing the
    profile) only by the run that holds the lock: a refused run must never touch the other's browser.
    wait>0: queue behind another run for up to that many seconds instead of failing at once
    (other sessions may be generating on the same account)."""
    os.makedirs(ROOT, exist_ok=True)
    fh = open(LOCK, "w")
    deadline, told = time.time() + wait, False
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= deadline:
                fh.close()
                raise Fail("another gemini.py run is using the profile; wait for it to finish")
            if not told:
                print(f"[account: {ACCOUNT}] another run is using this account; queuing behind it "
                      f"(up to {wait}s)...", file=sys.stderr, flush=True)
                told = True
            time.sleep(3)
    try:
        return fn()
    finally:
        if close_after:
            ab("close", check=False)
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


# ---------- account health ----------

DIALOG_JS = """(() => {
  const d = document.querySelector('[role=dialog]');
  return JSON.stringify(d ? (d.innerText || '') : '');
})()"""


def dialog_text():
    return js(DIALOG_JS) or ""


def account_email(snapshot=None):
    """The signed-in address from the avatar link, e.g. 'Google Account: Name (user@example.com)'.
    Only the address is returned, never any other account data."""
    s = snapshot if snapshot is not None else snap()
    m = re.search(r'link "Google Account: .*?\(([^)]+@[^)]+)\)"', s)
    return m.group(1) if m else None


def dismiss_upgrade_dialog():
    """Click 'Not now' on the 'Unlock more models' wall. Safe: it only closes the card."""
    s = snap()
    r = refs(r'button "Not now"', s)
    if r:
        ab("click", "@" + r[0], check=False)
        time.sleep(1)
        return True
    return False


def test_pro():
    """Can this account really select Pro? Returns True / False / None (unclear).

    Since 2026-10-23 a free account still *lists* '3.1 Pro'; clicking it opens the
    'Unlock more models' upgrade wall instead of switching. A lapsed account can even
    still show 'Pro' as its remembered label, so always click and verify. No image quota is spent."""
    click(r'button "Open mode picker')
    time.sleep(1.5)
    if not refs(MODEL_ITEM["pro"]):
        ab("press", "Escape", check=False)
        return False
    click(MODEL_ITEM["pro"])
    time.sleep(2)
    cur = current_model()
    if cur and re.search(MODEL_LABEL["pro"], cur, re.I):
        return True
    if "Unlock more models" in dialog_text():
        dismiss_upgrade_dialog()
        return False
    return None


def load_registry():
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_state(name, state, pro=None, model=None, email=None):
    """Merge one account's health into the local registry (0600, no secrets)."""
    os.makedirs(ROOT, exist_ok=True)
    lock = open(REGISTRY + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load_registry()
        data[name] = {"state": state, "pro": pro, "model": model, "email": email,
                      "checked": time.strftime("%Y-%m-%d %H:%M")}
        tmp = REGISTRY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, REGISTRY)
        os.chmod(REGISTRY, 0o600)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def forget_state(name):
    """Drop cached health when a profile is replaced (the email may change)."""
    lock = open(REGISTRY + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load_registry()
        if name in data:
            del data[name]
            tmp = REGISTRY + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, REGISTRY)
            os.chmod(REGISTRY, 0o600)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def describe_health(name, st):
    """One short human label for an account state."""
    if not st:
        return "?"
    if st.get("state") == "signed_in":
        return "PRO" if st.get("pro") is True else ("free" if st.get("pro") is False else "signed in")
    return {"signed_out": "SIGNED_OUT", "blocked": "BLOCKED"}.get(st.get("state"), "?")


def same_email_accounts(email):
    """Other saved profiles signed into the same Google address (they share one quota)."""
    if not email:
        return []
    return sorted(n for n, st in load_registry().items()
                  if n != ACCOUNT and (st.get("email") or "").lower() == email.lower())


# ---------- login ----------

def google_signed_in_cookie(profile=None):
    """True once Chrome has written Google's account cookie. Names only, never values."""
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        src = os.path.join(profile or PROFILE, rel)
        if not os.path.exists(src):
            continue
        tmp = tempfile.mktemp(suffix=".sqlite")
        try:
            shutil.copy(src, tmp)
            con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
            n = con.execute("select count(*) from cookies where host_key like '%google.com' "
                            "and name in ('__Secure-1PSID','SID')").fetchone()[0]
            con.close()
            if n:
                return True
        except sqlite3.Error:
            pass
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return False


def _login_window(a):
    """Open the plain Chrome sign-in window and wait for Google's cookie, then verify headlessly."""
    print(f"[account: {ACCOUNT}] Opening a plain Chrome window. Sign in with the Google account that has Gemini Pro.\n"
          "If Chrome offers 'Sign in to Chrome' / sync, decline. The window closes itself once you are in.")
    p = subprocess.Popen([CHROME, f"--user-data-dir={PROFILE}", "--use-mock-keychain", "--no-first-run",
                          "--no-default-browser-check", LOGIN_URL],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # A directly launched Chrome can open behind the terminal. Bring it forward so the
    # user sees what to sign in to (macOS only; harmless if osascript is unavailable).
    subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'],
                   capture_output=True, check=False)
    subprocess.run(["osascript", "-e",
                    f'display notification "Sign in with a Gemini Pro Google account" '
                    f'with title "Gemini login: {ACCOUNT}"'],
                   capture_output=True, check=False)
    deadline, seen = time.time() + a.wait, None
    while time.time() < deadline and p.poll() is None:
        if google_signed_in_cookie():
            seen = seen or time.time()
            if time.time() - seen > 10:  # let the user land on Gemini and Chrome flush cookies
                break
        time.sleep(3)
    if p.poll() is None:
        p.send_signal(signal.SIGTERM)  # graceful: flushes the profile to disk
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            raise Fail("Chrome would not quit; press Cmd+Q in its window, then run `status`")
    if not seen and not google_signed_in_cookie():
        raise Fail("no Google sign-in detected before the window closed or the wait ran out")
    print("Signed in. Verifying in headless mode...")
    return cmd_status(a)


def cmd_login(a):
    ab("close", check=False)
    time.sleep(1)
    if chrome_mains():
        raise Fail("a Chrome is already running on the Gemini profile; quit it first")
    backup = None
    if getattr(a, "fresh", False) and os.path.isdir(PROFILE):
        # Keep the old login as a timestamped backup instead of deleting it. The old
        # Google account is untouched server-side; only this local profile starts clean.
        backup = PROFILE + ".old-" + time.strftime("%Y%m%d-%H%M%S")
        os.rename(PROFILE, backup)
        forget_state(ACCOUNT)
        print(f"[account: {ACCOUNT}] old profile moved to {backup} (a backup; delete it when you no longer need it)")
    os.makedirs(PROFILE, exist_ok=True)
    os.chmod(PROFILE, 0o700)
    try:
        return _login_window(a)
    except Fail:
        # A failed --fresh sign-in must not leave the account name empty. Put the old
        # login back unless the new window did get a Google cookie (then keep both).
        if backup and not google_signed_in_cookie():
            try:
                shutil.rmtree(PROFILE, ignore_errors=True)
                os.rename(backup, PROFILE)
                print(f"[account: {ACCOUNT}] sign-in did not complete; old profile restored", file=sys.stderr)
            except OSError:
                print(f"[account: {ACCOUNT}] could not restore automatically; the old profile is at {backup}",
                      file=sys.stderr)
        raise


# ---------- status / keepalive ----------

def cmd_status(a):
    st = open_gemini()
    email = account_email() if st == "ready" else None
    pro = test_pro() if st == "ready" else None
    mode = current_model()  # after the Pro test: proof of what the picker now reads
    ab("close", check=False)  # closing flushes cookies to the profile
    if st == "ready":
        record_state(ACCOUNT, "signed_in", pro=pro, model=mode, email=email)
        dups = same_email_accounts(email)
        if dups:
            print(f"NOTE: {email} is also signed in as {', '.join(dups)}; "
                  f"they share one quota (this profile does not add capacity).", file=sys.stderr)
        if getattr(a, "json", False):
            print(json.dumps({"account": ACCOUNT, "state": "signed_in", "pro": pro,
                              "model": mode, "email": email}, ensure_ascii=False))
        else:
            if pro is True:
                plan = "yes"
            elif pro is False:
                plan = "no"
            else:
                plan = "?"
            who = f" {email}" if email else ""
            print(f"SIGNED_IN (model: {mode or '?'}, Pro: {plan}){who}")
            if pro is False:
                print("WARNING: this account has no Gemini Pro: selecting Pro opens the "
                      "'Unlock more models' upgrade wall. Use another account, or upgrade this one.",
                      file=sys.stderr)
        return 0 if pro is True else (4 if pro is False else 1)
    state = "signed_out" if st == "signed_out" else "blocked"
    record_state(ACCOUNT, state)
    if getattr(a, "json", False):
        print(json.dumps({"account": ACCOUNT, "state": state, "pro": None,
                          "model": None, "email": None}, ensure_ascii=False))
    else:
        print("SIGNED_OUT" if st == "signed_out" else "BLOCKED (unexpected page; run with a screenshot to look)")
    return 2


# ---------- generate ----------

def slugify(text):
    return re.sub(r"[^\w]+", "-", text[:40]).strip("-") or "image"


def sniff(path):
    with open(path, "rb") as f:
        head = f.read(12)
    if head[:2] == b"\xff\xd8":
        return "jpg"
    if head[:4] == b"\x89PNG":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def resolve_out(out, prompt, ext):
    name = time.strftime("%Y%m%d-%H%M%S-") + slugify(prompt)
    if not out:
        return os.path.join(os.getcwd(), "gemini-images", f"{name}.{ext}")
    wants_dir = out.endswith("/")  # abspath() strips the slash, so look before normalising
    out = os.path.abspath(os.path.expanduser(out))
    if wants_dir or os.path.isdir(out):
        return os.path.join(out, f"{name}.{ext}")
    return out if os.path.splitext(out)[1] else f"{out}.{ext}"


def finalize(raw, out, prompt):
    """Move the downloaded file to its destination. Gemini serves JPEG; if the caller
    asked for .png/.webp, convert with sips, otherwise never mislabel: use the real extension."""
    ext = sniff(raw) or "jpg"
    dest = resolve_out(out, prompt, ext)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    want = os.path.splitext(dest)[1].lstrip(".").lower().replace("jpeg", "jpg")
    if want != ext and want in ("png", "jpg") and shutil.which("sips"):  # sips cannot write webp
        try:
            subprocess.run(["sips", "-s", "format", {"jpg": "jpeg"}.get(want, want), raw, "--out", dest],
                           capture_output=True, check=True)
            os.remove(raw)
            return dest
        except subprocess.CalledProcessError:
            pass
    if want != ext:
        dest = os.path.splitext(dest)[0] + "." + ext
        print(f"NOTE: could not convert to .{want}; saved as real {ext.upper()} as {os.path.basename(dest)}", file=sys.stderr)
    shutil.move(raw, dest)
    return dest


MODEL_ITEM = {  # the picker's menu rows look like: menuitem "3.1 Pro Advanced reasoning"
    "pro": r'menuitem(?:radio)? "(?:Selected )?[\d.]+ Pro\b',  # menuitemradio since 7 Nov 2026
    "flash": r'menuitem(?:radio)? "(?:Selected )?[\d.]+ Flash(?!-)',
}
MODEL_LABEL = {"pro": r"\bpro\b", "flash": r"\bflash\b(?!-)"}  # what `currently X` reads after selecting


def current_model():
    m = re.search(r'mode picker, currently ([^"]+)"', snap())
    return m.group(1) if m else None


def select_model(want):
    """Switch the chat's model picker to Pro (default) or Flash before generating. Accounts differ in
    what the picker starts on, so never rely on the default. 'default' leaves it alone.

    A free account still lists a Pro row and only shows the upgrade wall after the click, so a
    selected-looking menu is not proof. Only the picker label after the click is."""
    if want == "default":
        return
    cur = current_model()
    if want != "pro" and cur and re.search(MODEL_LABEL[want], cur, re.I):
        return  # Flash is not plan-gated; only Pro needs a fresh proof
    click(r'button "Open mode picker')
    time.sleep(1.5)
    free_hint = ' (this account shows an "Upgrade" link; it is probably on the free Gemini Auto plan)' \
        if 'link "Upgrade"' in snap() else ""
    if not refs(MODEL_ITEM[want]):
        ab("press", "Escape", check=False)
        raise Fail(f"no {want.upper()} entry in the model picker (menu changed, or the account lacks it)"
                   + free_hint)
    click(MODEL_ITEM[want])
    time.sleep(2)
    now = current_model()
    if now and re.search(MODEL_LABEL[want], now, re.I):
        return
    if "Unlock more models" in dialog_text():
        dismiss_upgrade_dialog()
        raise Fail(f"account '{ACCOUNT}' has no Gemini Pro: choosing Pro opens the 'Unlock more models' "
                   "upgrade wall. Use another account, or upgrade this one.", code=4)
    raise Fail(f"could not switch the model picker to {want.upper()} (it reads {now!r})" + free_hint)


UPLOAD_INPUT = 'input[type=file][accept^="image/"]'  # exists only while "Upload and tools" is open (7 Nov 2026)
BLOB_IMGS_JS = "JSON.stringify(Array.from(document.querySelectorAll('img')).filter(i => i.src.startsWith('blob:')).length)"


def attach_refs(paths):
    """Attach reference photos to the prompt (added 7 Nov 2026). The image input is created when the
    "Upload and tools" menu opens, so open it, set the files, wait for each preview, then close the menu."""
    paths = [os.path.abspath(os.path.expanduser(p)) for p in paths]
    for p in paths:
        if not os.path.isfile(p):
            raise Fail(f"reference photo not found: {p}")
    before = js(BLOB_IMGS_JS) or 0
    click(r'button "Upload (?:&|and) tools"')
    time.sleep(1.5)
    ab("upload", UPLOAD_INPUT, *paths, timeout=120)
    deadline = time.time() + 90
    while time.time() < deadline:
        if (js(BLOB_IMGS_JS) or 0) >= before + len(paths):
            break
        time.sleep(2)
    else:
        raise Fail("the reference photos did not finish attaching", code=3)
    ab("press", "Escape", check=False)
    time.sleep(1)


def enable_image_mode():
    if "Deselect Images" in snap():
        return
    click(r'button "Upload (?:&|and) tools"')  # newer layout spells it "Upload and tools" (seen on one account)
    time.sleep(1)
    click(r'menuitemcheckbox "Create image"')
    time.sleep(1)
    if "Deselect Images" not in snap():
        raise Fail("could not switch on 'Create image' (Gemini's menu changed?)")


def set_ratio(ratio):
    click(r'button "Aspect ratio"')
    time.sleep(1)
    click(rf'menuitemradio "{re.escape(ratio)}"')
    time.sleep(1)


GEN_JS = """(() => {
  const turns = document.querySelectorAll('model-response');
  const t = turns[turns.length - 1];
  if (!t) return JSON.stringify({turn: false});
  const img = Array.from(t.querySelectorAll('img')).find(i => /AI generated/i.test(i.alt) && i.naturalWidth > 200);
  return JSON.stringify({turn: true, img: !!img, text: (t.innerText || '').trim().slice(0, 400)});
})()"""


def wait_for_image(timeout):
    deadline, last_text, same = time.time() + timeout, None, 0
    while time.time() < deadline:
        r = js(GEN_JS) or {}
        if r.get("img"):
            return
        text = r.get("text") or ""
        same = same + 1 if text and text == last_text else 0
        last_text = text
        if same >= 2 and REFUSAL.search(text):  # steady text that reads like a refusal or a quota message
            raise Fail("Gemini did not make an image. It said: " + text, code=3)
        time.sleep(4)
    raise Fail("timed out waiting for the image. Gemini's last text: " + (last_text or "(none)"), code=3)


# The label differs by account/layout: "Download full size image" (main) vs "Download full-sized image" (another account, 2026-10-16)
DOWNLOAD_BTN = r'button "Download full[- ]size[d]? image"'


def grab_download(timeout=180):
    """Click 'Download full size image' and pick the finished file out of DL_DIR.
    (`agent-browser download` blocks, then retries the click, so it is not used.)"""
    before = set(os.listdir(DL_DIR))
    deadline = time.time() + 60  # the button can appear a moment after the preview
    while time.time() < deadline and not refs(DOWNLOAD_BTN):
        time.sleep(2)
    click(DOWNLOAD_BTN, last=True)
    deadline, prev = time.time() + timeout, None
    while time.time() < deadline:
        new = [f for f in os.listdir(DL_DIR) if f not in before and not f.endswith((".crdownload", ".tmp"))]
        if new:
            path = os.path.join(DL_DIR, new[0])
            size = os.path.getsize(path)
            if size > 0 and size == prev:  # unchanged across two polls = finished
                return path
            prev = size
        time.sleep(2)
    raise Fail("the full-size download did not arrive in time", code=3)


def cmd_generate(a):
    if a.ratio and a.ratio not in RATIOS:
        raise Fail(f"--ratio must be one of {', '.join(RATIOS)}")
    st = open_gemini()
    if st == "signed_out":
        raise Fail("signed out of Google. Run: gemini.py login", code=2)
    if st != "ready":
        raise Fail("Gemini page is in an unexpected state (modal or layout change)")
    select_model(a.model)
    if a.ref:
        attach_refs(a.ref)
    enable_image_mode()
    if a.ratio:
        set_ratio(a.ratio)
    click(r'textbox "Enter a prompt')  # focus
    ab("fill", "@" + refs(r'textbox "Enter a prompt')[0], a.prompt)
    ab("press", "Enter")
    time.sleep(3)
    wait_for_image(a.timeout)
    model = current_model()  # what the picker reads now: the proof of which model made the picture
    chat_url = ab("get", "url", check=False).strip()
    dest = finalize(grab_download(), a.out, a.prompt)
    dims = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", dest], capture_output=True, text=True).stdout
    w = re.search(r"pixelWidth: (\d+)", dims)
    h = re.search(r"pixelHeight: (\d+)", dims)
    print(f"SAVED {dest} {w.group(1) + 'x' + h.group(1) if w and h else ''} {os.path.getsize(dest)} bytes")
    print(f"CHAT {chat_url}")
    print(f"MODEL {model or '?'}")
    return 0


# ---------- describe (look at a picture without uploading it) ----------

DESCRIBE_Q = ("Do not generate or edit any image. Only answer in text. Look carefully at the image you generated "
              "above (the final one) and describe exactly what is visible, as a plain list: the setting, every object, "
              "how many of each, materials and colours, camera angle, light. Then list anything that looks odd, "
              "garbled (any letters, digits or symbols), duplicated, physically impossible, or different from what the "
              "prompt asked for. Be literal and critical; do not repeat the prompt from memory.")

LAST_TEXT_JS = """(() => {
  const turns = document.querySelectorAll('model-response');
  const t = turns[turns.length - 1];
  return JSON.stringify({n: turns.length, text: t ? (t.innerText || '').trim() : ''});
})()"""


def clean_answer(text):
    """Drop the page chrome Gemini's innerText carries ('Gemini said', the 'JPG' chips, '+ 1' source badges)."""
    keep = [ln.rstrip() for ln in text.splitlines()
            if ln.strip() and ln.strip() not in ("JPG", "Gemini said") and not re.fullmatch(r"\+ ?\d+", ln.strip())]
    return "\n".join(keep)


def cmd_describe(a):
    """Claude cannot look at local pictures in this environment (reading one uploads it). The picture already
    lives in the Gemini chat that made it, so ask there: same account, same chat, text answer only."""
    if not re.match(r"https://gemini\.google\.com/app/[0-9a-f]+$", a.chat or ""):
        raise Fail("describe needs the CHAT url printed by generate (https://gemini.google.com/app/<id>)")
    launch(a.chat)
    time.sleep(6)
    st = page_state()
    if st == "signed_out":
        raise Fail("signed out of Google. Run: gemini.py login", code=2)
    select_model(a.model)
    before = (js(LAST_TEXT_JS) or {}).get("n", 0)
    if before == 0:
        raise Fail("that chat has no answer in it (wrong account for this chat?)")
    if "Deselect Images" in snap():  # image mode would make it draw again
        click(r'button "Deselect Images')
        time.sleep(1)
    click(r'textbox "Enter a prompt')
    ab("fill", "@" + refs(r'textbox "Enter a prompt')[0], a.question or DESCRIBE_Q)
    ab("press", "Enter")
    deadline, last, same = time.time() + a.timeout, None, 0
    while time.time() < deadline:
        time.sleep(5)
        r = js(LAST_TEXT_JS) or {}
        if r.get("n", 0) <= before:
            continue
        t = r.get("text", "")
        same = same + 1 if t and t == last else 0
        last = t
        if same >= 2 and len(t) > 80:
            break
    else:
        raise Fail("timed out waiting for the description", code=3)
    text = clean_answer(last)
    if len(text) < 400 and REFUSAL.search(text):  # "I'm having a hard time fulfilling your request" is not a description
        raise Fail("Gemini did not describe the picture. It said: " + text, code=3)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"DESCRIBED {a.out} {len(text)} chars")
    else:
        print(text)
    return 0


def cmd_keepalive(a):
    rc = cmd_status(a)
    return rc


def saved_accounts():
    """Names of every account that has a profile folder, 'main' first. No browser, no cookie values."""
    names = []
    if os.path.isdir(_MAIN[0]):
        names.append("main")
    if os.path.isdir(ROOT):
        for d in sorted(os.listdir(ROOT)):
            m = re.fullmatch(r"gemini-acct-([a-z0-9]{1,12})", d)
            if m and os.path.isdir(os.path.join(ROOT, d)):
                names.append(m.group(1))
    return names


def run_status(name, timeout=300):
    """Run `status --json` for one account in its own process (so parallel checks stay isolated)."""
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "status", "--json", "--account", name],
                       capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or "").strip().splitlines()
    for line in reversed(out):
        try:
            return json.loads(line)
        except ValueError:
            continue
    err = (p.stderr or p.stdout or "").strip().splitlines()
    return {"account": name, "state": "error", "pro": None, "model": None, "email": None,
            "error": (err[-1] if err else f"status exited {p.returncode}")[:300]}


def health_label(r):
    if r.get("state") == "signed_in":
        return "PRO" if r.get("pro") is True else ("free" if r.get("pro") is False else "signed in")
    return {"signed_out": "SIGNED_OUT", "blocked": "BLOCKED",
            "error": "ERROR"}.get(r.get("state"), "?")


def check_accounts(names, a):
    results, errors = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        futs = {pool.submit(run_status, n): n for n in names}
        for fut in concurrent.futures.as_completed(futs):
            n = futs[fut]
            try:
                results[n] = fut.result()
            except Exception as e:  # timeout, process killed, ...
                results[n] = {"account": n, "state": "error", "pro": None, "model": None,
                              "email": None, "error": str(e)[:300]}
            if results[n].get("state") == "error":
                errors[n] = results[n].get("error", "")
    rows = [results.get(n, {"account": n, "state": "error", "pro": None, "model": None, "email": None})
            for n in names]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"{r['account']}\t{health_label(r)}\t{r.get('model') or '-'}\t{r.get('email') or '-'}")
        pro = [r["account"] for r in rows if r.get("state") == "signed_in" and r.get("pro") is True]
        free = [r["account"] for r in rows if r.get("state") == "signed_in" and r.get("pro") is False]
        bad = [r["account"] for r in rows if r.get("state") != "signed_in"]
        print(f"\n{len(pro)} Pro profile(s): {', '.join(pro) if pro else '(none)'}")
        if free:
            print(f"{len(free)} signed in but without Pro: {', '.join(free)} "
                  f"(upgrade, or replace with `login --account NAME --fresh`)")
        # Two profiles can be signed into the same Google account (e.g. an old copy). Their
        # quotas do not add up, so parallel work on them buys nothing.
        by_email = {}
        for r in rows:
            if r.get("state") == "signed_in" and r.get("email"):
                by_email.setdefault(r["email"], []).append(r["account"])
        for email, group in by_email.items():
            if len(group) > 1:
                print(f"NOTE: {', '.join(group)} are the same Google account ({email}); "
                      f"they share one quota, so do not count them as separate capacity.")
        if bad:
            print(f"{len(bad)} not usable: {', '.join(bad)} (run `status --account NAME` for the reason)")
        if errors:
            print("Errors: " + "; ".join(f"{n}: {e}" for n, e in errors.items()))
    return 0 if all(r.get("state") == "signed_in" and r.get("pro") is True for r in rows) else 1


def cmd_accounts(a):
    """Default output is the stable NAME<TAB>cookie|no-cookie list (other tools parse it).
    --health adds cached email/plan, still no browser. --check really tests every account
    (opens each headlessly, clicks Pro, no image quota) and updates the cache."""
    names = saved_accounts()
    if not names:
        print("(no accounts saved yet; run: gemini.py login)")
        return 0
    if getattr(a, "check", False):
        return check_accounts(names, a)
    data = load_registry()
    for n in names:
        cookie = "cookie" if google_signed_in_cookie(account_paths(n)[0]) else "no-cookie"
        if getattr(a, "health", False):
            st = data.get(n)
            print(f"{n}\t{cookie}\t{describe_health(n, st)}\t{(st or {}).get('email') or '-'}\t"
                  f"{(st or {}).get('checked') or '-'}")
        else:
            print(f"{n}\t{cookie}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--account", default=os.environ.get("GEMINI_ACCOUNT", "main"),
                        help="which saved Google account (default: main, or $GEMINI_ACCOUNT)")
    st = sub.add_parser("status", parents=[common])
    st.add_argument("--json", action="store_true", help="machine-readable one-line result")
    st.set_defaults(fn=cmd_status)
    sub.add_parser("keepalive", parents=[common]).set_defaults(fn=cmd_keepalive)
    ap_accounts = sub.add_parser("accounts")
    ap_accounts.add_argument("--check", action="store_true",
                             help="really test every account (opens browsers in parallel; no image quota)")
    ap_accounts.add_argument("--health", action="store_true",
                             help="add last known plan/email (cached; no browser)")
    ap_accounts.add_argument("--jobs", type=int, default=3, help="accounts to check at once (default 3)")
    ap_accounts.add_argument("--json", action="store_true", help="machine-readable list")
    ap_accounts.set_defaults(fn=cmd_accounts)
    lp = sub.add_parser("login", parents=[common])
    lp.add_argument("--wait", type=int, default=900, help="seconds to wait for sign-in")
    lp.add_argument("--fresh", action="store_true",
                    help="move the existing profile aside and start a clean sign-in (replacing a lapsed account)")
    lp.set_defaults(fn=cmd_login)
    gp = sub.add_parser("generate", parents=[common])
    gp.add_argument("prompt")
    gp.add_argument("--ref", action="append", metavar="PHOTO",
                    help="a reference photo to attach (repeat for several); the prompt says how to use it")
    gp.add_argument("--ratio", help="one of " + ", ".join(RATIOS) + " (default: let Gemini choose)")
    gp.add_argument("--out", help="file path or directory (default ./gemini-images/<time>-<prompt>.jpg)")
    gp.add_argument("--timeout", type=int, default=240, help="seconds to wait for the image")
    gp.add_argument("--model", choices=("pro", "flash", "default"), default="pro",
                    help="model picker setting: pro (default, always switched to), flash, or default (leave it as the account has it)")
    gp.add_argument("--lock-wait", type=int, default=900,
                    help="seconds to queue behind another run on the same account before giving up (0 = fail at once)")
    gp.set_defaults(fn=cmd_generate)
    dp = sub.add_parser("describe", parents=[common])
    dp.add_argument("chat", help="the CHAT url that generate printed (use the same --account that made it)")
    dp.add_argument("--out", help="write the description to this file instead of printing it")
    dp.add_argument("--question", help="ask something else about the picture (default: describe it and list faults)")
    dp.add_argument("--timeout", type=int, default=240)
    dp.add_argument("--model", choices=("pro", "flash", "default"), default="pro")
    dp.add_argument("--lock-wait", type=int, default=900)
    dp.set_defaults(fn=cmd_describe)
    a = ap.parse_args()
    try:
        if a.cmd == "accounts":  # reads files only: no lock, no browser
            sys.exit(cmd_accounts(a))
        use_account(getattr(a, "account", "main"))
        rc = with_lock(lambda: a.fn(a), close_after=(a.cmd != "login"), wait=getattr(a, "lock_wait", 0))
    except Fail as e:
        print(f"ERROR: {e}", file=sys.stderr)
        rc = e.code
    sys.exit(rc)


if __name__ == "__main__":
    main()
