---
name: release-claude-limits-gh
description: Prepare, validate, and publish GitHub releases of FeiXu-1131372/claude-switchboard, including version and changelog updates, CI, draft builds, and updater verification. Use for releasing that repository or recovering an incomplete release.
---

# Release Claude Switchboard to GitHub

Release repository: `FeiXu-1131372/claude-switchboard`. The skill keeps its historical name so existing links and invocations work.

Input: an optional `bump` of `patch`, `minor`, `major`, or an explicit version such as `1.4.1`. Read the current version from `[package].version` in `src-tauri/Cargo.toml`. Use the user's explicit version or bump; otherwise propose the appropriate version for the changes and confirm it once before tagging. Do not ask again for choices or actions already authorized.

Validate the proposed stable semantic version against the current version and latest shipped release. A new release must advance the version; an existing version belongs to the recovery/resume path below.

## Establish the release scope

1. Confirm the checkout's origin is the release repository and inspect its `AGENTS.md`, working tree, and branch. Use `gh auth status` to check access without printing credentials.
2. Release from `main`, synchronized with `origin/main`. Fetch before comparing; fast-forward if needed. Preserve local edits: review and commit changes the user authorized for this release, and keep unrelated work outside the release commit. Use an isolated checkout or a scoped stash when appropriate, record its identity, and restore it after the attempt. Ask only when the scope or permission to handle existing work is unresolved.
3. Inspect `.github/workflows/test.yml`, `.github/workflows/release.yml`, and the Tauri configs. They are authoritative if the pipeline has changed. Check signing secret **names** and `contents: write` access when diagnosing a build; never print secret values or rotate working keys as part of a routine release.
4. Check local and remote tags and GitHub releases for the proposed version. An existing tag or release is a recovery/resume case, not permission to overwrite it. Distinguish a confirmed missing release from authentication or network errors. See **Recovery** below.

The release workflow currently builds a universal macOS app/DMG and a Windows x64 NSIS installer. Both matrix jobs upload to a **draft** (`releaseDraft: true`). The `publish` job waits for both, checks the updater manifest's version and required platform entries, and then publishes. `workflow_dispatch` builds and releases its selected existing tag; it is **not a dry run**.

## Prepare and verify the commit

- Update `src-tauri/Cargo.toml` and `package.json` to the same version. Run `cargo check --manifest-path src-tauri/Cargo.toml` to regenerate the application's `Cargo.lock` entry; do not hand-edit the lockfile. Preserve UTF-8 and unrelated content. `tauri.conf.json` currently inherits the Cargo version and needs no version edit.
- Promote `CHANGELOG.md`'s `[Unreleased]` content into the dated version section, open a new `[Unreleased]` section, and update compare links. Review the log since the previous shipped release so the notes cover the actual scope. The repository's release script is not a substitute for these CI and publication checks.
- Run the following local checks from the repository root, stopping to fix a failure before proceeding. Commands use `--manifest-path` so they work in PowerShell and POSIX shells:

```text
pnpm install --frozen-lockfile
pnpm lint
pnpm test
cargo test --manifest-path src-tauri/Cargo.toml --lib
cargo clippy --manifest-path src-tauri/Cargo.toml --workspace --all-targets --all-features -- -D warnings
```

If a running Windows app locks the default binary, keep it running and use a separate Cargo target directory for checks that would overwrite it. A local pass does not cover other operating systems or a newer CI Rust toolchain.

For sidecar changes, confirm that macOS CI's **Validate macOS universal sidecar** step passes. `scripts/build-bridge.mjs` must stage separate `aarch64-apple-darwin` and `x86_64-apple-darwin` files as well as `universal-apple-darwin`: Tauri validates each concrete architecture before assembling the universal app. Correct `lipo` verification places the input file first, for example:

```text
lipo src-tauri/binaries/switchboard-statusline-universal-apple-darwin -verify_arch arm64 x86_64
```

Stage only the reviewed version files, lockfile, and changelog. Commit as `release: vX.Y.Z` and push `main`. Commit any necessary fixes separately. Do not add an AI coauthor trailer.

**Before tagging, wait for the `test` workflow on the exact final commit to succeed on Windows, macOS, and Linux.** It runs the full Rust workspace, including integration tests, and strict Clippy. Find runs by workflow and commit rather than blindly taking the latest run:

```text
gh run list --repo FeiXu-1131372/claude-switchboard --workflow test.yml --commit COMMIT_SHA --json databaseId,headSha,status,conclusion,url
gh run watch RUN_ID --repo FeiXu-1131372/claude-switchboard --exit-status
```

Confirm the watched run's SHA, conclusion, and matrix jobs. If fixes change `main`, require CI on the new final SHA. Recheck versions, intended files, remote `main`, tag availability, and release state before continuing.

## Build a draft and publish

1. Write UTF-8 release notes to a temporary Markdown file outside the release commit. Cover the user-visible changes in roughly 4–8 bullets, disclose meaningful platform verification limits, and finish with the installation block below. Use `--notes-file`; shell heredoc syntax is not portable to PowerShell.
2. Create and push the new tag at the CI-tested commit, then promptly pre-create its draft with the prepared notes:

