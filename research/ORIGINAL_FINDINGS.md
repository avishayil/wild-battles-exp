# Wild Battles EXP — findings & handoff (Pokémon Let's Go Pikachu 1.0.2)

**Status (2026-10-29):** No working XP patch yet. The reward path originally
targeted has been **empirically ruled out** by live tracing. This document is a
starting point for the next agent / external reviewer. Read it before touching
anything; several "obvious" moves here are already known-wrong and one caused a
guest crash.

---

## 1. Goal

Extend RicoSantos' **"Wild Battles" (PWB1)** IPSwitch mod for **Pokémon: Let's
Go, Pikachu! v1.0.2** (Switch, title `010003F003A34000`, program NSO build-id
`C208DB6A4EF4361F28B8402BE0F7CD9A…`) so that **defeating** a wild Pokémon awards
normal battle EXP — *without* requiring a catch, without double-counting at the
catch screen, and without altering trainer/scripted/legendary battles. Target
runtime is **Eden on macOS** (Apple Silicon, MoltenVK).

Prior art: `raulzrrs/letsgo-recomp` (a recompiler for the **Eevee 1.0.0** build)
got this working with a **runtime-conditional HLE hook** that forces an
EXP-eligibility predicate to return true only during its custom battles. Its
address `0x70009d8ae0` is from a different build and must not be copied.

---

## 2. TL;DR of conclusions

1. **Extraction & build-id are verified.** We have the exact decompressed
   `main` for this build. The IPSwitch address convention is confirmed:
   `file_offset_in_main_dec = pchtxt_addr + 0x100` (proved against all 23 PWB1
   records).

2. **The EXP-eligibility predicate exists at `0x9D8A30`** and is structurally a
   perfect match for recomp's `9d8ae0` (checks battle kind ≤ 1, setup byte
   `+0x4A4 == 0`, and flags word `+0x494` bits `0x80`/`0x800`). **But forcing it
   to return 1 does nothing on a wild KO.**

3. **DECISIVE:** On a wild KO in a PWB battle, live tracing shows the predicate
   `0x9D8A30` and the encounter tester `0x9D8A80` are **never called** (hit
   counters stayed 0). The whole eligibility/reward path we patched is **not the
   code that runs when a PWB wild Pokémon faints.** KO goes down the
   legendary/Snorlax-style *"battle ends immediately, no faint, no XP"* branch.

4. **The `+0x4A4` check inside the EXP-amount function `0x9D3BA0` is a NULL/empty
   -context guard, NOT a wild-XP suppressor.** Removing it (PoC v3) made the
   function dereference a null object → `Unmapped Read @ 0x170` → guest crash.
   Do not touch that early-out.

5. **XP-related functions are virtual-dispatched** through vtable thunk tables
   (region `0xa0a0f0+`: `ldr x0,[x0,#0x60]; b <target>` forwarders), reached by
   `blr`, not direct `bl`. Static `bl`-caller scans therefore undercount callers.
   The battle object pointer lives in `x0`; the controller sub-object is
   `[x0+0x60]`, and battle-setup is `[x0+0x80]`.

6. **Core difficulty:** recomp's fix was *conditional at runtime*. A static
   `.pchtxt` rewrites bytes unconditionally and can only branch on state it can
   read from memory. We have a candidate discriminator (PWB stamps
   `[battle_setup+0x298] = 1`), but we first need to find *where the KO-reward
   decision is actually made in the immediate-end battle flow* — and the trace
   shows it is none of the three functions investigated so far.

---

## 2b. UPDATE (post-review): the faint-path route is located

An external review (and re-reading the **current** recomp `0.7.5`
`runtime/hle/wildbattle.c`) corrected two of this doc's earlier claims and
pointed at the right mechanism. **Both corrections are now confirmed in this
build.**

