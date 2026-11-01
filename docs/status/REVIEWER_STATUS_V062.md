# Reviewer status — v0.6.2-beta (2026-11-01)

Point-in-time record. Current state lives in [`CHANGELOG.md`](../../CHANGELOG.md) and
[`../LIVE_TESTING.md`](../LIVE_TESTING.md). Target: Pikachu **1.0.2** on Eden nightly
`de7e6e01d4-master` (macOS/MoltenVK, Apple M3 Pro). No game code/assets/keys here.

## Headline
**Strict KO gate promoted to the default build, on live-accept evidence gathered by a new
fully-autonomous test harness.** v0.7 Integrated Catch was researched and **shelved**.

## What shipped
- **`--hp-gate strict` is now the default.** `cave_ST` (A3 result rewrite) additionally requires
  `slot==12 && max_hp>0` before flipping the KO result, rejecting any stray participant that
  overwrote the reflect HP capture. `--hp-gate slot6` restores the older v0.6 gate. All three mods
  + `build-manifest.json` regenerated (`hp_gate: strict`); build passes preimage + cave-padding +
  overlap + PWB-marker checks. The longer strict `cave_ST` shifts later caves, so the Catch
  Variant bytes changed too (behaviourally identical, overlap-verified).

## Evidence that cleared the promotion
The reviewer had parked strict promotion on live acceptance across species. Gathered autonomously
on the current build: every wild KO had **`slot==12 & maxhp>0`** across **4 distinct species** —
Weedle (13), Pidgey (16), Rattata (19), Oddish (43) — all `result=3`, A3 rewrite firing. Combined
with the older-build v0.5 fixture (84/84 captured KOs `slot==12`), the data strongly supports the
tightening. (The scripted-**Snorlax/legendary** isolation gate remains separately open — the dev
save is early-game.)

## New capability: autonomous gdbstub harness (`tools/e2e_autoplay_pump.py`)
This Eden build halts the guest at **every** battle-scene stop (boot, encounter, menu, turn), so
the read-only observer freezes. The harness is a throwaway capture that **continuously pumps `$c`**
(so the guest never freezes) and samples the EXP scratch at each stop, while driving input via
`osascript`: A-taps through boot/controller/save into the overworld, roams the grass (held WASD),
auto-battles to KO, records `slot/species/maxhp`, prints the strict-gate verdict, and force-quits
Eden (`pkill -9` — the Qt quit-confirm dialog is unautomatable: Yes/No invisible to macOS AX,
ignores synthetic keys). Hard-won: input must be **held/tapped across** a `$c` run-window (an
instantaneous tap never lands); species is valid only **after** the KO reflect (`state 8`). It
sends `$c` by design (continue-pump) — not read-only, not shipped. Full runbook:
[`../LIVE_TESTING.md`](../LIVE_TESTING.md).

## v0.7 Integrated Catch — shelved (researched)
[`../CATCH_FEASIBILITY_V070.md`](../CATCH_FEASIBILITY_V070.md) +
[`../../research/CATCH_STEP1_MENU_RE.md`](../../research/CATCH_STEP1_MENU_RE.md): a static `.pchtxt`
cannot add a distinct 5th CATCH button (recomp wires the button's view/callback per allocation at
runtime). Detection of an existing button press **is** static-feasible — `CMD_DECIDE` = `0xab1dd0`,
the chosen id is in `w20` at `0xab1e34`, RUN = id 4 (live-confirmed) — so the only static path
repurposes RUN (losing flee). The owner declined that UX; the **Catch Variant** stays the shipped
"battle-then-catch" answer. v0.7 stays in research.

## Open / deferred (unchanged)
- Scripted **Snorlax/legendary** isolation — the one P0 live gate before a public beta.
- Catch-Variant double-EXP check; optional PP-consumption recheck.
- EXP multipliers (75/50%) — pending the EXP-amount grant path (`research/EXP_SEAM_INVESTIGATION.md`).
