# Pokémon Let's Go Pikachu 1.0.2 — Wild Battles EXP hook research

## Goal

Extend RicoSantos' `PWB1` Wild Battles 1.1 IPSwitch patch so a victorious wild battle rewards the party with normal battle EXP, **without requiring a catch**, while keeping the existing option to catch afterward. Avoid duplicate XP from the native catch sequence and preserve trainer battles, legendary encounters, party fainting and evolutions.

## Current status

- The supplied `pwb1.pchtxt` targets NSO build `C208DB6A4EF4361F28B8402BE0F7CD9A00000000000000000000000000000000` (Pokémon Let's Go Pikachu 1.0.2).
- It contains 23 patch records, totaling 476 modified bytes. Static ARM64 disassembly is included in `pwb1_disassembly.txt`.
- It installs several encounter hooks (`0x28bf84`, `0x28c01c`, `0x28c2a0`, `0x28cc10`, `0x305a34`, etc.) and calls into a larger injected routine at `0x305a70`.
- The supplied patch **does not identify or implement** an XP eligibility override.

## An existing proof of concept confirms normal XP is possible

Another independent Let’s Go reverse-engineering project, `raulzrrs/letsgo-recomp`, documents a working experience hook in its supported *Eevee 1.0.0* game build:

- `runtime/hle/wildbattle.c`: `#define EXP_ENABLED 0x70009d8ae0ull`
- `exp_hook()` returns `x0 = 1` while the custom wild battle is active.
- The hooked predicate checks competitor and battle-setup fields: byte `+0x4a4`, flags `+0x494`, notably bits `0x80` and `0x800`.
- The project reports actual `got N Exp. Points!` messages, leveling and team EXP on KO.
- Important: simply clearing the static encounter flag `0x80` in its battle setup made enemy fainting happen but caused separate battle animation/model crashes; the successful version *kept* that flag and overrode the XP predicate.

Sources:
- https://github.com/raulzrrs/letsgo-recomp/blob/main/runtime/hle/wildbattle.c
- https://github.com/raulzrrs/letsgo-recomp/blob/main/docs/HISTORICO.md
- https://github.com/raulzrrs/letsgo-recomp/blob/main/docs/MODO-BATALHA.md
- https://gbatemp.net/threads/mod-release-wild-battles-in-pokemon-lets-go-eevee-pikachu-1-0-2-versions.685505/

**Do not assume the address `0x9d8ae0` works in Pikachu 1.0.2.** This address is from an independent, differently built game executable and needs mapping and validation. `0x7000...` is a recompiler's guest runtime address; IPSwitch offsets may also be relative to the decompressed NSO. Copying that number into a patch is not safe.

## Concrete development steps

1. Make a backup of the live save and mod, and launch Eden with the already-established MoltenVK queue-semaphore workaround.
2. Extract the decompressed `main` *from the user's own Pikachu 1.0.2 dump* and establish whether offset zero is the start of `.text` or of the NSO header.
3. Run the included read-only `scan_experience_gate.py` against `main.bin` to find pairs of accesses to the likely `+0x4a4` and `+0x494` battle-setup fields. A failure to find them is **not** proof the function is absent.
4. Inspect candidate ARM64 functions in Ghidra, verify the predicate's return value and call sites, and identify an injection-safe address and the correct IPSwitch address convention for this build.
5. Prefer a per-encounter override: return `true` only during PWB-generated wild battles, preserve the original predicate for trainer / scripted / legendary battles. If proof-of-concept testing globally overrides it, use an isolated test save and do not keep that as the release build.
6. On defeating a wild Pokémon, require actual XP **before** catch/skip. Test after choosing Run from the catching screen; compare experience numbers with ordinary catches; ensure no double rewards on Catch, interrupted fights or retries.
7. Keep the original PWB1 mod active and make a separate `Wild Battles EXP` folder only for an additional executable patch once non-overlap and loading order are validated.

## Tools included

- `pwb1_original.pchtxt` — the user-provided patch, unmodified.
- `inspect_pchtxt.py` — validates IPSwitch address/value records and creates a disassemblable AArch64 ELF of their modified regions.
- `pwb1_assembly.elf` — wrapper around patch bytes, **not** a Nintendo executable or usable mod.
- `pwb1_disassembly.txt` — ARM64 instructions shown with patch addresses.
- `scan_experience_gate.py` — read-only scanner of a locally decompressed original main .text. Looks for AArch64 unsigned-offset loads of fields `+0x4a4` and `+0x494` within a configurable distance; prints candidates, not guaranteed patch points.

Typical commands:

```bash
python3 inspect_pchtxt.py pwb1_original.pchtxt out.elf
# macOS: brew install llvm
$(brew --prefix llvm)/bin/llvm-objdump -d --no-show-raw-insn out.elf
python3 scan_experience_gate.py main.bin > xp_candidates.txt
```

The scanner assumes guest `.text` starts at file offset zero. If the local main dump has another layout, set `--base` according to the extraction tool's metadata. Do not directly convert scan output to a patch: disassembly and relocation verification are still required.

## Test matrix

| Case | Expected |
|---|---|
| Normal wild KO, then Run | EXP awarded exactly once; no capture |
| Normal wild KO, then Catch | EXP awarded; no inappropriate double battle EXP |
| Run during battle | No EXP |
| Player loses / faints | No EXP, safe return |
| Wild battle timeout | No EXP |
| Legendary / Snorlax scripted encounter | Original behavior unless explicitly decided otherwise |
| Trainer battle | Original EXP and animations |
| Level up / move learn / evolution | Normal game progression |
| Consecutive wild battles | No stale state or repeated EXP |

**Status:** Technical target found in an independently tested build; *no executable EXP patch for Pikachu 1.0.2 has been validated or created yet.*