**recomp's actual XP mechanism (3 parts, decoded from source):**
1. `battle_event_hook` clears the legendary "instant-end" flag — `evt[+0x574] &=
   ~0x80` — but **only once the command menu is up** (`state==4 && menu_seen`).
   Clearing it earlier hangs the opening. This lets the KO'd wild Pokémon
   *faint* like a trainer battle, which is what drives the normal XP path.
2. `exp_hook` forces the eligibility predicate (`0x9D8A30` here) to return 1.
3. `model_joint_hook` (Eevee `0xa9c700`) guards the faint animation's joint
   lookup so the missing wild-battle model doesn't crash (`c->x[0]=0` = "no
   joint" when `!m || (m[+0x192]&&m[+0x1e8]) || m[+0x1e0]` is false).
   recomp also rewrites the result `evt→[+0x720]→[+0x68]→[+0x508]` from `1` to
   `3` at `state==5` for the "fainted, no capture" case.

**Why every earlier PoC failed:** none cleared `+0x574 & 0x80`, so the PWB KO
always took the instant-end branch and the predicate was never reached (the
`PRED n=0` trace). The predicate at `0x9D8A30` was the right function all along.

**Pikachu 1.0.2 equivalents located (static analysis):**

| Thing | Eevee (recomp) | **Pikachu 1.0.2** | Notes |
|---|---|---|---|
| Battle-event update fn | `0x28be80` | **entry `0x28BD20`** | `x0→x19` = battle-event object; state read at `0x28BD3C` |
| State dispatch | — | **jump table mem `0xF4D08C`**, states 0..0xC | `ldrsw`+`br`; state-4 handler `0x28BF34`, state-5 `0x28BF70` |
| State word | `[evt+0x68]` | **`[evt+0x68]`** | handler advances 4→5 |
| Legendary instant-end flag | `[evt+0x574] & 0x80` | **`[evt+0x574] & 0x80`** | confirmed on x19; RMW sites at `0x28C570`/`0x28C5B8` |
| Result chain | `[evt+0x720]→[+0x68]→[+0x508]` | **same** | exact match at `0x28C130`; res 1=normal/faint, 3=faint-no-capture |
| Time limit ("MATCH TIME") | `[evt+0x562]` | **`[evt+0x562]`** (byte `+0x584` related) | STATIC_SETUP writes 300s |
| Static setup | `0x28c770` | ~`0x28Cxxx` (PWB hooks this region) | sets the flag + time limit |
| EXP predicate | `0x9d8ae0` | **`0x9D8A30`** | unchanged finding |
| Model-joint guard | `0xa9c700` | **TBD** (find fn reading `+0x1e0`/`+0x1e8`/`+0x192`) | needed to avoid faint-anim crash |

**Code-cave blocker SOLVED.** Earlier "no caves" was wrong in consequence:
the `.text` segment size is **page-aligned up** by Eden's loader
(`PageAlignSize(0xD32BA8)=0xD33000`, proven in `eden/src/core/loader/nso.cpp`),
so the **0x458-byte zero gap at mem `0xD32BA8`–`0xD33000` is RX-mapped and
patchable** — a real code cave, disjoint from PWB. First hook built there (the
tracer, §8) verifies this empirically.

**Two-part patch recipe (once the trace confirms the discriminator):**
- **Faint enable:** hook the state-4 handler (`0x28BF34`) or the battle-event
  entry via the `0xD32BA8` cave; when `state==4` **and the battle is a PWB
  battle** (discriminator TBD — `[evt+0x298]` and byte `[evt+0x735]` are the
  candidates under test) **and** `[evt+0x574] & 0x80`, do `[evt+0x574] &= ~0x80`.
  Preserve all other battles (real legendaries/Snorlax keep the flag).
- **Model safety:** port the `model_joint` guard to the Pikachu equivalent to
  prevent the faint-animation null-model crash recomp documented.
- EXP then flows natively; `0x9D8A30` (already provably patchable to return 1,
  gated to PWB) supplies eligibility. Post-battle: verify no mandatory catch and
  no double XP via the result field `[bd+0x508]`.

