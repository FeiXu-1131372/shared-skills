# Gemini web UI notes (observed 2026-10-11, Pro account, English UI; model/plan changes 2026-10-23)

Gemini changes its labels from time to time. If a step in `scripts/gemini.py` stops matching, re-check
these against a fresh `agent-browser --session gemini snapshot -i`. Scope or filter snapshots: the
sidebar lists the user's chat titles.

## Look at the page by hand

Runs close the browser when they finish, so open it yourself (headless, same profile and Chrome as the
script; `--download-path` must match too if you will test downloads), inspect, then close it:

```bash
export PATH="$PATH:/opt/homebrew/bin"
agent-browser --session gemini --executable-path "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --profile ~/.agent-browser-profiles/gemini --download-path ~/.agent-browser-profiles/gemini-downloads \
  open https://gemini.google.com/app
agent-browser --session gemini snapshot -i | grep -v 'link "'     # controls without the chat-history sidebar
agent-browser --session gemini screenshot --screenshot-dir <scratch dir>
agent-browser --session gemini close                              # always: flushes cookies, frees the profile
```

Don't run `gemini.py` while that browser is open; it would reuse it. For a named account, swap
`gemini` for `gemini-acct-<name>` in all three places (`--session`, `--profile`, `--download-path`).

## Controls the script relies on (accessibility-tree labels)

| Purpose | Label |
|---|---|
| Prompt box | `textbox "Enter a prompt for Gemini"` |
| Signed-in marker | `button "Open mode picker, currently <label>"` (and no `button "Sign in"`); the avatar link `link "Google Account: NAME (email)"` gives the address |
| Model menu (paid account) | `menuitem "3.5 Flash-Lite …"`, `"3.8 Flash …"`, `"3.1 Pro …"`, `"Selected 4 Argon …"`; no Upgrade link. **Since 7 Nov 2026 the rows are `menuitemradio`, not `menuitem`**: the patterns in `MODEL_ITEM` accept both |
| Model menu (free account, 2026-10-23) | `"Selected Auto Gemini 3 models"`, `"3.1 Pro …"`, `"4 Argon …"`, plus `link "Upgrade"` outside the menu. **The Pro row is still listed.** |
| Pro upgrade wall | choosing `3.1 Pro` on a free account opens dialog `Unlock more models` with `button "Upgrade"` and `button "Not now"`; the picker label does not change |
| Tools menu | `button "Upload & tools"` → items: Upload files, Add from Drive, **`menuitemcheckbox "Create image"`**, Create video, Create music, Canvas |
| Image mode is on | chip `button "Deselect Images"` appears by the prompt box |
| Aspect ratio | `button "Aspect ratio"` → `menuitemradio` "1:1", "9:16", "3:4", "4:3", "16:9" (none ticked = Gemini decides) |
| Result | inside `<model-response>`: `<img alt=", AI generated">` (preview ~1024 px wide) |
| Full size | `button "Download full size image"` in the same response (also: Share image, Copy image, Redo) |
| Style chips | a row of presets (Cinematic, Cyborg…) shows in image mode; optional, ignored |

Image mode does **not** persist into a new chat; the script switches it on every run.

## Behaviour worth knowing

- **A menu row is not a plan.** Since 2026-10-23 a free account lists `3.1 Pro` exactly like a paid one. Only clicking it tells the truth: paid switches the picker to `Pro`; free opens the `Unlock more models` dialog. `gemini.py status` and `accounts --check` click it and dismiss the wall with `Not now` (safe; no image quota).
- The starting picker label varies by account and plan (`Pro`, `Argon`, `Gemini Auto`, `Flash`). It says nothing about the plan; the label after a successful Pro click does.
- The `Google Account: NAME (email)` avatar link exposes the signed-in address. Two profiles can share one email; they then share one quota, so don't count them as parallel capacity.
- Full-size download is a real file: ~2.4–4.2 MB JPEG, 2K-class (2752×1536 for 16:9). The preview on the page is smaller.
- Clicking the download button lands the file in Chrome's download folder (`--download-path`, here `~/.agent-browser-profiles/gemini-downloads`), under a GUID name. The script waits for a file whose size stops changing.
- `agent-browser download @ref path` blocks for a long time; on a socket timeout the CLI retries up to 5 times and each retry re-clicks, saving 5 identical files. Use click + poll instead. The same retry applies to any non-idempotent command if the daemon is busy, so don't run parallel commands against the same session while a download is pending.
- First sign-in shows a promo dialog "Supercharge Gemini with Personal Intelligence" with two buttons: "Acknowledge and close the discovery card" (safe) and "Acknowledge and open consent screen" (connects Google apps; never click).
- While such a modal is open, the accessibility snapshot shows only the modal's buttons, so "signed in" detection must dismiss it first.
- A new `/app` page is a fresh chat; each generation creates a chat in the user's history.

## Why sign-in needs a plain Chrome window

In the automated browser `navigator.webdriver === true`, and Google answers the sign-in with "This browser or app may not be secure". A plain Chrome launched with `--user-data-dir=<profile> --use-mock-keychain --no-first-run` has no such flag and signs in normally. `--use-mock-keychain` must match what agent-browser launches with, otherwise the automated browser cannot decrypt the cookies the plain one wrote. Cookies from that window are then accepted in the automated, headless browser.

## Ideas for extending

- Reference image (built 7 Nov 2026 as `--ref`, see `attach_refs()`): open `button "Upload & tools"`, then `agent-browser upload 'input[type=file][accept^="image/"]' PHOTO...` while the menu is still open (the input is removed when the menu closes, so pressing Escape first gives "element not found"). Wait until the page has one more `img[src^="blob:"]` per photo, then Escape to close the menu. Several photos go in one upload call. Editing an existing image in place is still not built.
- `--n`: loop `generate` with the same prompt; each is a separate chat and a separate quota hit.
