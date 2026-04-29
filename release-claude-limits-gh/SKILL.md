---
name: release-claude-limits-gh
description: Cut and publish a new GitHub release of FeiXu-1131372/claude-limits from the current commit on main. Bumps the version files, commits, tags, pushes, pre-creates the release record so the CI workflow can append bundle assets, and watches the build.
user-invokable: true
args:
  - name: bump
    description: Version bump kind. One of `patch`, `minor`, `major`, or an explicit version like `1.2.3`. Defaults to `patch`.
    required: false
---

# Release a new version of claude-limits to GitHub

This skill cuts a new tagged release of the `claude-limits` Tauri app on `https://github.com/FeiXu-1131372/claude-limits`. The CI workflow at `.github/workflows/release.yml` builds bundles for macOS (universal `.dmg` + `.app.tar.gz`) and Windows (`.nsis` installer) on every `v*` tag push and uploads them to the matching release.

## Pre-flight checklist (HARD STOPS)

Run these checks first. If any fails, stop and report — don't try to recover.

1. **Working tree must be clean.** Run `git status --short`. If anything is listed, ask the user what to do — likely commit or stash before continuing.
2. **Must be on `main`.** Run `git rev-parse --abbrev-ref HEAD`. If not `main`, ask the user — they may have meant to release a feature branch first.
3. **Local `main` must be up to date with `origin/main`.** Run `git fetch origin main` then `git rev-list --left-right --count HEAD...origin/main`. If `behind > 0`, pull first; if `ahead > 0` but the user hasn't pushed yet, push before tagging.
4. **Tag must not already exist locally or remotely.** Run `git tag -l "v$NEW_VERSION"` and `git ls-remote --tags origin "v$NEW_VERSION"`. If either returns the tag, abort — moving an existing tag is destructive and not what this skill does.
5. **GitHub release must not already exist.** Run `gh release view "v$NEW_VERSION" --repo FeiXu-1131372/claude-limits` (expect "release not found" — anything else means a release already exists at that version).

## Determining the new version

1. Read the current version from `src-tauri/Cargo.toml`'s `[package].version` field. This is the canonical source.
2. Apply the bump:
   - If `args.bump` is omitted or `patch`: `X.Y.Z` → `X.Y.(Z+1)`
   - If `minor`: `X.Y.Z` → `X.(Y+1).0`
   - If `major`: `X.Y.Z` → `(X+1).0.0`
   - If a literal version like `1.2.3`: use it verbatim. Validate it is a valid semver and strictly greater than the current version.
3. Print the planned bump to the user (`bumping 0.2.0 → 0.2.1`) and pause for confirmation if the user hasn't been explicit.

## Steps

### 1. Update version files

Three files carry the version. Update all of them so cargo, npm, and the Tauri bundle all see the same string:

- `src-tauri/Cargo.toml` — change `version = "X.Y.Z"` in `[package]`
- `package.json` — change the `"version"` field
- `src-tauri/Cargo.lock` — do NOT edit by hand. After bumping `Cargo.toml`, run `cargo check` from `src-tauri/` to let cargo regenerate the locked entry for `claude-limits`. (Skipping this leaves Cargo.lock pointing at the old version and CI gets a dirty lockfile.)

`tauri.conf.json` does NOT carry a version field in this project — Tauri reads it from `Cargo.toml` via `productName`/`version` discovery. Don't touch tauri.conf.json.

### 2. Verify everything builds

Run **all** of these from the repo root, in this order, and abort on the first failure:

```
pnpm install --frozen-lockfile
pnpm lint
pnpm test
( cd src-tauri && cargo test --lib )
( cd src-tauri && cargo clippy --all-targets -- -D warnings )
```

Note: macOS-local `cargo clippy` does NOT lint `#[cfg(windows)]` bodies. The CI Windows job is the only authoritative check for those — see `feedback_cfg_gated_lints.md` in memory. Don't be surprised if a lint slips through here and CI catches it; just push a follow-up and re-trigger the tag (see "Post-release recovery" below).

### 3. Commit the version bump

