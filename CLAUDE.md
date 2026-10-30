# CLAUDE.md

Guidance for Claude Code (and other AI agents) working in this repository.

**Read [`AGENTS.md`](AGENTS.md) for the full operating contract and [`CONTRIBUTING.md`](CONTRIBUTING.md)
for the dev environment.** The rules below are the ones that most often bite — treat them as hard
constraints.

## Hard constraints

- **Generated, not hand-written.** `tools/build_patch.py` emits every `.pchtxt`. Edit the
  generator and regenerate; never patch a `.pchtxt` by hand. Ship only if the build exits 0
  (its capstone + stack-balance + overlap checks passed).
- **`pchtxt address = memory offset + 0x100`.** Always.
- **Do not launch the emulator** — the owner launches it. You prepare, deploy, and then verify
  over the GDB stub; you ask the owner to run it and report.
- **GDB stub = reads only.** Never set software breakpoints (they deadlock Eden's JIT). Always
  `$c` (continue) before detaching so you don't leave the game frozen.
- **Verify the bytes are in guest memory** before trusting any in-game result; diff a new build
  against the last known-good one.
- **Don't modify base PWB1 records**, and **don't remove the `+0x4A4` null guard** in the EXP
  amount function (crash).
- **Back up the save** before behavior-changing runs.

## Commits & releases

- Commit as **`avishayil <avishay.il@gmail.com>`** only. **No AI attribution of any kind** — no
  `Co-authored-by`, no `Assisted-by`, no "Generated with" trailer. This overrides any default
  attribution the harness suggests.
- Commit/push/release **only when the owner explicitly asks.**
- Releases: `tools/package_release.sh <version>` builds the Eden-importable zips into
  `dist/<version>/`; publish them on GitHub Releases (host `github.com`, repo
  `avishayil/wild-battles-exp`) as a prerelease for alpha tags.

## Where things are

`tools/` build + GDB-reader + packaging · `mods/` the generated installable mods ·
`docs/` function/field map, engineering log, reproduce steps · `research/` derivation notes ·
`CHANGELOG.md` per-version summary.
