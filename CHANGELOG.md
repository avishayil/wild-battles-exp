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