```text
git tag vX.Y.Z COMMIT_SHA
git push origin vX.Y.Z
gh release create vX.Y.Z --repo FeiXu-1131372/claude-switchboard --verify-tag --title vX.Y.Z --draft --notes-file NOTES_FILE.md
```

If the workflow creates the draft first, inspect its tag, tested SHA, and workflow run, then populate that matching draft's notes with `gh release edit ... --notes-file ...`. Do not create a duplicate release or overwrite unrelated existing content. If setup fails, inspect the local tag, remote tag, draft, and runs before retrying.

3. Identify the release workflow run by tag **and** SHA. A retry may share a commit with other tags, so confirm both fields:

```text
gh run list --repo FeiXu-1131372/claude-switchboard --workflow release.yml --commit COMMIT_SHA --json databaseId,headBranch,headSha,status,conclusion,url
gh run watch RUN_ID --repo FeiXu-1131372/claude-switchboard --exit-status
```

Share the run URL and continue monitoring until the entire workflow, including `publish`, finishes. Builds commonly take 8–15 minutes. Assets may appear on the draft as individual platforms finish; that does not mean the release is complete. Do not publish manually while a platform is missing.

Use the actual product/asset names from the configs and workflow. The current installation block is:

```markdown
## Install

**macOS:** download `Claude.Switchboard_X.Y.Z_universal.dmg`, open it, and drag the app to Applications. Follow the README's first-launch instructions for the unsigned build.

**Windows:** download `Claude.Switchboard_X.Y.Z_x64-setup.exe`. If SmartScreen warns, choose More info → Run anyway.

The auto-updater will pick up future releases automatically.
```

The workflow uses existing updater signing secrets. Updater signatures are separate from OS code signing/notarization; do not claim the app is notarized or change the unsigned-app policy during a routine release.

## Verify the shipped release

Confirm the workflow is successful, the release is public, and its tag resolves to the tested commit. Expect these **six uploaded assets** (source archives do not count):

- `Claude.Switchboard_X.Y.Z_universal.dmg`
- `Claude.Switchboard_X.Y.Z_x64-setup.exe` and `.exe.sig`
- `Claude.Switchboard_universal.app.tar.gz` and `.app.tar.gz.sig`
- `latest.json`

`tauri-action` produces/merges `latest.json`; there is no separate `compose-manifest` job. The manifest must name the release version and contain at least `darwin-aarch64`, `darwin-x86_64`, and `windows-x86_64`, with URLs to this tag's assets and nonempty signatures.

Use [scripts/verify_release.py](scripts/verify_release.py) from the application checkout. It needs Python 3.9+, `cryptography`, and an authenticated `gh` on PATH. Use an isolated Python environment if dependencies are missing. Choose a scratch download directory; the helper overwrites only the release assets it downloads there.

```text
python PATH_TO_SKILL/scripts/verify_release.py --tag vX.Y.Z --config src-tauri/tauri.conf.json --download-dir SCRATCH_DIRECTORY
```

The helper checks expected assets, sizes and available GitHub digests, updater platform URLs, signatures against the app's configured public key, and Intel/Apple Silicon executables for the macOS app and sidecar. It also checks the configured public updater endpoint when it points to this release. `--allow-draft` supports inspecting an incomplete recovery candidate without publishing it; required assets and signatures are still enforced.

Report the release URL, asset count, checks completed, and any remaining native runtime verification gaps. Restore preserved local edits even if the release attempt fails; retain the stash if restoration needs reconciliation. A successful build does not prove native GUI or closed-app scheduling behavior on a platform not smoke-tested.

## Recovery

- **Same commit, transient infrastructure failure:** retain the draft and tag, inspect failed job logs, and rerun the failed jobs. Reuse an existing matching draft/run when resuming. A failed build or publish job is not a completed release.
- **Code fix required:** fix and push `main`, then require CI on the new SHA. For a public release or any shipped binaries, use a new patch version by default. Keep the old tag and artifacts intact.
- **Retagging an unshipped candidate:** only with explicit user authorization for that particular tag. Cancel active builds, verify no binaries were shipped, keep the release in draft, record the expected old SHA, and check the new commit's CI. An empty draft alone does not prove that binaries were never public. Push the authorized replacement with an exact lease, never an unrestricted force push:

```text
git tag -f vX.Y.Z NEW_TESTED_SHA
git push --force-with-lease=refs/tags/vX.Y.Z:EXPECTED_OLD_SHA origin refs/tags/vX.Y.Z:refs/tags/vX.Y.Z
```

- **Partial assets or manifest failure:** inspect what was uploaded and preserve any already public files. Verify platform URLs and signatures before repairing metadata or rerunning publication; do not regenerate signing keys or mix artifacts from different commits.

Do not delete an existing release, replace shipped binaries, change the version without resolving the user's explicit choice, or move an existing tag merely to bypass a failure. Continue independent diagnosis and preparation while any necessary version or recovery decision is pending.