**Corrections to §2/§9/§11 of the original doc:** (a) clearing `+0x574 & 0x80`
IS usable when delayed to after the command menu — the "unusable" conclusion was
based on recomp's *early* attempt; (b) a static pchtxt CAN branch on runtime
memory (it installs ARM64 code) — the "cannot replicate runtime conditionality"
claim was too strong; (c) a code cave does exist (`0xD32BA8`), so hooking does
not require clobbering a live function or calling the reward fn from `0x305A70`.

**Current deliverable:** `patches/pwb1_trace_be.pchtxt` — a behavior-preserving
tracer hooked at `0x28BD20`→cave `0xD32BA8`, logging the state timeline,
`[evt+0x574]`, and discriminator candidates `[evt+0x298]`/`[evt+0x735]` to the
blackboard at mem `0x1EE0F40..0x1EE0F64`. Read with `tools/memtrace.py` (updated
field layout). Awaiting an in-game run of a PWB wild battle (+ a trainer and a
real legendary for contrast) to (1) confirm the `0xD32BA8` cave executes and
(2) identify the field that uniquely marks PWB battles.

---

## 3. Reproduction environment

- **Project dir:** `<project-dir>` (not a git repo).
- **Game assets:** `Games/Pokemon Lets Go Pikachu v102.nsp` (65 MB update NSP —
  contains the v1.0.2 Program NCA), `v100.nsp` (4.4 GB base), `bak/…xci` cart
  dump, `prod.keys` at project root.
- **Eden (macOS):** `~/Applications/eden.app/Contents/MacOS/eden`, launched as:
  ```
  MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1 MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0 \
    "$HOME/Applications/eden.app/Contents/MacOS/eden"
  ```
- **Eden data dir:** `~/.local/share/eden/`
  - Live base mod: `load/010003F003A34000/Wild Battles/exefs/pwb1.pchtxt`
  - Our mod folder (sibling): `load/010003F003A34000/Wild Battles EXP/exefs/pwb1_exp.pchtxt`
  - Save: `nand/user/save/0000000000000000/<your-save-id>/`
  - Logs: `log/eden_log.txt`
  - Config: `~/.config/eden/qt-config.ini`
- **Eden source** is checked out at `eden/` (useful for understanding the loader
  and gdbstub).
- **Save snapshot** taken before testing: `bak/save-20261029-121905/` (intact; the
  crash was a CPU halt, not a save write).

---

## 4. Extraction & verification (reproducible)

Tooling built/installed: **hactool** from source at `tools/hactool-src/` (vendors
lz4+mbedtls; `cp config.mk.template config.mk && make`), **capstone** (pip),
**Ghidra** (brew cask). `/usr/bin/objdump` on this Mac is already LLVM-21
llvm-objdump (ELF+AArch64), and Apple clang assembles AArch64 ELF
(`clang -target aarch64-none-elf -c`), so no extra toolchain is needed.

```bash
HT=tools/hactool-src/hactool
# 1. unpack update NSP
$HT -k prod.keys -t pfs0 --outdir=work/nsp_v102 "Games/Pokemon Lets Go Pikachu v102.nsp"
# 2. Program NCA = 2b7730a9… (Content Type Program). It uses TITLEKEY crypto
#    (Rights ID 010003F003A348000000000000000007); the ticket is in the NSP:
TK=$(xxd -s 0x180 -l 16 -p work/nsp_v102/010003f003a34800*0007.tik | tr -d '\n')  # (titlekey; derive from your own dump)
# 3. extract exefs (update NCA carries a COMPLETE exefs; romfs-only is BKTR)
$HT -k prod.keys --titlekey=$TK -t nca --exefsdir=work/exefs_v102 work/nsp_v102/2b7730a9*.nca
# 4. VERIFY build-id (NSO header +0x40) == c208db6a4ef4361f28b8402be0f7cd9a… — ELSE ABORT
xxd -s 0x40 -l 32 -p work/exefs_v102/main
# 5. decompress NSO → main_dec.bin, carve .text
$HT -k prod.keys -t nso0 --uncompressed=work/main_dec.bin work/exefs_v102/main
dd if=work/main_dec.bin of=work/text.bin bs=256 skip=1   # drop 0x100 header; see §5
```

