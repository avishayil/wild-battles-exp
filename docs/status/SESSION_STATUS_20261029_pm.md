# Wild Battles EXP — session status & reviewer brief (2026-10-29, afternoon)

**Read `Wild_Battles_XP_Findings.md` first** for the full reverse-engineering
state. This file is a short, honest status update layered on top of it: what
this session actually accomplished, the new crash we hit, and the decisions I'd
like a reviewer to weigh in on.

## Goal (unchanged)
Make RicoSantos' "Wild Battles" (PWB1) mod for Pokémon: Let's Go Pikachu v1.0.2
award normal EXP when you **defeat** a wild Pokémon (not just catch it), via a
static `.pchtxt`, on **Eden/macOS**. Title `010003F003A34000`, program build-id
`C208DB6A4EF4361F28B8402BE0F7CD9A…`.

## Are we off track? Partly — yes.
The **research** question has not advanced this session. The last substantive
progress is still the §2b state in the findings doc:

> recomp enables KO XP by clearing the legendary "instant-end" flag
> `[evt+0x574] & 0x80` **only after the command menu (state==4)**, so the wild
> Pokémon faints and the normal EXP path (predicate `0x9D8A30`) runs. We located
> the Pikachu 1.0.2 equivalents statically (battle-event fn `0x28BD20`, state
> word `[evt+0x68]`, flag `[evt+0x574]`, state-4 handler `0x28BF34`, etc.) and
> built a **behavior-preserving tracer** to confirm, at runtime, (a) that the
> cave executes and (b) which field (`+0x298` vs `+0x735`) uniquely marks PWB
> battles. That in-game confirmation is the gate to writing the real two-part
> patch.

Everything this session was **infrastructure and environment**, plus one crash
that is blocking the trace. Net research gain: a single data point (below).

## What this session did
1. **Policy change (recorded):** per company policy the AI must **not launch the
   app**. The debug harness `tools/dbg.sh` was amended to prepare everything
   (deploy patch, enable gdbstub, start the reader) and **print** the launch
   command for the user to run manually. Killing stale processes is still done
   by the harness.
2. **Fixed a "frozen at boot" red herring:** Eden's renderer had been set to
   **Null** (`qt-config.ini [Renderer] backend=2`; title bar showed `NULL`). The
   game ran headless (CPU busy, gdbstub resumed fine) but never drew a frame, so
   it sat forever on the Switch "Launching…" splash. Set `backend=1` (Vulkan).
   This was not the debugger and not the patch.
3. **Ran the tracer (`patches/pwb1_trace4.pchtxt`) into a wild Rattata battle.**
   The hook at `0x28BD20` fired once and logged one clean sample, then the guest
   crashed (details below) before reaching the command menu.

### The one data point we got (battle start, state 0)
```
state=0  seen=0b1  +0x574=0x00000000  +0x562=25646  +0x735=1  calls=1  evt=0x21b1ddb6b0
```
Reading: at battle-start of a PWB wild battle, the instant-end flag `[evt+0x574]`
is **0** (not yet set at state 0), `[evt+0x735]==1`, and the battle-event object
is valid. This is consistent but insufficient — we need the **state 4/5** samples
(command menu and result) to confirm the discriminator and the `+0x574` timing.
We never got them because of the crash.

## The crash (this is what's blocking us)
Eden halted the guest: `Core.ARM Critical: unmapped memory access at 0xd0`.
Full dump saved in `work/crash_20261029_1548.txt`. Summary:

- **Faulting PC = `nnSdk+0xd9838`** (an `svc`/`ret` trampoline sled), **LR =
  `nnSdk+0xb4c30`**. The fault is a read of `[null + 0xd0]` (a pointer other than
  `x0` was null; `x0`/`x19` held a valid heap object).
- **Stack unwind** (frame-pointer chain), bottoming cleanly at thread start:
  ```
  #0 nnSdk+0xa9ff4
  #1 beluga.nss+0x21124
  #2 beluga.nss+0x1f8d4
  #3 beluga.nss+0x393d0
  #4 beluga.nss+0x39344
  #5 beluga.nss+0x4900     (near game main / thread entry — LOW .text)
  #6 nnSdk+0x849bc         (thread trampoline)
  #7 nnrtld+0xac           (rtld start)
  ```
