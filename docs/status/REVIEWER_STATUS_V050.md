# Wild Battles EXP — reviewer status at v0.5.0-beta (2026-10-31)

v0.5 ("battle-engine stability") is the release-hardening pass. Per the approved plan, all
**save-independent** work is done and live-verified; the single remaining gate (a live scripted
Snorlax/legendary isolation test) is deferred because the development save is early-game, and is
explicitly labeled as the one pending item before promotion to a public beta.

## What changed (one code change + tooling)
- **cave_R (`0x9E41D0`) hardened:** captures only during an active PWB encounter (`pwb_encounter`,
  +0xF8), and records the wild **slot** (+0xD4), **species** (+0xCC) and **max HP** (+0xD0)
  alongside current HP (+0xC8).
- **A3 gate (cave_ST) hardened:** the result rewrite now also requires `pwb_encounter` and
  `species != 0`, on top of `have && wild_HP == 0`.
- **`tools/trace_assert.py` (new):** replays a reader trace and asserts the invariants (G1 rewrite
  monotonic; G2 hooks only fire while `pwb_encounter`; E1 marker set→cleared per episode; E2 KO
  rewrites once with `result==3 / HP==0 / SLOT==12 / species!=0`; E3 non-KO never rewrites). It
  passes on the real run `tools/fixtures/trace-v0.5-20261031.log` (2 sessions, 15 episodes,
  9 KO / 6 non-KO) and fails on injected faults.
- Differential vs frozen v0.4.1: unified changes limited to cave_R + cave_ST; catch variant logic
  unchanged. Build passes capstone + stack-balance + overlap.

## Live regression (gdbstub scratch trace, this session)
| Case | Result |
|---|---|
| Wild KOs (9 episodes, 4+ species: 10/14/16/19) | ✅ `SLOT=12` on **84/84** captured samples; `WILD_HP→0`; rewrite once each |
| Flees (several) | ✅ live HP captured, **no rewrite** |
| Trainer battle | ✅ fully vanilla (no marker, no hook activity) |
| Battle **timeout** | ✅ `result=2` (distinct code) → no EXP, no rewrite |
| **Black-out** (party defeated) | ✅ `result=0`, wild HP non-zero → no false EXP; **marker cleared on the loss path** |
| Save → quit → relaunch | ✅ party/XP persisted; fresh session re-armed and KO rewrote cleanly |

Notable: the black-out confirmed the player-loss path traverses the marker cleanup (no stale
scratch) — a prior open proof-obligation. The timeout confirmed `evt+0x562=300` is an **enforced**
rule (the battle actually ended on time), which de-risks the v0.6 timer work (and means its
removal will require a live >5-minute re-test).

## Open / deferred
- **P0 gate (deferred, needs a late-game save):** live scripted Snorlax + a legendary must stay
  fully vanilla with the capture opportunity and timer intact; measure `pwb_encounter` and the
  native field `[evt+0x735]` there. Offline, the isolation rests on PWB's own marker (the analog
  of recomp's `WILD_HASH` sentinel); see [`../WBEXP_STATIC_CALLGRAPH.md`](../WBEXP_STATIC_CALLGRAPH.md).
- **Optional follow-ups:** PP persistence across battles; Catch-Variant double-EXP measurement.

## Standing constraints (unchanged)
Base PWB1 untouched; every record `pchtxt = mem + 0x100`; capstone + stack-balance + overlap +
differential-vs-last-good verification; verify bytes in guest memory before trusting a run;
gdbstub memory-reads only (no breakpoints; `$c` before detach); save snapshots before
behavior-changing runs; the AI prepares everything, the owner launches the emulator.
