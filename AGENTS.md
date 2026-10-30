# AGENTS.md — working rules for AI coding agents

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first for the development environment, tools, and
external references. This file is the **operating contract** for autonomous/AI contributors.
[`CLAUDE.md`](CLAUDE.md) points here.

## Non-negotiable rules

1. **`tools/build_patch.py` is the only source of truth.** All `.pchtxt` files are generated.
   Never hand-edit a generated patch — change the generator and regenerate, then let its
   built-in capstone + stack-balance + overlap checks pass (non-zero exit = do not ship).
2. **`pchtxt address = memory offset + 0x100`.** This is the single most common bug; every
   record obeys it.
3. **Do not launch the emulator.** A human launches it (owner policy). Prepare and deploy
   everything, then ask the human to launch and report what they see. Drive verification from
   the GDB stub, not by starting the app yourself.
4. **GDB stub (port `6543`): memory reads only. Never set software breakpoints** (`Z0`) — they
   deadlock Eden's JIT and freeze the game. **Always send `$c` before detaching.** If a script
   dies mid-session it can leave the guest halted; reconnect and `$c` to release it.
5. **Verify before trusting.** Verify the build offline (capstone/stack-balance/overlap, and a
   relocation-normalized diff against the last known-good build), then verify the bytes are
   actually in guest memory before believing any in-game result.
6. **Never touch base PWB1 records.** Keep the patch a separate reversible layer.
7. **Never remove the `+0x4A4` null guard** in the EXP amount function — it prevents a crash.
8. **Back up the save** before any behavior-changing run.
9. **Commits:** author as `avishayil <avishay.il@gmail.com>` **only**. **No AI attribution** —
   do **not** add `Co-authored-by`, `Assisted-by`, "Generated with", or any similar trailer.
   Do not commit or push unless the owner explicitly asks.

## The loop

`edit build_patch.py → regenerate artifacts → offline verify → deploy to the Eden load dir →
verify bytes in guest memory → human launches & plays → read the scratch trace → decide`.

Deploy target: `~/.local/share/eden/load/010003F003A34000/Wild Battles EXP/exefs/`.
The base `Wild Battles` mod stays disabled (`.off`) when the **unified** build is deployed —
the unified build already contains PWB's records.

## How the mod works (so you can reason about changes)

PWB reuses the game's legendary/Snorlax "special battle" system, which ends instantly with no
faint and no EXP. The mod flips that onto the normal faint→reward path and isolates the change
to PWB's own encounters. Hooks (all in the code cave, see `docs/FUNCTION_MAP.md`):

- **M** `0x3059B8` — replays PWB's per-encounter marker write and sets `pwb_encounter` (scratch
  `+0xF8`): the PWB-only, per-encounter identity everything else keys off.
- **A** `0x28BF34` — clears the instant-end flag (so a KO faints) **only when `pwb_encounter`**.
- **A2** `0x9D8A30` — predicate wrapper: force XP eligibility only when `pwb_encounter` **and**
  the PWB profile hold; else run the untouched original predicate.
- **C** `0xA9C650` — model-joint guard: prevents the post-faint crash for resource-less models;
  **gated on `pwb_encounter`** (outside a PWB battle it runs the untouched original).
- **A3** `0x28BD20` — at state 5 rewrite result `1→3` on a **verified KO** (captured HP == 0),
  one-shot, so the catch screen is skipped and the battle exits.
- **A4** `0x319EC4` — redirect the after-battle transition so a KO level-up evolves; clears
  `pwb_encounter` each battle.

The **Catch Variant** omits A3/A4 (keeps the post-KO catch screen).

## Scratch instrumentation (read with `tools/scratchread.py`)

`+0x34` clear-count · `+0x58` result · `+0xC8` captured wild HP · `+0xD8` guard-hit ·
`+0xE0` rewrite-count · `+0xE4` A2 PWB-match count · `+0xF8` **pwb_encounter** ·
`+0xFC/+0xFD/+0xFE/+0xFF` armed/done/have/evolve_pending. All inert for gameplay.

## Quick reference

- Title `010003F003A34000`, v1.0.2, build-id `C208DB6A4EF4361F28B8402BE0F7CD9A…`.
- Code cave mem `0xD32BA8..0xD33000`; scratch mem `0x1EE0F00..0x1EE1000`.
- Reference recomp (Eevee 1.0.0): `raulzrrs/letsgo-recomp` — addresses drift; re-pin at runtime.