NSO segment layout (from header): `.text` fileOff `0x100`, memOff `0`, size
`0xD32BA8`; `.rodata` fileOff `0xD33100`, memOff `0xD33000`; `.rwdata`/`.bss`
follow. **`.bss` extends mapped memory out to mem `0x1EE1000`** — the tail of
this region (we used `0x1EE0F00`) is a usable scratch "blackboard" for
instrumentation (see §8).

---

## 5. Address convention (confirmed)

**`pchtxt address` == NSO memory offset; `file offset in main_dec.bin` ==
`pchtxt_addr + 0x100`.** Verified by `tools/verify_convention.py`: for all 23
PWB1 records, vanilla bytes at `addr+0x100` differ from the patch bytes and
disassemble as plausible pre-patch code, and the internal branch
`0x28C01C → 0x305BF0` lands exactly as encoded. Patch bytes are little-endian
AArch64 instruction words. Eden's pchtxt parser treats `/` and `#` as comment
markers (confirmed in `eden/src/core/file_sys/ips_layer.cpp`).

---

## 6. Function map (this build)

All addresses are pchtxt/mem offsets in `main`.

| Addr | Role (confidence) |
|---|---|
| `0x9D8A30` | **EXP-eligibility predicate.** kind≤1 (`[x8]`), `[x8+0x4A4]==0`, flags `[x8+0x494]` bits `0x80`/`0x800`; returns 0/1 in w0. `x8=[x0+0x80]`. Structural match for recomp `9d8ae0`. **Not called on wild KO.** |
| `0x9D8A80` | `+0x4A4==0` tester → bool. Sole static caller `0xA58CEC`. **Not called on wild KO.** |
| `0x9D3BA0` | **EXP-amount.** Early-out `cbz` at `0x9D3BAC` guards on `[x8+0x4A4]` (this is a **null/empty-context guard**); otherwise base exp `[x8+0x170]`, multipliers `[x8+0x540/0x541]`, cap `0x1869F`. **Called once with x0=NULL on wild KO.** |
| `0xA58AD0–0xA58F80` | **Catch-phase reward state machine.** Emits message ids incl. `0x44` ("got N Exp. Points!") built at `0xA58D60`. Calls `0x9D3BA0`, `0x9D8A80`. This is the path that pays XP **on catch** (unchanged, works). |
| `0x9F28C0`, `0x9F6180` | Battle-end/turn-outcome functions that call predicate `0x9D8A30` in the *normal* (non-immediate-end) flow. |
| `0xa0a0f0+` | **vtable thunk table**: tiny forwarders `ldr x0,[x0,#0x60]; b <fn>` (e.g. `0xa0a130→0x9d3d30`, `0xa0a170→0x9d8ab0`, `0xa0a150→bl 0x9d8d20`). XP fns are virtual-dispatched through these via `blr`. |
| `0x9D3A00` | Populates battle summary fields `[setup+0x53c]`, `[setup+0x542]`; reaches the thunk table. The null-context AMOUNT hit's return addr (`0x9D3A74`) is in this neighborhood — exact chain **TBC** (dispatch is virtual, so lr attribution is unreliable). |

### PWB1 mod mechanism (recap, from `pwb1.pchtxt` + disassembly)
PWB reuses the special wild-battle (Snorlax/legendary) system. Its injected
routine at `0x305A70` (entered via `bl` patched at `0x305A34`) copies encounter
data into the handle and — key for us — writes a marker: `mov w9,#1;
str w9,[x20,#0x298]` at `0x305AB8`. It also NOPs vanilla instructions at
`0x2FE034` (`mov x0,x21`) and `0x2FE080` (`blr x8`) inside a battle-teardown
loop (likely result-sequence/crash-avoidance tweaks — unverified). The encounter
hooks set configuration values 9/10 (`0x28BF84`, `0x28C2A0`, `0x305C10`).
`[battle_setup+0x298]==1` is a plausible "this is a PWB battle" discriminator and
was confirmed to live in the same struct the predicate reads (initializer around
`0xB4C4xx` touches `+0x298`, `+0x494`, `+0x4A4`).

