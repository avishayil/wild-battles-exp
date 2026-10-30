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
