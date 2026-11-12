---
name: gemini-image
description: Generate an image with the user's own Gemini Pro subscription by driving the Gemini web chat (gemini.google.com) in a headless browser through agent-browser. No API key, no pop-up window, saves the full-size file (up to 2752×1536) to disk. Use whenever the user wants an image, picture, illustration, poster, cover, concept art, icon or "Nano Banana" output made with Gemini, says "用 Gemini 生成图片 / 画一张 / 出图", "generate an image with my Gemini subscription", or asks for an image and mentions Gemini Pro, gemini.google.com or "the chat window" — even if they never say "skill". Also use it to check or repair the saved Google login for this workflow.
---

# gemini-image

Types a prompt into the user's signed-in Gemini chat, waits for the picture, and saves the **full-size** file. It uses the user's Pro quota in the web app, not the API.

```bash
python3 ~/.claude/skills/gemini-image/scripts/gemini.py generate "PROMPT" [--ratio 16:9] [--out PATH] [--ref PHOTO ...]
```

- `--ref PHOTO` (repeatable, added 2026-11-07): attaches a reference photo to the prompt, e.g. a real garment to put on a model. Say in the prompt how to use it ("keep this exact garment: colour, knit, lace, buttons"). The photo goes to Google, so only with the owner's say. Tested 7 Nov 2026 on 11 jobs, 1-5 photos each, all on Pro, about 1 minute each: start the prompt with "Use the attached photos only as the reference for the clothes", name each piece in words as well (colour, trim, print), and add "Do not show hangers, hooks or price tags". Use the plain photos, not collages with a watermark. With 5 photos it still placed every piece. Always compare the result with the reference before using it.

- `--ratio`: `1:1`, `9:16`, `3:4`, `4:3`, `16:9`. Leave it off to let Gemini choose. Measured sizes: 16:9 → 2752×1536, 1:1 → 2048×2048, 9:16 → 1536×2752.
- `--out`: a file or a folder (end a folder with `/`). Default `./gemini-images/<time>-<prompt>.jpg`. Gemini serves JPEG; asking for `.png` converts it, other types keep the real `.jpg` and print a NOTE, so the extension never lies.
- `--model`: `pro` (default), `flash`, or `default`. **Every run switches the chat's model picker to Pro first** (the user's rule, 2026-10-16: "默认都用 Pro 生成图，不用 Flash"), because the picker starts on Auto/Argon/Flash depending on the account. The Pro choice is verified *after* the click: a free account also lists "3.1 Pro", but choosing it opens an "Unlock more models" upgrade wall. In that case the run stops with exit 4 instead of quietly drawing with Auto. Use `--model flash` only if the user asks, `--model default` to leave the picker as the account has it.
- Takes about 40 s. Prints `SAVED <path> <WxH> <bytes>`, `CHAT <url>` and `MODEL <picker label after the image>` (check it says Pro).
- Exit codes: 0 ok · 2 signed out · 4 signed in but no Gemini Pro (do not retry on that account) · 3 Gemini made no image (its own words are printed: quota, policy) · 1 anything else.

After it saves, **check the picture** before telling the user it is done; prompts sometimes come back off-brief. Where reading a local image is fine, Read it. Where it is not (for example when reading a local image would upload it to an outside service you do not want to send it to), use `describe`:

```bash
python3 ~/.claude/skills/gemini-image/scripts/gemini.py describe CHAT_URL --account NAME [--out FILE] [--question "..."]
```

It goes back into the chat that made the picture (same account; use the `CHAT` url `generate` printed) and asks Gemini, text only, to list everything visible (objects, counts, materials, camera angle, light) and everything that looks wrong (garbled letters or digits, duplicates, impossible geometry, departures from the prompt). Nothing local is uploaded, because the picture is already in that chat. It takes about 40 s and prints the answer, or writes it with `--out`. Check the answer against the facts the picture must get right. Gemini's own "no problems" means little; trust only what it describes. (Added 2026-10-16 after a set of illustrations went out with an elevator and a fire escape stopping halfway up, which nobody had looked at.)

## Rules that matter

