# Changelog

## v0.1.0-alpha — 2026-10-29
First working build. Native EXP for defeating wild Pokémon in Pokémon: Let's Go,
Pikachu! v1.0.2 (build-id C208DB6A…), on top of RicoSantos' Wild Battles (PWB1).

Added (four coordinated mechanisms; see docs/ENGINEERING_LOG.md):
- **A** — clear legendary instant-end flag at the state-4 handler (0x28BF34) → wild KO faints.
- **C** — model-joint guard (0xA9C650) → no post-faint crash.
- **A2** — bypass the XP predicate's +0x4A4 gate (0x9D8A44) → native EXP awarded.
- **A3** — rewrite the battle result 1→3 at state 5 (0x28BD20) → end without the catch screen.

Packaging:
- Unified single-mod build (base PWB + EXP in one pchtxt).
- Add-on build (requires base Wild Battles enabled separately).
- build_patch.py reproduces both byte-for-byte from text.bin + pwb1.pchtxt.

Verified: wild battle → faint → native EXP (e.g. 12 pts) + party distribution → clean
overworld return; consecutive encounters; zero crashes.

Known-untested (see README "Status & known limitations"): evolution on KO level-up;
trainer / real legendary isolation; intentional catching; save/reload persistence; explicit
enemy-HP==0 guard for A3.

## v0.2.0-alpha — 2026-10-30
Release-hardening: **A3 now requires a verified KO.**
- New hook at the BTL_POKEPARAM "reflect" function (mem `0x9E41D0`, pchtxt `0x9E42D0`):
  when the battle ends it captures the **wild** Pokémon's HP (slot-id 12, HP u16 at `+0x7e`)
  into scratch, setting a `have` flag.
