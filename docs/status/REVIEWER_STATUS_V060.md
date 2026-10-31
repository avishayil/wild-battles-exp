# Wild Battles EXP — reviewer status at v0.6.0-beta (2026-11-01)

v0.6 ("classic battles") delivers the first gameplay-feel change plus the generator
maintainability pass. Two Workstreams landed; EXP presets (F) are next, and the one deferred
gate (live Snorlax/legendary) still stands before a public beta.

## Workstream E — no timer in ordinary wild battles (done, live-verified)
- The special-battle setup fn `0x28C740` writes the 300-second limit as a u16 to `evt+0x562`
  (at `0x28C898`, the only `.text` writer) alongside setting the instant-end flag `evt+0x574`
  bit `0x80`. `cave_A` already clears that flag for PWB encounters; v0.6 adds `strh wzr,[x19,
  #0x562]` right after, on the same `pwb_encounter`-gated path.
- **Live-verified:** a wild battle held **>5 minutes** produced no timeout (`result=2` never
  appeared), the "MATCH TIME" display is gone, and a normal KO afterwards still worked. This also
  answered the open question of whether `evt+0x562` is the rule or the display — it is the
  **enforced rule** (an unmodified battle actually ends on it), so the clear disables the timeout.
- Isolation: the clear is on the PWB-gated path, so a genuine legendary/Snorlax (not
  `pwb_encounter`) keeps its countdown — covered by the same deferred live gate.

## Workstream H — modular patch builder (done, byte-identical)
- `tools/build_patch.py` refactored into a **hook-module registry**: each module declares its
  hook site, cave builder, variant membership and scratch usage. The builder lays caves out from
  the registry, runs the capstone + stack-balance + overlap checks per module, and assembles each
  variant's records from the registry in the established order.
- **Output is byte-identical** to the pre-refactor builder for the default profile (verified by
  diffing all three variants against a snapshot of the prior generator).
- **Build-time profiles:** `--profile classic` (default, timer removed) / `timed` (keep it). The
  EXP-multiplier profiles (100/75/50) will attach here when Workstream F lands.
- **`--manifest`** writes a JSON build record: build-id, profile, per-module cave offsets, variant
  membership, scratch map, and each output's record count + SHA-256 (`build-manifest.json`).

## Verification
- Build passes capstone + stack-balance + overlap; differential vs v0.5.0-beta shows the only
  patch-byte change is `cave_A` (the timer-clear). Repo artifacts are byte-identical to the
  deployed build that was live-tested.
- `tools/trace_assert.py` still green on the fixtures.

## Open / deferred (unchanged)
- **P0 gate (needs a late-game save):** live scripted Snorlax + a legendary must stay fully
  vanilla (timer, countdown and capture intact). The timer removal shares this gate.
- **Next milestone (Workstream F):** build-time selectable EXP multipliers, hooking the native
  amount at `0x9D3BA0` (keep its `+0x4A4` guard; wild EXP only). recomp is **not** a reference
  here (it only forces eligibility) — this is our own research, using our located amount seam.
- Optional: PP persistence; Catch-Variant double-EXP measurement.

## Standing constraints (unchanged)
Base PWB1 untouched; `pchtxt = mem + 0x100`; capstone + stack-balance + overlap +
differential-vs-last-good; verify bytes in guest memory before trusting a run; gdbstub
memory-reads only; save snapshots before behavior-changing runs; the AI prepares everything, the
owner launches the emulator.
