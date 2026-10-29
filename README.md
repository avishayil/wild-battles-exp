# Wild Battles EXP — native experience for wild KOs in Pokémon: Let's Go, Pikachu!

**Alpha (`v0.1.0-alpha`).** A static IPSwitch (`.pchtxt`) mod for **Pokémon: Let's Go,
Pikachu! v1.0.2** (Switch, title `010003F003A34000`) that makes **defeating** a wild
Pokémon award normal battle **experience** — the way the main-series games do — on top of
RicoSantos' *Wild Battles* (PWB1) mod.

```
Walk into a wild Pokémon  →  battle it  →  KO it  →  it faints
  →  your party gains native EXP (real amounts, normal level-ups)
  →  you return straight to the overworld (no catch screen)
```

All of this runs through the game's **own** battle, fainting, EXP and party-distribution
code. There is no custom XP formula and no modified emulator.

Verified working on **Eden** (macOS, Apple Silicon / MoltenVK). Program NSO build-id
`C208DB6A4EF4361F28B8402BE0F7CD9A…`.

> ⚠️ **Alpha / limited testing.** Confirmed: wild battle → faint → EXP → clean exit, across
> consecutive encounters, no crashes. **Not yet validated:** evolution on a KO-induced
> level-up, trainer battles, real legendary/Snorlax encounters, intentional catching, and
> save/reload persistence. See **Status & known limitations** below. Keep a save backup.

---

## Install

You need the game dumped and running under an emulator that supports IPSwitch `.pchtxt`
mods (tested on Eden; Ryujinx/yuzu-family loaders use the same format). This mod targets
**v1.0.2** specifically — the update must be applied so the running program matches
build-id `C208DB6A…`.

### Option 1 — Unified single mod (recommended)
Load **one** mod that already contains everything.

1. Copy `mods/Wild Battles EXP/` into your emulator's mod folder for this title, e.g.
   `…/load/010003F003A34000/Wild Battles EXP/`.
2. In the emulator's game **Properties → Add-Ons**, enable **"Wild Battles EXP"**.
3. **Do NOT also enable a separate "Wild Battles" mod** — the unified build already
   includes it. Running both would double-apply the base records.

### Option 2 — Add-on (if you already run RicoSantos' Wild Battles)
1. Keep your existing **Wild Battles** mod enabled.
2. Add `mods/addon-only (needs base Wild Battles)/Wild Battles EXP Addon/` alongside it and
   enable it too.
3. Both mods must target the same build-id (`C208DB6A…`).

### Launch note (Eden/macOS)
This was developed/tested launching Eden with MoltenVK workarounds:
```
MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1 MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0 \
  "$HOME/Applications/eden.app/Contents/MacOS/eden"
```
Use the **Vulkan** renderer (a Null renderer shows a black "Launching…" screen).

---

## What it does (how the four pieces fit)

Wild battles created by PWB1 reuse the game's *legendary / Snorlax* "special battle"
system, which is wired to **end instantly with no faint and no EXP**. This mod flips that
battle onto the normal faint→reward path and fills the gaps that the special-battle setup
leaves behind:

| Piece | Hook (NSO memory offset) | Effect |
|---|---|---|
| **A** faint | `0x28BF34` (state-4 handler) | Clears the legendary "instant-end" flag `[evt+0x574] & 0x80` once the command menu exists, so a KO **faints** |
| **C** model guard | `0xA9C650` (model-joint fn) | Returns "no joint" when the wild model lacks its resources — prevents the post-faint crash |
| **A2** XP | `0x9D8A44` (in predicate `0x9D8A30`) | Bypasses the `+0x4A4` eligibility gate so the native EXP reward runs; the predicate's own flags check still excludes real legendaries |
| **A3** exit | `0x28BD20` (battle-event entry) | At state 5, rewrites the result `1 → 3` ("fainted, no capture") so the battle ends **without** the catch screen (one-shot per encounter) |

Details, derivation, and the full debugging history are in [`docs/`](docs/) and
[`research/`](research/).

---

## Status & known limitations
- ✅ Wild battle → faint → native EXP (measured, e.g. "Pikachu got 12 Exp. Points!") →
  party distribution → clean return to overworld.
- ✅ Consecutive encounters (per-encounter one-shot re-arms correctly). No crashes.
- ❓ **Evolution** after a KO-induced level-up — untested (may need the after-battle
  `state 4→1` redirect; see `docs/ENGINEERING_LOG.md` "A4").
- ❓ **Encounter isolation** — the XP eligibility change is gated by the game's own
  static-encounter flags (which should exclude real legendaries) and the result rewrite is
  gated to battles where this mod forced the faint, **but neither has been tested against a
  real legendary/trainer battle yet.** Treat as unsafe for scripted encounters until
  validated.
- ❓ **Intentional catching:** with the unified build, a *defeated* wild Pokémon is gone
  (no catch screen). The base PWB mod has no in-battle "throw ball" action, so there is
  currently no way to keep a Pokémon you battle. See the add-on / future "Catch variant"
  note in the engineering log.
- ❓ Save/reload persistence of gained levels/XP — untested.

## Repo layout
```
mods/                 the installable mod(s) — unified + add-on
tools/                build_patch.py (regenerates the patch) + analysis/verify scripts
docs/                 ENGINEERING_LOG, REPRODUCE, FUNCTION_MAP
research/             raw experiment log, investigation notes, original findings
CHANGELOG.md, CREDITS.md
```

## Credits
Base **Wild Battles (PWB1)** mod by **RicoSantos**. Native-EXP mechanism and address map
derived with reference to **raulzrrs/letsgo-recomp** (a recompiler for the Eevee 1.0.0
build) — this project ports the same ideas to the Pikachu 1.0.2 executable as a static
`.pchtxt`. See `CREDITS.md`.