- The state-5 result rewrite (`1 → 3`) now additionally requires `have && wild_HP == 0`
  (on top of state==5, result==1, armed, once-per-encounter). A fled battle records a
  live HP and is left untouched — verified in-game (KO → rewrite fires; flee → it doesn't).
- build_patch.py: added depth-tracking stack-balance verification for every cave (an
  early-exit branch that skips a register restore now fails the build).

## v0.3.0-alpha — 2026-10-30
**A4: evolution after wild-KO level-ups.**
- Root cause: the after-battle processor (mem `0x319A60`) picks its next state from the battle
  result — result `3` ("fainted, no capture", which A3 writes) routed to the evolution-SKIPPING
  state 4.
- Fix: one-instruction hook at the next-state write (mem `0x319EC4`, pchtxt `0x319FC4`): when the
  `evolve_pending` flag (set only by A3's verified-KO rewrite) is up and the next state would be 4,
  write 1 instead — the game's own evolution-check state. One-shot; flag auto-cleared at the next
  encounter's state-0 reset.
- Verified: level-6 Caterpie leveled to 7 purely on wild-KO EXP → native evolution cutscene →
  Metapod. Trainer battles unaffected (flag can never be set outside a PWB verified KO).
- Also verified this session: trainer-battle isolation (hooks never fire; fully vanilla), and
  PP/HP persistence between battles under the main build.

## v0.4.0-alpha — 2026-10-30
**Explicit per-encounter PWB isolation.** The faint hook and the XP-eligibility override are
now gated on PWB's *own* encounter marker, so no hook can touch a battle the mod wasn't meant
to change — even one that happens to reach the same states.
- New hook **M** at PWB's marker write `str w9,[x20,#0x298]` (mem `0x3059B8`, inside PWB's
  injected setup routine): the cave replays that exact instruction and sets a `pwb_encounter`
  flag (scratch `+0xF8`). Because PWB writes this marker once per synthesized encounter, the
  flag is true only during a PWB wild battle.
- Hook **A** (faint) now clears the instant-end flag only when `pwb_encounter` is set (plus the
  existing command-menu + flag-0x80 guards). Hook **E** (after-battle) clears `pwb_encounter`
  each battle, so it re-arms per encounter.
- Hook **A2** reworked into a conditional predicate wrapper at the predicate entry
  (mem `0x9D8A30`, replacing the blunt one-word bypass at `0x9D8A44`): it forces XP eligibility
  only for the PWB profile (`setup[+0x4A4]==1 && setup[+0x494]==0`) and otherwise falls through
  to the **untouched** original predicate — a real legendary/static encounter runs its own gate.
- build_patch.py: single intentional overlap (hook M's branch sits inside PWB's 32-byte
  `0x305AB0` record) is whitelisted; capstone + stack-balance + overlap checks all pass. A
  relocation-normalized diff confirms the ST/C/R caves are byte-identical to v0.3 (logic
  unchanged, just moved).
- Verified live (gdbstub scratch trace): two consecutive wild KOs (`pwb_encounter` re-set and
  the one-shot re-armed each time), one trainer battle (fully vanilla — `pwb_encounter` never
  set, no hook activity, no rewrite), a third wild KO, and a flee (hook A armed but the result
  rewrite correctly did **not** fire; native flee path ran).

## v0.4.1-alpha — encounter-isolation hardening
Source-review follow-ups so **every** hook that changes native behavior is scoped to a PWB
encounter, not just hook A/A3.
- **A2 (cave_P) now requires `pwb_encounter`** in addition to the PWB profile
  (`setup[+0x4A4]==1 && setup[+0x494]==0`). Previously profile-gated only — a non-PWB battle
  sharing that profile could have received modified XP eligibility.
- **Hook C (cave_C) now requires `pwb_encounter`.** Outside a PWB encounter it runs the
  untouched original model-joint function, so a resource-less vanilla model is never
  force-returned "no joint".
- **Catch Variant now clears `pwb_encounter`.** It included hook M (which sets the marker) but
  not hook E (which clears it), so the marker leaked into later battles. Hook E is now part of
  the variant; its A4 state-redirect stays inert there (`evolve_pending` is never set).
- Static call-graph report of PWB's injection seam added (`docs/WBEXP_STATIC_CALLGRAPH.md`):
  marker mechanism fully mapped; its enclosing function is virtually dispatched so
  exclusivity can't be proven offline; a native discriminator `[evt+0x735]` identified as the
  thing to measure in the live Snorlax/legendary test.
- Differential vs v0.4.0: unified changes limited to cave_C + cave_P (`+0xF8` gate); catch adds
  cave_E. All other caves byte-identical.
- Verified live (gdbstub scratch trace): **unified** — two wild KOs, a flee and a trainer
  battle, with A2/C still firing in PWB battles, the marker clearing on KO and flee, and the
  trainer battle fully vanilla with no leaked marker; **catch variant** — a KO+capture and a
  flee, marker cleared on both the capture and flee paths with no leak into the next battle.
- Still open (unchanged): a live scripted-Snorlax/legendary isolation test (the beta gate),
  multi-species HP validation, a save/reload persistence pass, and a PP control test.

## v0.5.0-beta — battle-engine stability
Release-hardening pass: tighten opponent identity / end-state ownership and add a replayable
trace-assertion harness, so the ordinary-wild loop is safe enough for a beta.
- **cave_R (HP capture) hardened:** captures only during an active PWB encounter (`pwb_encounter`),
  and now records the wild **slot** (`+0xD4`), **species** (`+0xCC`) and **max HP** (`+0xD0`)
  alongside current HP — so the verified-KO gate can sanity-check the capture and so the wild
  slot/species can be validated across encounters.
- **A3 result rewrite hardened:** now requires `pwb_encounter` and `species != 0` on top of the
  existing `have && wild_HP == 0`, rejecting stale/garbage captures.
- **New `tools/trace_assert.py`:** replays a reader trace and asserts the invariants (marker set
  then cleared per encounter; hooks never fire outside a PWB encounter; KO rewrites exactly once
  with `result==3 / HP==0 / SLOT==12 / species!=0`; non-KO endings never rewrite). A real
  known-good run is kept as `tools/fixtures/trace-v0.5-20261031.log`.
- Differential vs v0.4.1: unified changes limited to cave_R and cave_ST; catch variant logic
  unchanged (relocated).
- **Live-verified (gdbstub trace):** wild KOs across 4+ species (`SLOT=12` on every one of 84
  captured samples), flees (no rewrite), a fully-vanilla trainer battle, a **battle timeout**
  (`result=2` → no EXP), a **black-out** (`result=0` → no false EXP, **and the marker clears on
  the player-loss path** — closing a prior open question about stale scratch), and **save → quit
  → relaunch** (party/XP persisted; mod re-armed cleanly on the fresh session).
- **One pending gate before promotion:** the live scripted-Snorlax / legendary isolation test
  (blocked on a late-game save). PP persistence and the Catch-Variant double-EXP measurement
  remain optional follow-ups. Public beta stays held until the static-encounter test passes.

## v0.6.0-beta — classic battles (no timer) + modular builder
First "classic battle" release and a maintainability pass on the generator.
- **No 5-minute timer in ordinary wild battles.** `cave_A` now also zeroes the special-battle
  300-second limit (`evt+0x562`, which the setup fn `0x28C740` writes alongside the instant-end
  flag) — on the same `pwb_encounter`-gated path, so a genuine legendary/Snorlax keeps its
  countdown. **Live-verified:** a wild battle held >5 minutes did not time out (no `result=2`),
  and the "MATCH TIME" display is gone; a normal KO still works.
- **Modular patch builder.** `tools/build_patch.py` is refactored into a hook-module registry
  (each module declares its hook site, cave, variants and scratch usage); the builder lays out
  caves, runs the capstone + stack-balance + overlap checks, and assembles each variant from the
  registry. Output is **byte-identical** to the previous builder for the default profile.
- **Build-time profiles + manifest.** `--profile classic` (default, timer removed) / `timed`
  (keep the timer); `--manifest build-manifest.json` writes build-id, profile, per-module cave
  addresses, variant membership, scratch map, and per-output record counts + SHA-256.
- Differential vs v0.5.0-beta: the only patch-byte change is `cave_A` (the timer-clear).
- Inherits the deferred gate: the live scripted-Snorlax / legendary isolation test. The timer
  removal is isolation-safe by construction (PWB-gated) but shares that one pending live check.

## v0.6.1 — offline safety validation
Hardening pass with no gameplay change (default build byte-identical to v0.6.0).
- **Builder self-checks.** `build_patch.py` gained per-hook preimage verification (each hook site
  must still hold its expected original instruction), code-cave padding checks, a branch-range
  check, and `--verify-manifest` (assert each output's SHA-256 matches the committed manifest).
- **`--hp-gate {slot6,strict}` (opt-in at this version).** `strict` adds `slot==12 && max_hp>0` to
  the A3 KO gate; default stayed `slot6` (byte-identical) pending live acceptance.
- **Trace-assert `--strict`** (complete-session / rewrite-coincides-with-KO / identity-present) +
  negative fixtures; **game-file-free CI** (encoders, trace-assert, mod lint — no ROM needed).

## v0.6.2-beta — strict KO gate default + autonomous test harness
Promotes the strict KO gate to the default build, backed by live evidence gathered autonomously.
- **Strict KO gate is now the default.** The A3 result rewrite (`cave_ST`) additionally requires the
  captured opponent to be the wild slot (`slot==12`) with a real `max_hp>0`, rejecting any stray
  participant that overwrote the HP capture. `--hp-gate slot6` restores the older v0.6 gate.
- **Live-accept evidence (current Eden build `de7e6e01d4-master`).** Every wild KO showed
  `slot==12 & maxhp>0` across 4 distinct species — Weedle (13), Pidgey (16), Rattata (19),
  Oddish (43), all `result=3` with the A3 rewrite firing. This clears the live check the gate's
  promotion was waiting on. (The scripted-Snorlax/legendary isolation gate remains separately open.)
- **Autonomous test harness (`tools/e2e_autoplay_pump.py`).** A throwaway capture tool that drives
  Eden fully hands-off from boot on this fragile build (which halts the guest at every battle-scene
  stop): it continuously pumps `$c`, A-taps through the boot/controller/save menus, roams the grass
  (held WASD), auto-battles each wild Pokémon to KO, records per-encounter `slot/species/maxhp`,
  prints the strict-gate verdict, and force-quits Eden. Input must be held/tapped *across* a `$c`
  run-window (an instantaneous tap never lands). Not shipped; see `docs/LIVE_TESTING.md`.
- **Regenerated artifacts.** All three mods + `build-manifest.json` rebuilt with the strict default
  (manifest `hp_gate: strict`); build passes preimage + cave-padding + overlap + PWB-marker checks.
- **v0.7 Integrated Catch — researched and shelved.** `docs/CATCH_FEASIBILITY_V070.md` +
  `research/CATCH_STEP1_MENU_RE.md`: catching mid-battle is not static-feasible as a 5th button
  (needs runtime view/callback wiring); the only static path repurposes RUN (`CMD_DECIDE 0xab1dd0`,
  button id in `w20@0xab1e34`, RUN = id 4, live-confirmed). The owner declined that UX, so the
  shipped **Catch Variant** remains the "battle-then-catch" answer.