---

## 7. What was tried, and what each attempt proved

All patches were authored as a **separate** mod folder ("Wild Battles EXP"),
overlap-checked against PWB1 (`tools/check_overlap.py`), and round-tripped
through the kit's `inspect_pchtxt.py` + objdump before deploy. PWB1 itself was
never edited. Eden's loader log confirms both mods apply to build-id
`C208DB6A…` at boot, in order (Wild Battles, then Wild Battles EXP).

- **PoC v1** — `0x9D8A30 → mov w0,#1; ret`. *In-game: no EXP on KO.* Patch
  confirmed applied in `eden_log.txt`. ⇒ forcing the predicate alone is
  insufficient.
- **PoC v2** — also removed the `0x9D3BAC` early-out and forced `0x9D8A80 → 1`.
  *In-game: still no EXP on KO; XP only after catching (= vanilla behavior).*
  ⇒ the functions being patched belong to the **catch-phase** reward sequence,
  not the KO path.
- **PoC v3 (instrumented)** — same three functions rewritten to **log** hit
  counters + live field values to the `.bss` blackboard, and (mistakenly)
  removed AMOUNT's `+0x4A4` guard. *Trace result (below) + guest crash.*

### The decisive v3 trace (wild KO)
Blackboard readout immediately before the freeze:
```
PRED   n=0            (0x9D8A30 never called)
TESTER n=0            (0x9D8A80 never called)
AMOUNT n=1 lr=+0x9D3A74 base_exp=0   (0x9D3BA0 called once, x0 = NULL)
```
Eden log at the freeze:
```
Core.ARM Stopping execution due to unmapped memory access at 0x170
HW.Memory Unmapped Read32 @ 0x170     (then 0x197, 0x540, 0x541)
```
Interpretation: AMOUNT ran with a **null battle object**; with the `+0x4A4`
guard removed it read `[null+0x170]` etc. ⇒ the guard is a null/empty-context
check. And because PRED/TESTER were never hit, the KO reward is dispatched
somewhere we have **not** yet identified — consistent with the recomp note that,
with bit `0x80` of setup `+0x574` set, a KO ends the battle immediately with no
faint and no XP.

The mod was reverted to the harmless PoC v1 after the crash.

---

## 8. Tooling built (all under `tools/`, run kit scripts with `python3 -I`)

- `verify_convention.py` — proves the `+0x100` address rule against PWB1.
- `disasm.py <text.bin> <start> <end> [--func]` — capstone window disassembler
  (addresses = mem offsets).
- `find_refs.py {bl|ptr|fieldstr} …` — direct `bl` callers, 8-aligned pointer
  refs, and `ldr/str`-by-field-offset scans.
- `find_rela.py` — scans `.rela.dyn` R_AARCH64_RELATIVE entries (addend→slot);
  used to check for vtable pointers (found none for the XP fns → they're reached
  via the `0xa0a0f0` thunks, not data pointers).