Stage the three changed files (Cargo.toml, Cargo.lock, package.json) and create one commit:

```
git add src-tauri/Cargo.toml src-tauri/Cargo.lock package.json
git commit -m "release: vX.Y.Z"
```

Use the literal `release: vX.Y.Z` form — matches the existing convention from `fa99bce release: v0.2.0`. Do NOT add a `Co-Authored-By: Claude` trailer (project hard rule, see `feedback_no_claude_coauthor.md` in memory).

### 4. Push main

```
git push origin main
```

Wait for it to succeed. The push triggers the `test` workflow but NOT the `release` workflow yet (release only fires on tag push).

### 5. Tag and push the tag

```
git tag vX.Y.Z
git push origin vX.Y.Z
```

The tag push triggers `.github/workflows/release.yml`. From now on the macOS and Windows runners are building.

### 6. Pre-create the GitHub release record

Pre-creating the release means `tauri-action` finds an existing release on its first lookup and appends bundles to it instead of trying to create one (the create step needs `contents: write` and the append step is more forgiving). Use `gh release create` with descriptive notes:

```
gh release create vX.Y.Z \
  --repo FeiXu-1131372/claude-limits \
  --title "vX.Y.Z" \
  --notes "<release notes here>"
```

For the `--notes` body, draft a short summary based on what landed since the previous release. Look at `git log v$PREVIOUS_VERSION..vX.Y.Z --oneline` to see what changed. Group by area (auth / ui / fix / docs / ci) and write 4–8 bullet points covering the user-visible changes. Always end with the install instructions block:

```
## Install

**macOS:** download `Claude Limits_X.Y.Z_universal.dmg`, open, drag to Applications. On first launch, right-click → Open to bypass Gatekeeper for unsigned binaries.

**Windows:** download the `.nsis.exe` installer. SmartScreen may warn — More Info → Run Anyway.

The auto-updater will pick up future releases automatically.
```

Use a HEREDOC for the `--notes` argument to preserve formatting.

### 7. Watch the build

Find the running workflow ID:

```
gh run list --repo FeiXu-1131372/claude-limits --workflow release --limit 1 --json databaseId --jq '.[0].databaseId'
```

Print the watch URL so the user can monitor in a browser:

```
https://github.com/FeiXu-1131372/claude-limits/actions/runs/<RUN_ID>
```

Optionally tail in the terminal:

```
gh run watch <RUN_ID> --repo FeiXu-1131372/claude-limits
```

Cross-platform builds typically take 8–15 minutes. The release page won't show bundle assets until the workflow completes — only the auto-generated `Source code (zip|tar.gz)` archives will be visible during the build.

### 8. Confirm

When the workflow completes successfully, verify:

```
gh release view vX.Y.Z --repo FeiXu-1131372/claude-limits
```

Should list at least these assets:

- `Claude Limits_X.Y.Z_universal.dmg`
- `Claude Limits.app.tar.gz` and `Claude Limits.app.tar.gz.sig`
- A Windows installer (`.nsis.exe` or `.nsis.zip`) and `.sig`
- `latest.json` (added by the `compose-manifest` job — used by the in-app auto-updater)

Tell the user the release URL and the asset count so they can confirm.

## Post-release recovery

If CI fails after the tag was pushed (e.g. a clippy lint only Windows catches):

1. Fix the issue on `main` and push the fix
2. Move the tag forward to the fix commit:
   ```
   git tag -f vX.Y.Z <fix-commit-sha>
   git push origin vX.Y.Z --force
   ```
   This re-triggers the workflow.
3. The pre-created release record stays in place — `tauri-action` will upload bundles to it when the rebuild succeeds.

Force-pushing a tag that has *no published release* yet is safe; once a release is published, prefer cutting a new patch (`vX.Y.(Z+1)`) instead of moving the existing tag.

## Things this skill deliberately does NOT do

- Sign or notarise the bundles (project policy: unsigned, see README)
- Rewrite git history
- Push to anything other than `main` and the new tag
- Bump versions in any branch other than `main`
- Create a release on a tag that already has one (would silently overwrite assets — abort instead)
