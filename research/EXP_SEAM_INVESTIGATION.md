# EXP-amount seam investigation (Workstream F) — research checkpoint

**Status: paused** after an approved, bounded diagnostic (reviewer verdict 2026-11-01). The
native 100% EXP already works; build-time EXP multipliers (75%/50%) are **deferred** until the
*actual* EXP award/write path is identified, and behind the scripted Snorlax/legendary gate.

This file preserves the findings so F resumes cheaply without repeating the dead ends. Tooling:
`tools/probe_exp.py` / `tools/probe_exp_read.py` (eligible-path probe), `tools/probe_f1.py` /
`tools/probe_f1_read.py` (message-number ring probe), fixture
`tools/fixtures/f1-trace-20261101.log`. None of these ship in release zips (packaging only
includes `mods/`).

## Goal
Find a single instruction/field that holds the **awarded** per-Pokémon EXP for a PWB wild KO,
so a build-time profile can scale it — without touching the display only, trainer/static EXP,
party distribution, rounding, level-up or evolution. All amounts below are real in-game refs:
Pidgey 14, Oddish L4 25, Weedle L4 14, Weedle L3 11, Rattata L4 19; trainer (Lass, Nidoran L4) 22.

## Ruled out (with evidence)
| Candidate | Finding | Verdict |
|---|---|---|
| `0x9D3BA0` (mapped "amount fn") | Live probe of all 3 callers: only `0xA65540` fires, returns **0** (its `+0x4A4==0` guard; PWB setup has `+0x4A4==1`), result discarded by `cbz`. Trainer run: also 0. | **Not** the award source. Keep its `+0x4A4` guard regardless. |
| `0xa089e0` (eligible-path candidate) | Fires in general gameplay; on a PWB KO the counter did not increment. | Not the EXP path. |
| `0xa11980` → `0xa11a90` | Fetches stat indices `0xa–0xf` via `0x9d0000(species,form,idx)`, doubles for species `0xD7`, adds Power-item bonuses (items `0x121–0x126`). | **EV-yield** distribution, not EXP. |
| `0xA6EF80` (message-number setter, F1) | Ring probe over 2 KOs (11, 19): fired twice per KO, both from `0xA59BA8`, number `0` every time — never 11/19. | Does **not** carry the EXP amount for PWB. |
| `0xA59BA8` (the F1 caller) | Builds message id `0x4E`/`0x50` (via `0xa6ef50`), not the EXP message `0x44`. | Different, non-EXP message. |

Caveat (reviewer): this rules out the *observed* `0xA6EF80` call path; it doesn't prove that
function can never participate in other EXP messages under different conditions.

## Confirmed
- PWB EXP is awarded on the **eligible-predicate branch**: predicate `0x9D8A30` (A2 forces
  `w0=1`) is called from `0x9F28E8`, inside reward processor **`0x9F28B8`**. Live probe: only the
  `0x9F28E8` branch fires per wild KO (`0x9F619C` and `0xa089e0` do not).
- `0x9F28B8` runs a per-participant reward loop (count `w27`) over list accessors
  (`0xa65f50/fd0/f80`), `0x9daac0` (status), `0x9e0de0` (Pokémon ptr), `0xa11980` (EVs). The EXP
  amount is computed/applied elsewhere within this processor's nested calls — not yet pinned.

## Strategy if/when F resumes — target the AWARD path, not the display
Two display-side probe rounds did not reach the amount. Switch approach:
1. **Find the "gain experience" routine by signature:** a `ldr`/`add`/`str` to a party-Pokémon
   EXP field followed by the level-up loop. Its call argument is the awarded amount → hook there.
2. **Party-EXP-field memory-watch:** read the active Pokémon's stored EXP over the gdbstub
   before/after a KO to locate the field (+delta == awarded amount), then find its writer.
Both pin the *awarded* value directly, satisfying the display-vs-award acceptance criterion.
Watch for scaling at the wrong stage (pre-party-modifier total vs final per-Pokémon grant), which
would corrupt party distribution or rounding.

## Build plan when the seam is found (reviewer guidance)
`--exp-percent 100|75|50` **orthogonal** to `--profile classic|timed` (no Cartesian explosion):
100% byte-identical to v0.6; scaling strictly scoped to active PWB encounters; shown == applied
== persisted; validate rounding on odd/low amounts; level-up + evolution intact; trainers native;
compare Catch-Variant XP vs main before supporting scaled Catch builds; record the multiplier in
the build manifest.
