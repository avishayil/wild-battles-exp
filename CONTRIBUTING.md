# Contributing & development environment

This is a **static IPSwitch (`.pchtxt`) mod** for *Pokémon: Let's Go, Pikachu!* v1.0.2
(Switch, title `010003F003A34000`, program NSO build-id `C208DB6A4EF4361F28B8402BE0F7CD9A…`).
It makes defeating a wild Pokémon award native EXP, on top of RicoSantos' *Wild Battles*
(PWB1) mod. There is no custom XP formula and no modified emulator — every effect runs
through the game's own code via a handful of hooks into unused `.text` padding (a "code
cave").

> **Legal / scope.** This repo contains **no game code, assets, ROMs, or keys** — only
> original tooling, docs, and address-based patch descriptions. You must supply your own
> legally dumped copy of the game. Read [`DISCLAIMER.md`](DISCLAIMER.md) before contributing.

## What you need

| Thing | Notes |
|---|---|
| **A legal dump of LGP v1.0.2** | The v1.0.2 update must be applied so the running program matches build-id `C208DB6A…`. Not distributed here — dump from your own console. |
| **Eden emulator** (nightly) | macOS / Apple Silicon / MoltenVK is the reference target. Any emulator with IPSwitch `.pchtxt` support and a GDB stub should work. |
| **Python 3** + **capstone** | `pip install capstone`. Used by the build/verify tooling. |
| **`text.bin`** | The carved `.text` of the program NSO, laid out so that **`text.bin[M]` is the byte at NSO memory offset `M`**. Produce it from *your own* decompressed main NSO; it is game code and is **not** committed. The build tool reads it to disassemble/verify hooks and to fetch displaced original instructions. |
| A base **`pwb1.pchtxt`** (RicoSantos' Wild Battles) | Needed to emit the unified/catch builds (the tool merges PWB's records with ours). See [`CREDITS.md`](CREDITS.md). |

## External references

- **RicoSantos — *Wild Battles* (PWB1):** the base mod this builds on. Our hooks assume its
  synthesized-encounter setup routine (see `docs/FUNCTION_MAP.md`).
- **raulzrrs — [`letsgo-recomp`](https://github.com/raulzrrs/letsgo-recomp):** a recompiler
  for the **Eevee 1.0.0** build. We port its field/function knowledge (HP capture, the EXP
  predicate, the model-joint guard) to the Pikachu 1.0.2 executable. Addresses drift by a
  consistent per-region offset; always re-pin at runtime, never trust a ported address blind.

## Tools in this repo

- **`tools/build_patch.py`** — the single source of truth. A **hook-module registry** (each
  module declares its hook site, cave, variants and scratch usage) that regenerates **all**
  `.pchtxt` artifacts byte-for-byte from `text.bin` + the base PWB pchtxt, and self-verifies
  every cave (capstone disassembly of return branches + displaced originals, a dataflow
  **stack-balance** check, and a pairwise **overlap** check). A non-zero exit means the build is
  rejected — never ship past it. **Never hand-edit the generated `.pchtxt` files; change the
  generator.** Flags: `--profile classic` (default; removes the wild-battle timer) / `timed`
  (keeps it); `--manifest <path>` writes a JSON build record (build-id, profile, per-module cave
  offsets, variant membership, scratch map, output record counts + SHA-256).
- **`tools/trace_assert.py`** — replays a `scratchread` trace and asserts the runtime invariants
  (marker set→cleared per encounter; hooks only fire inside a PWB encounter; KO rewrites exactly
  once; non-KO endings never rewrite). A known-good trace lives in `tools/fixtures/`.
- **`tools/scratchread.py`** — connects to the emulator GDB stub (port `6543`) and prints the
  mod's scratch-page instrumentation (hook counters, `pwb_encounter`, captured wild HP, …) as
  it changes. Memory reads only.
- **`tools/package_release.sh <version>`** — zips each variant in the Eden-importable layout
  (`<Mod Name>/exefs/*.pchtxt`) into `dist/<version>/`.

## Build → verify → test loop

```sh
# 1. Regenerate the three artifacts from source
python3 -I tools/build_patch.py \
  --text /path/to/text.bin \
  --pwb  /path/to/pwb1.pchtxt \
  --out-addon         "mods/addon-only (needs base Wild Battles)/Wild Battles EXP Addon/exefs/wbexp_addon.pchtxt" \
  --out-unified       "mods/Wild Battles EXP/exefs/wild_battles_exp.pchtxt" \
  --out-catch-unified "mods/Wild Battles EXP (Catch Variant)/exefs/wild_battles_exp_catch.pchtxt"
# exit 0 = capstone + stack-balance + overlap all passed

# 2. Deploy to the emulator's mod folder for this title, e.g. Eden:
#    ~/.local/share/eden/load/010003F003A34000/Wild Battles EXP/exefs/

# 3. Launch the emulator (a human does this — see AGENTS.md) with the Vulkan renderer.
#    macOS/MoltenVK reference flags:
#    MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1 MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0 eden

# 4. Before trusting the run, verify the patch bytes are actually in guest memory
#    (read them over the GDB stub at module_base + mem_offset).

# 5. Watch the live trace while testing:
python3 -I tools/scratchread.py   # tails to scratchread.log
```

### Regression checklist (minimum before a release)
1. **Two consecutive wild KOs** — each faints → native EXP → clean auto-exit; the per-encounter
   one-shot re-arms (`pwb_encounter` re-set, `done` reset) each time.
2. **A trainer battle** — fully vanilla: no hook fires (`pwb_encounter` stays 0, no rewrite).
3. **A flee** — the result rewrite must **not** fire (no verified KO); the native flee path runs.
4. **A KO-induced level-up that should evolve** — native evolution cutscene plays.

Open release gates (need a late-game save): a real scripted **Snorlax** and a **legendary**
must stay fully vanilla with a catch opportunity intact.

## Load-bearing conventions (do not violate)

- **`pchtxt record address = memory offset + 0x100`** (the NSO 0x100 header). Every record.
- **Code cave:** mem `0xD32BA8..0xD33000` (zero-filled `.text` padding, RX). **Scratch:** mem
  `0x1EE0F00..0x1EE1000` (`.bss` tail). `adrp x16,#0x1EE0000` from the cave page = `0xD0008D70`.
- **GDB stub: memory reads only. Never set software breakpoints** — they deadlock Eden's JIT.
  Always send `$c` (continue) before detaching, or you leave the game frozen.
- **Never modify the base PWB1 records.** Keep our patch a separate, reversible layer.
- **Never remove the `+0x4A4` null guard** in the EXP amount function (`0x9D3BA0`) — it prevents
  a null-context crash.
- **Back up the save** before any behavior-changing run.

See [`docs/FUNCTION_MAP.md`](docs/FUNCTION_MAP.md) for the full function/field/offset map and
[`docs/ENGINEERING_LOG.md`](docs/ENGINEERING_LOG.md) / [`research/`](research/) for how each
hook was derived.