- **Headless only.** Never pass `--headed`; the user must not get windows popping up. The one exception is `login` below, and warn the user before running it.
- **The prompt goes to Google.** Do not put unpublished manuscripts, personal data or client material into a prompt. Describe the picture instead.
- **One image per run.** For variations, run again with a changed prompt. Each run spends the user's Pro quota; on exit 3, report Gemini's message and stop rather than retrying in a loop.
- **Never accept Gemini's promo or consent cards.** The script closes cards only through "Not now / Acknowledge and close". Buttons such as "Get started" connect other Google apps to Gemini; that decision belongs to the user.
- **Don't print chat history.** The Gemini sidebar lists the user's past chats. When poking at the page by hand, filter or scope snapshots; don't dump them.
- Every run creates a chat in the user's Gemini history (the `CHAT` url). Mention it if they ask where an image came from. Don't delete chats unless they ask.
- Run one at a time **per account**; a lock stops two runs sharing a profile. Different accounts can run at the same time (next section).

## Several Google accounts (added 2026-10-16, health checks 2026-10-23)

The user has several saved Google accounts. Each profile is a separate login, and the quota adds up **only when the Google emails differ**.

```bash
gemini.py accounts                      # stable list: NAME<TAB>cookie|no-cookie (no browser)
gemini.py accounts --health             # + last known PRO/free, email, checked (no browser)
gemini.py accounts --check --jobs 3     # real test of every account; exit 1 if any signed-in account lacks Pro
gemini.py status --account b            # SIGNED_IN (model: Pro, Pro: yes) EMAIL / SIGNED_OUT; exit 4 = no Pro
gemini.py login --account b             # sign in account "b" once (plain Chrome window, see Login)
gemini.py login --account b --fresh     # replace a lapsed profile with a different Google account
gemini.py generate "PROMPT" --account b
```

- `main` is the original account and the default (also `GEMINI_ACCOUNT=b`). Any other name is 1–12 letters or digits (case does not matter, stored lower-case: `Work` = `work`); the user picks it, e.g. `b`, `c`, `work`.
- Each account has its own profile `~/.agent-browser-profiles/gemini-acct-<name>`, lock, agent-browser session and download folder, so parallel runs never pick up each other's files. Same rules as `main` for the profile: it is the credential, never copy or share it, and there is still no cookie backup.
- `accounts` (no flags) is the stable two-column list other tools parse (`NAME<TAB>cookie|no-cookie`); `cookie` only means a sign-in cookie is on disk. `accounts --health` adds the **last known** PRO/free, email and check time (`?` = never checked); both are file-only and a cached result can be stale.
- **`accounts --check` is the real test.** It opens each account headlessly and clicks the Pro row, but makes no image and spends no image quota. Use it before a batch, after a login, or whenever the user asks which accounts still work. It prints one line per account plus how many are usable, which are free, and which share an email. Exit 1 means at least one account is not a usable Pro account.
- **`--fresh`** is for a profile whose account lost Pro (or is the wrong person). It moves the old profile to `<profile>.old-<timestamp>` as a backup, clears the cached email, and opens a clean sign-in window. If the sign-in fails or times out, the old profile is put back automatically, so a bad attempt never leaves the name empty. Nothing is deleted; remove the backup folder later when the new login is confirmed. Without `--fresh`, an already signed-in profile just signs in as the same account again.
- **Parallel work:** run one `generate` per *distinct* account at once (separate background commands, or your own batch script that spreads an image list across the signed-in accounts). Never two runs on the same account, and never count two profiles with the same email as extra capacity.
- **Logging in a new account:** warn the user first, run `login --account NAME` (it opens a plain Chrome window), they sign in with that Google account, it closes itself and re-checks headlessly. Do accounts one at a time; two sign-in windows at once confuse the user.
- After login, `status --account NAME` must say `Pro: yes`. The `(model: …)` part is only the chat's starting picker and does not prove the plan: on 2026-10-23 the paid accounts started on `Argon` or `Gemini Auto`, and the free ones started on `Gemini Auto` while still listing a Pro row. Only the post-click label (`model: Pro`) and `Pro: yes` count.
- On exit 2, exit 4, or an exit 3 about quota/limit, drop that account for this job and use the others; never loop on one account.
- **Lesson from 2026-10-23:** three of the five saved profiles were still signed in but had dropped to the free plan, and two profiles were signed into the same Google email. The model menu looked healthy on all five. `accounts --check` caught both; the old check of reading only the starting label would have missed both.

