<div align="center">

<!-- Banner slot: drop an ORIGINAL logo/banner at docs/assets/banner.png.
     Do NOT commit copyrighted Nintendo / Game Freak / Pokémon artwork — see docs/assets/README.md. -->
<img src="docs/assets/banner.png" alt="Wild Battles EXP" width="620">

# Wild Battles EXP

**Defeat a wild Pokémon → earn real experience.**
Native battle EXP for wild knockouts in *Pokémon: Let's Go, Pikachu!* — entirely through the game's own battle, faint, EXP and evolution code.

[![Release](https://img.shields.io/badge/release-v0.4.1--alpha-e67e22)](https://github.com/avishayil/wild-battles-exp/releases)
[![License](https://img.shields.io/badge/license-MIT-3498db)](LICENSE.md)
![Game](https://img.shields.io/badge/Let's%20Go%20Pikachu-v1.0.2-f1c40f)
![Emulator](https://img.shields.io/badge/Eden-MoltenVK-9b59b6)
![Status](https://img.shields.io/badge/status-experimental%20alpha-e74c3c)

</div>

> ⚖️ **Unofficial, non-commercial fan project — not affiliated with, endorsed, or sponsored by
> Nintendo, Game Freak, Creatures Inc., or The Pokémon Company.** All game trademarks and
> copyrights belong to their respective owners. **No game code, assets, ROMs, or keys are
> distributed** — only original tooling and address-based patch descriptions; a legally owned
> copy of the game is required. Read the full [legal notice](DISCLAIMER.md) before using this mod.

---

A static IPSwitch (`.pchtxt`) mod for **Pokémon: Let's Go, Pikachu! v1.0.2** (Switch, title
`010003F003A34000`, program NSO build-id `C208DB6A…`) that makes **defeating** a wild Pokémon
award normal battle **experience** — the way the main-series games do — on top of RicoSantos'
*Wild Battles* (PWB1) mod. There is **no custom XP formula and no modified emulator**.

```text
Walk into a wild Pokémon  →  battle it  →  KO it  →  it faints
  →  your party gains native EXP (real amounts, normal level-ups, evolutions)
  →  you return straight to the overworld (no catch screen)
```

Developed and verified on **Eden** (macOS, Apple Silicon / MoltenVK).

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Install](#install)
- [Status & known limitations](#status--known-limitations)
- [Roadmap](#roadmap)
- [Contributing & reproducing](#contributing--reproducing)
- [Repository layout](#repository-layout)
- [Legal](#legal) · [Credits](#credits)

## What it does

Wild battles created by PWB1 reuse the game's *legendary / Snorlax* "special battle" system,
which is wired to **end instantly with no faint and no EXP**. This mod flips that battle onto the
normal faint → reward path, fills the gaps the special-battle setup leaves behind, and **scopes
every change to PWB's own encounters** so it never touches a real battle.

| Piece | Hook (NSO offset) | Effect |
|---|---|---|
| **M** PWB marker | `0x3059B8` | Replays PWB's own per-encounter marker write and sets a `pwb_encounter` flag — true only during a PWB-synthesized wild battle. The identity every other hook keys off. |
| **A** faint | `0x28BF34` | Clears the legendary "instant-end" flag once the command menu exists **and `pwb_encounter` is set**, so a KO **faints**. |
| **C** model guard | `0xA9C650` | Returns "no joint" for a resource-less wild model (prevents a post-faint crash); **gated on `pwb_encounter`**. |
| **A2** XP | `0x9D8A30` | Forces EXP eligibility **only** for a PWB encounter matching the PWB profile; every other battle runs the game's untouched predicate. |
| **A3** exit | `0x28BD20` | On a **verified KO** (captured enemy HP == 0), rewrites the battle result so it ends **without** the catch screen (one-shot per encounter). |
| **A4** evolution | `0x319EC4` | Redirects the after-battle transition so a KO-induced level-up **evolves**; also clears `pwb_encounter` each battle. |

Details and the full debugging history are in [`docs/`](docs/) and [`research/`](research/).

## Install

You need the game dumped and running under an emulator that supports IPSwitch `.pchtxt` mods
(tested on Eden; Ryujinx/yuzu-family loaders use the same format). This targets **v1.0.2**
specifically — the update must be applied so the running program matches build-id `C208DB6A…`.

### From a release zip (recommended)
Grab **one** variant's zip from [**Releases**](https://github.com/avishayil/wild-battles-exp/releases).
In Eden: right-click the game → **Properties → Add-Ons → Import Mod from ZIP**, pick the zip,
enable it, disable any other variant, and restart the game.

| Variant | Behaviour |
|---|---|
| **Wild Battles EXP** (main) | wild KO → EXP → auto-exit to the overworld (no catch screen). |
| **Wild Battles EXP (Catch Variant)** | wild KO → EXP, but the normal **catch screen stays**. |
| **Add-on** | for people already running RicoSantos' *Wild Battles* — enable both. |

> ⚠️ **Enable exactly one** of the main / catch variants — each is a full build that already
> contains the base *Wild Battles* records; running two would double-apply them.

### Launch note (Eden / macOS)
Developed/tested launching Eden with MoltenVK workarounds, using the **Vulkan** renderer (a Null
renderer shows a black "Launching…" screen):

```sh
MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1 MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0 \
  "$HOME/Applications/eden.app/Contents/MacOS/eden"
```

## Status & known limitations

- ✅ Wild battle → faint → native EXP (measured, e.g. *"Pikachu got 12 Exp. Points!"*) → party
  distribution → clean return to the overworld.
- ✅ Consecutive encounters (per-encounter one-shot re-arms). No crashes.
- ✅ **Evolution** after a KO-induced level-up (Caterpie L6 → L7 → Metapod, native cutscene).
- ✅ **Trainer battles**: fully vanilla — no hook fires.
- ✅ **Flee / intentional catching** (Catch Variant): the result is left untouched; the marker
  clears on KO, capture and flee with no leak into the next battle.
- ⛔ **OPEN GATE — real legendary / scripted encounters (e.g. the Route 12/16 Snorlax):** PWB
  reuses that same battle system, so isolation is designed to exclude them, but this has **not
  been tested on a live static encounter yet** (the development save is early-game). Until that
  passes, don't rely on this mod during such a battle.
- ❓ Full save/reload persistence pass and a PP-consumption recheck are still pending.

**This is alpha software — back up your saves.**

## Roadmap

- **v0.4.0 / v0.4.1-alpha — encounter isolation (done):** every behavior-changing hook (A, A2,
  C) is scoped to PWB's own per-encounter marker; the Catch Variant clears it each battle.
  Live-verified across KO / capture / flee / trainer.
- **Validation backlog:** multi-species HP-capture checks, a dedicated save → relaunch
  persistence pass, a PP-consumption control test.
- **v0.5.0-beta — release gates:** a scripted Snorlax and a real legendary must stay fully
  vanilla (capture intact). **Public beta is held until these pass.**
- **Future:** an in-battle CATCH action (FireRed-style) merging the two variants; shiny /
  scripted wild-encounter edge cases.

## Contributing & reproducing

Everything regenerates byte-for-byte from one source of truth:

```sh
python3 -I tools/build_patch.py --text text.bin --pwb pwb1.pchtxt \
  --out-addon addon.pchtxt --out-unified unified.pchtxt --out-catch-unified catch.pchtxt
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development environment, tooling, and the
build → verify → test loop; AI coding agents should also read [`AGENTS.md`](AGENTS.md).
The full function/field map is in [`docs/FUNCTION_MAP.md`](docs/FUNCTION_MAP.md), step-by-step
reproduction in [`docs/REPRODUCE.md`](docs/REPRODUCE.md), and the reasoning trail in
[`docs/ENGINEERING_LOG.md`](docs/ENGINEERING_LOG.md).

## Repository layout

```text
mods/        the installable mods — main unified · catch variant · add-on
tools/       build_patch.py (regenerates every patch) + gdbstub reader + packaging
docs/        ENGINEERING_LOG · REPRODUCE · FUNCTION_MAP · WBEXP_STATIC_CALLGRAPH · status/
research/    raw experiment log, investigation notes, original findings, hook research
CONTRIBUTING.md · AGENTS.md · CLAUDE.md   dev + AI-agent guides
CHANGELOG.md · CREDITS.md · DISCLAIMER.md · LICENSE.md
```

## Legal

Unofficial, non-commercial fan project, **not affiliated with or endorsed by Nintendo, Game
Freak, Creatures Inc., or The Pokémon Company**. All game trademarks and copyrights belong to
their respective owners. This repository contains **no game code, assets, or keys** — only
original tooling and address-based patch descriptions created through independent
interoperability research. A legally owned copy of the game is required. Full notice:
[`DISCLAIMER.md`](DISCLAIMER.md). The original tooling, docs, and patch descriptions here are
MIT-licensed ([`LICENSE.md`](LICENSE.md)); the license grants no rights in any game IP.

## Credits

Base **Wild Battles (PWB1)** mod by **RicoSantos**. Native-EXP mechanism and address map derived
with reference to **[raulzrrs/letsgo-recomp](https://github.com/raulzrrs/letsgo-recomp)** (a
recompiler for the Eevee 1.0.0 build) — this project ports the same ideas to the Pikachu 1.0.2
executable as a static `.pchtxt`. See [`CREDITS.md`](CREDITS.md).
