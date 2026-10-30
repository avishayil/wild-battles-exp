# Engineering log — Wild Battles EXP (Pikachu 1.0.2)

This is the reasoning trail: the goal, the reference implementation, the one bug that cost
days, how each mechanism was found and verified, and what remains. It is
written so another engineer (or AI agent) can understand *why* the patch is what it is.

## 1. Goal
Extend RicoSantos' *Wild Battles* (PWB1) for **Pokémon: Let's Go, Pikachu! v1.0.2** so
that **defeating** a wild Pokémon awards normal battle EXP — no forced catch, no custom XP
math, no emulator fork. Target runtime: Eden/macOS (Apple Silicon, MoltenVK). Program NSO
build-id `C208DB6A4EF4361F28B8402BE0F7CD9A…`.

## 2. Reference: letsgo-recomp
`raulzrrs/letsgo-recomp` is a *recompiler* for the **Eevee 1.0.0** build that already does
this. Its `runtime/hle/wildbattle.c` uses four runtime HLE hooks:
1. `battle_event_hook` — clears the legendary instant-end flag `[evt+0x574] & 0x80` once
   the command menu is up (state 4), so the wild Pokémon **faints**; and at state 5
   rewrites the result `1 → 3` to suppress the capture transition.
2. `model_joint_hook` (Eevee `0xA9C700`) — returns the game's "no joint" result when the
   wild model's resource is missing, avoiding a faint-animation null crash.
3. `exp_hook` — forces the EXP-eligibility predicate true for its custom battle.
4. `after_battle_hook` — redirects the after-battle state `4 → 1` so evolution checks run.

recomp's addresses are for a **different build and must not be copied**. We re-derived
every address against Pikachu 1.0.2 and reproduced the mechanisms as static `.pchtxt`
code (hooks into zero-filled `.text` page padding — a "code cave").

## 3. THE BUG that cost days: the 0x100 address convention
IPSwitch/pchtxt record addresses are **file offsets into the decompressed NSO**, which
begins with a **0x100-byte NSO header**. Therefore:

```
pchtxt_record_address  ==  NSO_memory_offset + 0x100
```

Early work treated the disassembly offset (a memory offset) directly as the pchtxt
address. Every record landed **0x100 too low** in memory. The code cave, meant for the
zero padding at mem `0xD32BA8`, actually overwrote a **live veneer** at mem `0xD32AA8`;
when the game called that veneer during a battle it executed our cave bytes and died.

This produced a long, misleading investigation: an "unmapped read @0xd0 / @0x360" crash in
a condvar/`ArbitrateLock` path on a sibling thread, which looked like an Eden scheduler
race and even got "confirmed" by a (coincidental) no-op experiment. **It was all one
addressing error.** Proof (runtime gdbstub reads of guest memory):

| pchtxt record | bytes land at memory | i.e. |
|---|---|---|
| PWB `0x28BF84` (`28018052…`) | `0x28BE84` | `−0x100` |
| PWB routine `0x305A70` (`FD7BBBA9…`) | `0x305970` | `−0x100` |
| our hook `0x28BF34` | `0x28BE34` | `−0x100` |
| our cave `0xD32BA8` | `0xD32AA8` (live code!) | `−0x100` |

After correcting to `pchtxt = mem + 0x100`, hooking the **per-frame** battle-event
function is completely stable (500+ invocations, zero crashes). The "per-frame hooking is
fatal / Eden condvar race" conclusion was an artifact.

**Process rule adopted:** after deploying any patch, verify the bytes are actually in guest
memory (gdbstub `m <base+mem_offset>`) *before* trusting a run. Don't trust the Eden log's
"Applying IPSwitch patch" line — also confirm the mod is enabled and lands where intended.

Two other environment traps found along the way:
- Eden's **renderer set to Null** shows a black "Launching…" screen forever (CPU runs, no
  frames). Use Vulkan (`[Renderer] backend=1`).
- The Eden **GUI keeps config and enabled-mods in memory**; editing `qt-config.ini` while
  it's open does nothing. Toggle gdbstub / mods in the GUI, or fully quit first.

## 4. The battle lifecycle and the hooks

> The v0.1–v0.3 core is A/C/A2/A3 (faint, crash-guard, EXP, exit). v0.4 added **R** (verified-KO
> HP capture) and **A4** (evolution), and v0.4.1 added **M** — a per-encounter PWB **identity**
> that every behavior-changing hook (A, A2, C) now gates on. See §6.