## Login: sign in once, keep it

Google refuses to sign in inside any automated browser (`navigator.webdriver` is true), so:

1. `python3 …/gemini.py login` opens a **plain** Chrome window on the dedicated profile `~/.agent-browser-profiles/gemini`. The user signs in (2FA included); decline "Sign in to Chrome"/sync. The script sees the Google cookie, closes the window itself, then re-checks headlessly. It also brings Chrome to the front and posts a macOS notification, so a window opened behind other apps is not missed.
2. From then on the automated browser reuses that saved login, headless.
3. For a named account add `--account NAME`; for a profile that should switch to a **different** Google account add `--fresh` (see above). Ex: `gemini.py login --account b --fresh`.

What keeps it alive: the persistent profile (Google's cookies last long and refresh on use), one fixed Chrome binary (`/Applications/Google Chrome.app`) for both sign-in and automation, and a clean close after every run so cookies flush. `gemini.py keepalive` visits Gemini and closes; run it now and then if the skill sits unused for weeks. Verified 2026-10-11: login survived full browser restarts.

It can still lapse (password change, long idle spell, Google's security check). Then `generate` exits 2 and `login` takes about a minute. A login can also stay valid while the **plan** changes: the profile is still signed in but the account is no longer Pro. Then `generate` exits 4; use another account, or `login --account NAME --fresh` with a Pro account.

- `gemini.py status` → `SIGNED_IN (model: Pro, Pro: yes) EMAIL` / `SIGNED_OUT` / exit 4 for a free account.
- The profile folder is the credential. Keep it outside projects, never commit, copy or share it. There is deliberately **no** separate cookie backup file: a second plaintext copy of a Google session is a liability with no proven benefit.
- Don't switch Chrome binaries or delete the profile folder. An older Chrome can't open a profile written by a newer one.

## When something breaks

| Symptom | Likely cause / fix |
|---|---|
| exit 2 `signed out` | run `login` |
| exit 4 `has no Gemini Pro` | signed in but the account lost Pro; choosing Pro shows "Unlock more models". Use another account, upgrade it, or `login --account NAME --fresh` with a Pro account |
| `Pro: no` in `accounts --check` | same as above; the model menu may still list a Pro row, which is why the real check exists |
| `control not found on page: button "…"` on one account only | that account's page layout differs (one account, 2026-10-16: "Upload and tools", "Download full-sized image"); snapshot the page (`snap()` in `gemini.py`), then widen the pattern in `enable_image_mode()` / `DOWNLOAD_BTN` with `(?:a|b)` alternatives, never delete the old spelling |
| the picture is blurry or the wrong subject | don't keep it: redo on another account with Pro and a more specific prompt |
| `BLOCKED` from `status` | a modal or layout change; look at the page by hand (see "Look at the page by hand" in `references/gemini-ui.md`) |
| `could not switch on 'Create image'` | Gemini renamed menu labels; update the patterns in `enable_image_mode()` using `references/gemini-ui.md` |
| `a plain Chrome window is still open` | a login window was left open; quit it (Cmd+Q) |
| exit 3 with Gemini's text | quota, policy or a refusal; change the prompt or wait |
| `agent-browser: command not found` | add `/opt/homebrew/bin` to PATH (the script already does) |

Don't use `agent-browser download` here. It blocks, then its retry re-sends the click and saves duplicate files; the script clicks the button and watches the download folder instead.

## Not covered (yet)

Editing an existing image in place, video, music, several images per request. (Reference photos: `--ref`, since 2026-11-07.) Uploads go through the "Upload & tools" menu; its `input[type=file][accept^="image/"]` exists only while that menu is open (see `references/gemini-ui.md`).