- `find_caves.py` — zero/NOP code-cave scan (result: **no** ≥0x40 caves in
  `.text` outside PWB1's ranges; the gated rewrite had to fit in-place).
- `check_overlap.py` — asserts a new pchtxt is disjoint from PWB1 + same nsobid.
- `instr.S` + `patches/pwb1_exp_poc3.pchtxt` — instrumentation template; writes
  counters/values to blackboard page mem `0x1EE0F00+` (adrp targets precomputed
  per site; see comments).
- `memtrace.py` — **the safe live tool.** Connects to Eden's gdbstub, resumes
  boot, and polls the blackboard with memory reads only (no breakpoints). Prints
  a line whenever any logged value changes.
- `gdbtrace.py` — breakpoint-based tracer. **Abandoned** (see gotcha below).

Patches on disk: `patches/pwb1_exp_poc.pchtxt` (v1), `…poc2`, `…poc3`,
`pwb1_exp.pchtxt` (a gated release *candidate* that is now known to be aimed at
the wrong path — do not ship).

### gdbstub gotchas (important)
- Enable with `use_gdbstub=true` in `~/.config/eden/qt-config.ini` (port 6543).
  The game **halts at boot** until a client attaches and sends `c`. Disable it
  again for normal play.
- **Software breakpoints (`Z0`) reliably DEADLOCK Eden**, both at boot and
  mid-game: the insert path calls `InvalidateInstructionCacheRange` →
  `m_jit->HaltExecution(CacheInvalidation)` and wedges. Two separate attempts
  froze the emulator this way. **Use memory reads (`m addr,len`) only.** This is
  why instrumentation-to-a-blackboard + `memtrace.py` is the chosen technique.
- `qRcmd,"get info"` returns module bases; `main` may be unnamed — match it by
  size (`0x1EE1000`). ASLR changes the base every boot; resolve it live.

---

## 9. Open questions for the reviewer

1. **Where is the KO reward decision in the immediate-end (legendary-style)
   battle flow?** It is not `0x9D8A30`/`0x9D8A80`/the `0xA58Axx` catch sequence.
   recomp's notes point at setup `+0x574` bit `0x80` and byte `+0x584` governing
   the "no faint / no XP" behavior, and at `0x28C770` as the static-battle setup.
   What runs between KO and "battle end" for this battle kind?
2. **Is `0x9D8A30` actually recomp's `9d8ae0` equivalent, or a sibling?** It
   matches structurally but is never consulted here. Did recomp's battles reach
   it because they were configured differently from PWB's (recomp builds the
   class-A process via factory `0x17f0a0` and hooks `0x305ad0`; PWB uses the
   pchtxt encounter-config route)?
3. **Can the immediate-end path be converted to a normal faint+reward safely?**
   recomp tried clearing the `0x80` bit and hit a null-model crash (`0xa9c700` →
   `0x651b40`), then abandoned it in favor of the predicate override. If the
   predicate override doesn't fire for PWB, is there a third option?
4. **Is a static pchtxt even the right vehicle,** given recomp needed runtime
   conditionality? Would a small Eden-side mod / cheat-engine hook, or an
   amended PWB injected routine (which already runs custom code at `0x305A70`
   and could call the reward function itself), be cleaner?

## 10. Recommended next steps

- Continue with **memory-read tracing only**. Instrument (via the blackboard
  pattern) candidate battle-end functions — start by watching the battle object
  `[x0+0x80]` state fields (`+0x574`, `+0x584`, `+0x298`, the `+0x84` state word
  seen at `0x9F25E4`) across a KO vs a catch, to see which branch each takes.
- Trace the **virtual dispatch**: the `0xa0a0f0` thunk table forwards through
  `[x0+0x60]`; enumerating which vtable slots point there, and which fire on KO,
  should reveal the reward entry point without guessing.
- Consider having **PWB's own injected routine** (`0x305A70`, already executing
  custom code with the battle handle in registers) invoke the reward/EXP
  function directly for PWB battles — this sidesteps the static-conditionality
  problem because that code only runs for PWB battles by construction.

## 11. Safety notes for whoever continues

- Never edit `Wild Battles/pwb1.pchtxt`; keep XP work in the sibling folder.
- Overlap-check every pchtxt before deploy; snapshot the save before first boot
  with any new patch.
- Do not remove the `0x9D3BAC` `+0x4A4` early-out (null guard — crashes).
- Do not set gdbstub software breakpoints (deadlocks Eden).
- The kit zip and any downloads are untrusted: extract to their own dir, run
  their Python with `python3 -I`, keep our scripts separate.
- Per project policy: no AI-authored commits/pushes on the Eden repo.