### Battle-event state machine
`0x28BD20` is the per-frame battle-event update: `x0 → x19` = event object `evt`; it reads
the state word `[evt+0x68]` and dispatches through a jump table. States progress
`0,1,2,3,4,5,…`. State **4** is the command menu; the state-4 handler is `0x28BF34`
(`ldr x20,[x1,#0x60]; cbz x20,…`, where `[x1+0x60]` is the command-menu object). The
legendary instant-end flag is `[evt+0x574] & 0x80`.

### A — make it faint (`0x28BF34`)
Hook the state-4 handler; once the menu object `[x1+0x60]` exists, clear
`[evt+0x574] &= ~0x80`. This routes a KO into the normal **faint**. Verified: the wild
Rattata plays its faint animation instead of instant-ending. We also set a per-encounter
**"armed"** flag here (scratch `+0xFC`) meaning "this mod forced the faint" — used to scope
A3.

### C — survive the faint (`0xA9C650`, model-joint guard)
Clearing the flag makes the game request the wild model's joints during the faint, but a
PWB wild battle doesn't fully set that model up → a null propagates to a later deref and
crashes. `0xA9C650` is the Pikachu equivalent of recomp's `0xA9C700`: entry
`sub sp,sp,#0x70`, arg0 `x0` = model, reads `[model+0x192]` (byte), `[model+0x1e8]`,
`[model+0x1e0]`. Instrumentation confirmed it is called during the faint with a
resource-less model (`+0x192=0, +0x1e8=0, +0x1e0=0`). The guard replicates recomp's
condition: **run the original** if `model==0 || [+0x1e0]!=0 || ([+0x192]!=0 && [+0x1e8]!=0)`;
otherwise return `x0=0` ("no joint") immediately. Verified: post-faint crash gone. From
**v0.4.1** this guard is also gated on `pwb_encounter` — outside a PWB battle it always runs
the original, so a resource-less vanilla model is never force-returned "no joint".

### A2 — award EXP (`0x9D8A30`, predicate entry)
`0x9D8A30` is the EXP-eligibility predicate: `x8=[x0+0x80]` (battle setup); returns 1 only
if `kind<=1 && [setup+0x4A4]==0 && flags[+0x494] bit7 clear && bit0x800 clear`.
Instrumentation showed it returns **0 solely because `[setup+0x4A4]==1`** (`kind=0`,
`flags=0` both pass). Normal XP-eligible battles have `+0x4A4==0`; PWB has `==1`.

v0.1–v0.3 bypassed the `+0x4A4` gate in place (one word at `0x9D8A44`), which was global.
From **v0.4** A2 is a wrapper hooked at the **predicate entry** instead: it forces `w0=1`
only for the PWB **profile** (`setup[+0x4A4]==1 && setup[+0x494]==0`) and otherwise falls
through to the **untouched original** predicate (which keeps its own `+0x4A4` gate, so a real
static encounter is still denied). From **v0.4.1** it additionally requires the PWB
encounter marker (`pwb_encounter`, see M) — so a non-PWB battle that merely shares the profile
can't get modified eligibility. Verified in-game: "Pikachu got 12 Exp. Points!" + party
distribution. The downstream amount function (`0x9D3BA0`, which has its own `+0x4A4`
null-guard that we do **not** touch) computed a real amount.

### A3 — end without the catch screen (`0x28BD20`, state 5)
With the crash gone, the lifecycle now reaches **state 5**. The result chain
`[evt+0x720] → [+0x68] → [+0x508]` holds `1` (normal/faint); recomp rewrites it to `3`
("fainted, no capture"). We hook the battle-event entry and, at `state==5` when the
encounter is **armed** (A set the flag), `result==1`, and not already done, write
`[+0x508]=3` once. From **v0.4** this is gated on a **verified KO** — `have && wild_HP==0`
(see R) — not just the "armed" proxy, so a non-KO ending (e.g. flee) that reaches state 5 is
left alone. The one-shot flags (`+0xFC` armed, `+0xFD` done) are **reset when `state==0`**, so
each new encounter re-arms. Verified: KO → faint → EXP → straight back to overworld, no catch
screen; `result` observed flipping `1→3` once; flee leaves `result` untouched; second
encounter re-armed cleanly.

### R — capture the wild HP (`0x9E41D0`, BTL_POKEPARAM reflect)
To make A3's "verified KO" real, hook the battle-Pokémon "reflect" function (fires at battle
end, KO **and** flee). For the wild slot (`[b+0x87] >= 6`; observed `12`) it records current
HP `[b+0x7e]` into scratch `+0xC8` and sets `have` (`+0xFE`). A KO reads `0`; a flee reads a
live value — which is exactly what lets A3 reject non-KO endings.

