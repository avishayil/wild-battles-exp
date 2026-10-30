# Reproducing the mod from scratch

Audience: an engineer or coding agent who has the game files and wants to regenerate and
verify this patch end-to-end. Every address below is an **NSO memory offset**; the pchtxt
record address is `memory_offset + 0x100` (see step 2 — this is load-bearing).

## 0. Prerequisites
- A dump of **Pokémon: Let's Go, Pikachu!** base + the **v1.0.2** update, and `prod.keys`.
- `hactool` (build from source; vendors lz4+mbedtls), `python3` with `capstone`
  (`pip install capstone`), and LLVM `objdump` (Apple's `/usr/bin/objdump` works).
- An emulator with IPSwitch `.pchtxt` support and a **gdbstub** (Eden tested; port 6543).
- RicoSantos' **Wild Battles (PWB1)** `pwb1.pchtxt` (the base mod this extends).

## 1. Extract and verify the executable
```bash
HT=hactool
# unpack the v1.0.2 update NSP; the Program NCA uses titlekey crypto (ticket .tik in NSP)
$HT -k prod.keys -t pfs0 --outdir=nsp_v102 "Pokemon Lets Go Pikachu v102.nsp"
TK=$(xxd -s 0x180 -l 16 -p nsp_v102/*0007.tik | tr -d '\n')
$HT -k prod.keys --titlekey=$TK -t nca --exefsdir=exefs_v102 nsp_v102/<ProgramNCA>.nca
# MUST match build-id C208DB6A4EF4361F28B8402BE0F7CD9A... (NSO header +0x40) or ABORT:
xxd -s 0x40 -l 32 -p exefs_v102/main
# decompress the NSO and carve .text (drop the 0x100 header -> text.bin[X] == mem offset X)
$HT -k prod.keys -t nso0 --uncompressed=main_dec.bin exefs_v102/main
dd if=main_dec.bin of=text.bin bs=256 skip=1
```
NSO segment layout (from the header): `.text` fileoff `0x100`, memoff `0`, size `0xD32BA8`;
`.rodata` memoff `0xD33000`; `.bss` extends the mapping to mem `0x1EE1000`.

## 2. The address convention (verify it yourself — this is the #1 pitfall)
A pchtxt record at address `P` patches the decompressed-NSO **file** offset `P`, which is
memory offset `P − 0x100` (because of the 0x100 NSO header). Confirm against the base mod:
PWB's record `0028BF84 28018052…` must appear in the running game at **memory** offset
`0x28BE84` (not `0x28BF84`). Read it live with the gdbstub (`m <beluga_base+0x28BE84>,8`).
If you instead find it at `+0x28BF84`, your base resolution is wrong. **Build every record
address as `mem + 0x100`.** `tools/verify_convention.py` checks the related branch encoding.

## 3. Locate the hook sites (structural disassembly)
Use `tools/disasm.py text.bin <start> <end>`:
- **Battle-event update entry `0x28BD20`**: prologue `sub sp,sp,#0x70; …; mov x19,x0;
  ldr w8,[x19,#0x68]`. `x0`=event obj `evt`; state word `[evt+0x68]`; dispatch via a jump
  table. **State-4 handler `0x28BF34`**: `ldr x20,[x1,#0x60]; cbz x20,…` (`[x1+0x60]` =
  command-menu object). Instant-end flag `[evt+0x574] & 0x80`.
- **EXP predicate `0x9D8A30`**: `ldr x8,[x0,#0x80]; ldr w9,[x8]; cmp w9,#1; b.hi …;
  ldrb w9,[x8,#0x4a4]; cbz w9,#0x9d8a58; …` then flags `[x8+0x494]` bits `0x80`/`0x800`.
  `[setup+0x4A4]==1` is the only thing that denies a PWB battle. A2 hooks the **predicate
  entry** and forces eligibility only for the PWB profile (`+0x4A4==1 && +0x494==0`) *and*
  while `pwb_encounter` is set (v0.4.1); every other battle runs the original predicate —
  including its `cbz` gate at `0x9D8A44` — untouched. (v0.1–v0.3 patched that `cbz` in place;
  no longer.)
- **Model-joint fn `0xA9C650`** (recomp Eevee `0xA9C700`): entry `sub sp,sp,#0x70; … mov
  x21,x0; ldrb w8,[x21,#0x192]; cbz …; ldr x8,[x21,#0x1e8]; cbz …`. Find it by searching
  for the rare `ldrb w,[*,#0x192]` combined with `ldr x,[*,#0x1e8]`/`[*,#0x1e0]`.
- **Result chain**: `[evt+0x720] → [+0x68] → [+0x508]` (value `1` = normal/faint; set `3`
  for "fainted, no capture").
- **Code cave**: mem `0xD32BA8..0xD33000` is zero padding (page-aligned `.text` tail), RX.
- **Scratch**: mem `0x1EE0F00..0x1EE1000` (`.bss` tail) for flags/instrumentation.

## 4. Build the patch
```bash
python3 -I tools/build_patch.py \
  --text text.bin \
  --pwb  pwb1.pchtxt \
  --out-addon         wbexp_addon.pchtxt \
  --out-unified       wild_battles_exp.pchtxt \
  --out-catch-unified wild_battles_exp_catch.pchtxt
```
`build_patch.py` encodes the hooks + caves (A faint, C model-guard, ST/A3 result rewrite,
R HP-capture, E/A4 evolution, P/A2 XP, M identity marker) in memory space, emits records at
`mem + 0x100`, self-verifies with capstone (return branches, displaced originals) plus a
dataflow **stack-balance** check, merges the base PWB records for the unified builds, and runs
a pairwise **overlap** check (one intentional overlap: M's branch inside PWB's `0x305AB0`
record). It reproduces the shipped files byte-for-byte. The catch variant omits A3/A4/R.

## 5. Deploy and VERIFY IN MEMORY (don't skip)
Install the mod, enable it, boot the game, then with the gdbstub confirm the bytes landed:
```
m <beluga_base + 0x28BF34>,4   -> should be the hook branch (not the vanilla ldr)
m <beluga_base + 0xD32BA8>,8   -> should be the cave (not zeros)
m <beluga_base + 0xD32AA8>,8   -> MUST still be the original veneer (5046009011b644f9…)
```
`beluga_base` is the ASLR base of the main module; resolve it live
(`qRcmd,"get info"`). Only trust a test run after these match.

## 6. Runtime tracing (how every mechanism was confirmed)
Use `tools/scratchread.py` (gdbstub, **memory reads only**). Hook a site to a cave that
writes counters/fields into the scratch page, then poll. Examples used here:
state timeline + states-seen bitmask (does it reach state 5?), the result chain + value,
the predicate inputs (`kind`, `[setup+0x4A4]`, `flags`) to derive its return, the
model-joint entry/guard-hit counters, and the A3 rewrite counter + armed/done flags.

**Never set gdbstub software breakpoints (`Z0`)** — they deadlock Eden's JIT
(`InvalidateInstructionCacheRange → HaltExecution`), at boot and mid-game. Memory reads are
the only safe tool.

## 7. Safety
- Keep the base PWB `pwb1.pchtxt` unmodified; build the EXP parts as separate records.
- Overlap-check every record against PWB and against the other EXP records.
- Snapshot the save before testing a behavior-changing build.
- Re-verify build-id if you change game version — all addresses are build-specific.