- **The stack never passes through our hook (`0x28BD20`) or our cave
  (`beluga+0xD32BA8` = `0x81376ba8`).** The game-side frames are all low `.text`
  offsets (`0x4900`–`0x393d0`), i.e. the main/system path, **not** the battle
  code we patched (`0x28BD20`, `0x9D8A30`, `0xA58Axx` are all much higher).
- The tracer itself is provably correct: the displaced original instruction
  matches vanilla (`0x28BD20 = sub sp,sp,#0x70`), the return branch resolves to
  `0x28BD24`, it preserves x14–x17, reads only the same object the vanilla code
  reads, and the cave sits in loader zero-padding (vanilla bytes there are all
  zero; nothing references it).

**Interpretation / leading hypothesis:** this is an **environmental** crash in a
system/nnSdk path, most likely GPU/resource-related, surfacing when the battle
scene loads — not caused by our passive tracer. Suspicion points at the renderer:
the Vulkan instance logged `VK_KHR_portability_enumeration is not available` at
boot, and the renderer was just switched Null→Vulkan this session. Prior PoC v1
testing earlier today (same PWB mod, predicate-force patch) **did** run a wild
battle to completion, which argues the PWB battle path is not inherently crashing
— so something about this boot/config is different.

**Caveat:** "environmental" is a hypothesis, not proven. It has **not** been
isolated with a control run.

## The decision I'd like the reviewer to make
The next step should isolate the crash before any more tracing. Options:

- **A. Control run (recommended):** disable the "Wild Battles EXP" mod entirely
  (leave only base PWB) and encounter a wild Pokémon.
  - If it **still** crashes at `~0xd0`/nnSdk → the crash is environmental or
    PWB-inherent on this build; it must be fixed/avoided before the tracer can
    reach state 4. (Then: check Eden version `de7e6e01d4-master`, Vulkan device,
    MoltenVK, firmware, or try a known-good Eden build / the save state that PoC
    v1 used.)
  - If it does **not** crash → our tracer perturbs something despite the static
    analysis; re-examine the cave/JIT interaction.
- **B. Re-test with PoC v1 (known to have run a battle)** to re-establish a
  working baseline on the current config, then reintroduce the tracer.
- **C. Abandon the pchtxt-tracer approach** for confirmation and instead read the
  battle-event state **externally** via gdbstub memory reads of `[evt+0x68]`,
  `[evt+0x574]`, etc. — resolving `evt` from a known global rather than hooking
  `0x28BD20` at all. Slower to poll, but touches zero guest code.

My recommendation: **A first** (cheap, one encounter), because it answers the
only question that matters right now — is the crash ours or the environment's.

## Key files
- `Wild_Battles_XP_Findings.md` — full RE state, function map, §2b route.
- `work/crash_20261029_1548.txt` — this crash's registers + backtrace.
- `patches/pwb1_trace4.pchtxt` / `tools/trace4.S` — the behavior-preserving tracer
  (hook `0x28BD20` → cave `0xD32BA8`, logs to scratch `beluga+0x1956830`).
- `tools/scratchread.py` — safe live reader (gdbstub memory reads only; breakpoints
  deadlock Eden). `tools/dbg.sh` — prep harness (no longer launches Eden).
- Mod folder: `~/.local/share/eden/load/010003F003A34000/Wild Battles EXP/exefs/`.
- Save snapshot: `bak/save-20261029-121905/` (intact).

## Environment notes for the reviewer
- Eden build: `de7e6e01d4-master`, Clang 23.1.3, macOS (Apple Silicon, MoltenVK).
- Launch manually (policy): `MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1
  MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0 "$HOME/Applications/eden.app/Contents/MacOS/eden"`.
- gdbstub currently ENABLED (`qt-config.ini use_gdbstub=true`, port 6543); the
  guest halts at boot until a client sends `c` (the reader does this). Disable for
  normal play.
- Renderer now `backend=1` (Vulkan). Do **not** leave it at `2` (Null).
