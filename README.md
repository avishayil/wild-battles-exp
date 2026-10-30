# Wild Battles EXP — native experience for wild KOs in Pokémon: Let's Go, Pikachu!

> ⚖️ **Unofficial fan project — not affiliated with or endorsed by Nintendo, Game Freak,
> Creatures Inc., or The Pokémon Company.** All game trademarks/copyrights belong to their
> respective owners. No game code or assets are distributed; a legally owned copy is
> required. Read the full [legal notice & disclaimer](DISCLAIMER.md) before using this mod.

**Alpha (`v0.4.1-alpha`).** A static IPSwitch (`.pchtxt`) mod for **Pokémon: Let's Go,
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

> ⚠️ **Alpha / limited testing.** Confirmed: wild KO → faint → EXP → clean exit across
> consecutive encounters, KO-induced evolution, fully-vanilla trainer battles, and flee — all
> with per-encounter PWB isolation (v0.4). **The open gate:** real legendary / scripted Snorlax
> static encounters are not yet tested against (the development save is early-game); a dedicated
> save/reload persistence pass is also pending. See **Status & known limitations** below. Keep a
> save backup.

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
| **M** PWB marker | `0x3059B8` (in PWB's setup routine) | Replays PWB's own marker write and sets a `pwb_encounter` flag — true only during a PWB-synthesized wild battle; the per-encounter identity every other hook keys off |
| **A** faint | `0x28BF34` (state-4 handler) | Clears the legendary "instant-end" flag `[evt+0x574] & 0x80` once the command menu exists **and `pwb_encounter` is set**, so a KO **faints** |
| **C** model guard | `0xA9C650` (model-joint fn) | Returns "no joint" when the wild model lacks its resources — prevents the post-faint crash |
| **A2** XP | `0x9D8A30` (predicate entry) | Forces eligibility **only** for the PWB profile (`setup[+0x4A4]==1 && setup[+0x494]==0`); any other battle falls through to the untouched original predicate, so real legendaries keep their own gate |
| **A3** exit | `0x28BD20` (battle-event entry) | At state 5, rewrites the result `1 → 3` ("fainted, no capture") so the battle ends **without** the catch screen — only on a verified KO (`pwb_encounter` + captured HP == 0), one-shot per encounter |
| **A4** evolution | `0x319EC4` (after-battle next-state) | Redirects the would-be evolution-skipping transition so a KO-induced level-up evolves; also clears `pwb_encounter` each battle |

Details, derivation, and the full debugging history are in [`docs/`](docs/) and
[`research/`](research/).

---

## Status & known limitations
- ✅ Wild battle → faint → native EXP (measured, e.g. "Pikachu got 12 Exp. Points!") →
  party distribution → clean return to overworld.
- ✅ Consecutive encounters (per-encounter one-shot re-arms correctly). No crashes.
- ✅ **Evolution** after a KO-induced level-up (A4): verified — Caterpie leveled 6→7 on
  wild-KO EXP and evolved into Metapod via the game's native evolution sequence.
- ✅ **Trainer battles**: tested — fully vanilla (no mod hook fires; normal faints, XP,
  victory flow).
- ⛔ **OPEN RELEASE GATE — real legendary / scripted encounters (e.g. the Route 12/16
  Snorlax):** the XP eligibility change is gated by the game's own static-encounter flags
  (which should exclude real legendaries) and the result rewrite requires this mod's
  verified KO, but **neither has been tested against a real static encounter yet** (the
  development save is early-game). Until that regression passes, do not use this mod on a
  save where you're about to fight Snorlax or a legendary — or disable it for that battle.
- ✅ **Intentional catching:** use the **Catch Variant** (`mods/Wild Battles EXP (Catch
  Variant)/`) — battle → KO → EXP → the normal catch screen stays. Mutually exclusive with
  the main unified mod (enable exactly one). The main build auto-exits after a KO, so a
  defeated Pokémon is gone.
- ❓ Save/reload persistence of gained levels/XP — spot-checked via the user's save/reload during testing; full pass pending.

## Roadmap / next TODOs
- **v0.4.0 / v0.4.1-alpha — explicit encounter isolation (done):** a new hook (M) on PWB's own
  marker write sets a `pwb_encounter` flag, true only during a PWB-synthesized battle. In
  v0.4.1 **every** behavior-changing hook is scoped to it — the faint hook (A), the
  XP-eligibility override (A2) and the model-joint guard (C) all require the marker, and the
  Catch Variant now clears it after each battle (no leak). Verified live: consecutive wild KOs
  re-arm per encounter, trainer battles stay fully vanilla, flee leaves the result untouched,
  and the marker clears on KO / capture / flee. Differential byte verification confirms the
  carried-over caves are logic-identical across versions.
- **Validation backlog (P1):** multi-species HP-capture checks, dedicated save → quit →
  relaunch persistence pass, PP-consumption recheck under both variants, document the Catch
  Variant's evolution limitation (it lacks the A3/A4 chain).
- **v0.5.0-beta — release gates:** scripted Snorlax (Route 12/16) and a real legendary must
  behave fully vanilla (battle + capture opportunity intact) with hook counters at zero;
  ordinary wild/trainer/flee regressions re-passed; save integrity confirmed. **Public beta
  is held until these pass.**
- **Future (post-beta):** an in-battle CATCH action (FireRed-style), merging the two
  variants; shiny/scripted wild-encounter edge cases.

## Repo layout
```
mods/                 the installable mod(s) — unified + catch variant + add-on
tools/                build_patch.py (regenerates the patch) + analysis/verify scripts
docs/                 ENGINEERING_LOG, REPRODUCE, FUNCTION_MAP
research/             raw experiment log, investigation notes, original findings
CONTRIBUTING.md       dev environment, tools, external references, build/test loop
AGENTS.md, CLAUDE.md  operating rules for AI coding agents
CHANGELOG.md, CREDITS.md, DISCLAIMER.md, LICENSE.md
```

## Contributing
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development environment, tooling, and the
build → verify → test loop; AI coding agents should also read [`AGENTS.md`](AGENTS.md).

## Install from a release zip (Eden)
Grab the zip for ONE variant from GitHub Releases, then in Eden: right-click the game →
**Properties → Add-Ons → Import Mod from ZIP** and pick the zip. Enable the mod, disable any
other variant, and restart the game.

## Legal
This is an unofficial, non-commercial fan project, **not affiliated with or endorsed by
Nintendo, Game Freak, Creatures Inc., or The Pokémon Company**. All game trademarks and
copyrights belong to their respective owners. This repository contains **no game code,
assets, or keys** — only original tooling and address-based patch descriptions. A legally
owned copy of the game is required. Full notice: [`DISCLAIMER.md`](DISCLAIMER.md).

The original tooling, docs, and patch descriptions here are MIT-licensed
([`LICENSE.md`](LICENSE.md)); the license grants no rights in any game IP.

## Credits
Base **Wild Battles (PWB1)** mod by **RicoSantos**. Native-EXP mechanism and address map
derived with reference to **raulzrrs/letsgo-recomp** (a recompiler for the Eevee 1.0.0
build) — this project ports the same ideas to the Pikachu 1.0.2 executable as a static
`.pchtxt`. See `CREDITS.md`.