### A4 — evolve on a KO level-up (`0x319EC4`, after-battle)
The after-battle processor (`0x319A60`) picks its next state from the result: `3` (which A3
writes) routed to the evolution-**skipping** state 4. Hook the next-state write
`str w8,[x19,#0x68]` at `0x319EC4`: when `evolve_pending` (`+0xFF`, set only by A3's
verified-KO rewrite) and the next state would be 4, write 1 instead (the native
evolution-check state); one-shot. Verified: L6 Caterpie → L7 on wild-KO EXP → native evolution
cutscene → Metapod. This hook also **clears `pwb_encounter`** each battle (see M).

### M — per-encounter PWB identity (`0x3059B8`, v0.4.1 scoping)
A/A2/C change behavior that a *real* legendary/Snorlax (the same special-battle system PWB
reuses) would also hit. To scope them, hook **PWB's own marker write** `str w9,[x20,#0x298]`
inside its injected setup routine (`0x305970`): the cave replays that store and sets
`pwb_encounter` (scratch `+0xF8`). Because PWB writes it once per synthesized encounter, the
flag is true only during a PWB wild battle; A4 clears it after each battle (re-arms per
encounter). A, A2 and C all require it. Caveat: PWB's setup is reached by virtual dispatch, so
static analysis can't prove the marker never fires for a genuine static encounter — PWB's
native discriminator `[evt+0x735]` is the lead to confirm on a live Snorlax (see
`WBEXP_STATIC_CALLGRAPH.md`).

## 5. Code cave & scratch
- **Cave:** the loader page-aligns the `.text` segment size up
  (`PageAlignSize(0xD32BA8)=0xD33000`), so mem `0xD32BA8..0xD33000` (0x458 bytes) is
  zero-filled, RX-mapped, and unused — our cave bodies live here (v0.4.1: caves
  A/C/ST/R/E/P/M laid out consecutively, `0xD32BA8..0xD32E08`, 608 B).
- **Scratch:** mem `0x1EE0F00..0x1EE1000` is the tail of `.bss` (module mapped out to
  `0x1EE1000`), used as an instrumentation/flag "blackboard". `adrp x16,#0x1EE0000` from
  the cave page encodes as `0xD0008D70`. (An earlier bug used mid-`.bss` `0x1956830`, which
  overlapped live globals — use the tail.)

## 6. Done since (v0.4 / v0.4.1) and what remains

**Done and live-verified:**
- **R — enemy-HP capture** and **A3's verified-KO gate** (`have && wild_HP==0`): flee no longer
  triggers the result rewrite.
- **A4 — evolution** on a KO level-up (Caterpie L6→7 → Metapod).
- **M — per-encounter PWB identity** and **v0.4.1 scoping**: A, A2 and C all require
  `pwb_encounter`; A2 is a profile+marker-gated predicate wrapper (not the old global bypass);
  the Catch Variant clears the marker after each battle (no leak). Verified across KO / capture
  / flee / trainer.
- **Catch Variant** (A+C+A2+M+E, no A3/A4): keeps the post-KO catch screen.

**Still open (release gates / validation):**
- **Real static encounter:** a scripted **Snorlax** / **legendary** must stay fully vanilla
  (capture intact). PWB reuses that exact battle system, and the marker's exclusivity can't be
  proven offline (virtual dispatch) — measure `pwb_encounter` and `[evt+0x735]` on a live one.
  This is the gate holding public beta. See `WBEXP_STATIC_CALLGRAPH.md`.
- **Multi-species HP** capture (widen past the observed slot `12`), a dedicated **save/reload**
  persistence pass, and a **PP** control test (base PWB vs EXP vs Catch Variant).
- **Catch-during-battle:** base PWB can't throw a ball mid-battle; a battle CATCH action
  (recomp has related work) would merge the two variants. Post-beta.

## 7. Tooling
- `tools/build_patch.py` — regenerates the add-on and the unified pchtxt from `text.bin` +
  base `pwb1.pchtxt`, with capstone self-verification. **It reproduces the shipped patch
  byte-for-byte.**
- `tools/disasm.py`, `find_refs.py`, `find_caves.py`, `verify_convention.py` — analysis.
- `tools/scratchread.py` — gdbstub reader (memory reads only; **never set software
  breakpoints — they deadlock Eden's JIT**). Used for all runtime verification.

See `docs/REPRODUCE.md` for the step-by-step, `docs/FUNCTION_MAP.md` for the address table,
and `research/` for the raw experiment log and investigation notes.
