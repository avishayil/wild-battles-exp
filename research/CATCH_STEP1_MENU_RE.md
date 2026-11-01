# v0.7 step-1 — battle command-menu RE (offline go/no-go)

Status: **offline disassembly complete, no emulator.** Resolves unresolved question #1 of
`docs/CATCH_FEASIBILITY_V070.md` ("can a static cave hook observe which battle command button was
pressed and set a scratch flag, zero false positives?").

**Verdict: GO for *detection*.** A static cave hook can read the canonical chosen-button id and
gate it to our wild battles. **NO-GO for a *distinct 5th CATCH button* as a static patch** — that
needs per-allocation runtime wiring a `.pchtxt` cannot do. Consequence: a static minimal slice must
*repurpose an existing button* (most naturally RUN), not add one; that is a product decision for the
owner, carried to step-2.

All addresses are PK **1.0.2** NSO memory offsets, read from `work/text.bin`
(`tools/disasm.py`); `pchtxt = mem + 0x100`.

---

## 1. The command-menu decision path in 1.0.2 (confirmed)

recomp (Eevee 1.0.0) models the menu as: each button stores a decide callback at `[button+0x150]`
and `{view,event}` at `[+0x170]`; on a press the callback writes `{type=1, id}` to the menu event
(`views+0x270`), and `CMD_DECIDE` dispatches on `id` (1..7). Every piece of that survives into
1.0.2, instruction-matched:

**Invoke callbacks that write `{1,id}` to the event** (`BUTTON_INVOKE` family, Eevee `0xab49f0`):
```
0xab49c0: ldr x8,[x0]; mov w9,#1; str w9,[x8]      ; event.type = 1
0xab49cc: ldr x8,[x0]; mov w9,#5; str w9,[x8,#4]   ; event.id   = 5
0xab49f0: ldr x8,[x0]; str x8,[x1]; ret            ; (accessor)
0xab4a10: ... str #1,[x8]; str #6,[x8,#4]          ; event.id   = 6
```
→ the event is `{u32 type, u32 id}`, `id` at `+4`. Exactly recomp's model.

**`CMD_DECIDE` (1.0.2 entry `0xab1dd0`, Eevee `0xab1e80` — body shifted +0x10):**
```
0xab1e28: ldr x8,[x22,#0x250]; ldr x8,[x8,#0x10]; blr x8   ; read the menu event record -> x0
0xab1e34: ldr w20,[x0,#4]          ; *** w20 = chosen-button id (event+4) ***
0xab1e38: cmp w20,#6; b.ne 0xab1e88 ; id==6 diverts to the move-select block (0xab1e40)
0xab1e90: sub w8,w20,#1; cmp #6; b.hi 0xab1ff4   ; id-1 in 0..6 ? else drop
0xab1e9c: adrp x9,#0xf98000; add x9,#0x23c        ; jump table @ mem 0xf9823c
0xab1ea4: ldrsw x8,[x9,x8,lsl#2]; add x8,x8,x9; br x8   ; 7-way switch on id
```

**Jump table @ `0xf9823c` → in-function handlers**, each writing an *action code* to `[x21+0x10]`
(recomp's `act+0x10`):

| event id | handler | action written to `[x21+0x10]` | note |
|---|---|---|---|
| 1 | `0xab1eb0` | **1** | |
| 2 | `0xab1fb0` | **2** | |
| 3 | `0xab1fb8` | **3** | |
| 4 | `0xab1fc0` | **4** | matches recomp's RUN action value (4) |
| 5 | `0xab1fc8` | clears `[x21+0x10]`, sets `[frame+0x184]=1` | special |
| 6 | (diverted at `0xab1e38` → `0xab1e40`) | move/attack select (`blr`, model setup) | tbl[5]=`0xab1ff4` is dead |
| 7 | `0xab1fe8` | **0xA (10)** | |

So the chosen button is observable at **two** fixed, canonical sites: the raw id in `w20` at
`0xab1e34`, and the action code at `[x21+0x10]` once a handler runs. Both are the game's own values,
written only on an actual press of the corresponding button.

---

## 2. The gate is reachable from here (the question that actually decided it)

The worry was that `CMD_DECIDE` is a uikit function far from the battle-event code we normally hook,
so it couldn't tell a PWB wild battle from a trainer/2-player one — and repurposing a button in
*all* battles would be unacceptable.

Resolved: **`pwb_encounter` is scratch `+0xF8`** — an *absolute* byte in the module's `.bss`-tail
scratch page (`module+0x1EE0F00+0xF8`), set by HOOK_M (`cave_M`) at PWB encounter start and cleared
by `cave_E` after each battle (`tools/build_patch.py`). It is **not** an `evt` field, so it does not
depend on the local object graph. Every existing cave reads it with the same PC-relative
`ADRP_SCRATCH` (`adrp x16,#0x1EE0000; add x16,#0xf00; ldrb w17,[x16,#0xF8]`) — and that sequence is
relative to the **cave page (`0xD32xxx`)**, where a `CMD_DECIDE` hook would trampoline. So a cave hook
invoked from `0xab1e34` reads the identical global flag with the identical constant. **The PWB-active
gate works verbatim from the menu context.**

---

## 3. Proposed static detection hook (fits the budget)

- **Site:** displace one instruction at `0xab1e34`/`0xab1e38` (after `ldr w20,[x0,#4]`, before the
  dispatch) and trampoline to a new `cave_MENU`. `w20` is live into the dispatch, so the cave must
  preserve it (standard save/restore).
- **Cave body (~12–16 instr, well within the ~428 B free):** `ADRP_SCRATCH` → `ldrb w17,[x16,#0xF8]`;
  if `pwb_encounter==0` → restore and run the displaced original (no effect outside PWB). Else
  compare `w20` to the target id; if equal, `strb` a new `menu_choice` byte to scratch (propose
  `+0xFB`, currently free — confirm against the slot map in `build_patch.py` at build time). Restore
  regs, run the displaced original, return.
- **Zero false positives:** the flag is written only when (a) a PWB wild battle is active and
  (b) the game's own id equals the target. Trainer/2-player/overworld menus never set
  `pwb_encounter`, so they never trip it. This is the same isolation discipline as every existing
  hook.

**Pass criterion (met in principle, pending one live confirmation):** a scratch byte is set iff a
specific command button is chosen in a PWB wild battle, and never otherwise. The *code path* to do
this is proven offline; the single live confirmation below is a measurement, not a feasibility risk.

---

## 4. The 5th-button wall (why detection ≠ the recomp feature)

recomp's CATCH button is a **runtime** construct: `views_hook` finds the injected button by hash,
then writes callback pointers into `[button+0x150..0x178]` and points it at a hand-crafted view with
pattern frame 5 → id 0 (`g_catch_view`), which `CMD_DECIDE`'s 1..7 switch ignores, and `decide_hook`
turns into RUN. A `.pchtxt` **cannot** allocate that view or write per-instance callback pointers —
those are per-allocation C writes. LayeredFS can serve the button *art* but cannot bind its
*behavior*, and an injected button with no valid callback/view would at best produce an
already-used id (not a distinguishable "CATCH").

Therefore a static minimal slice cannot add a 5th button. It must **repurpose an existing one** — the
natural choice is RUN (id→action 4): in a PWB wild battle, detect the RUN press (§3), set the flag,
and let step-2's result-gate flip `[+0x508] 3→1` so RUN routes to the native capture instead of
fleeing. Cost: you can no longer *flee* a PWB wild battle. That is a product/UX call for the owner,
not a technical blocker, and it is the step-2 entry condition.

---

## 5. Remaining bounded follow-ups (none block the go/no-go)

1. **Pin id↔label for 1.0.2.** The id space here is richer than recomp's Eevee note (it shows
   dedicated invoke writers for ids 5 and 6, and id 6 diverts to the move-select block). Confirm
   which numeric id is RUN before wiring a RUN-gate — either by reading the handler semantics in full
   or by **one live read** (open a PWB wild menu, press each button, log `w20`/`[x21+0x10]` over the
   stub, reads-only). recomp's labeling (1 fight / 2 pokémon / 3 bag / 4 run / 7 back) is the working
   hypothesis; id4→action4 is consistent with RUN=4 but must be verified, not assumed.
2. **Confirm the free scratch slot** (`+0xFB` proposed) against the live slot map in `build_patch.py`
   and reserve it in the manifest.
3. **Step-2 (only if the owner accepts the RUN-repurpose UX):** prototype the result-gate at the
   `0x28BD20` site we already own, gated on `pwb_encounter && menu_choice`, and confirm the native
   capture screen opens on a sane wild mon — the step-2 pass/fail from the feasibility report.

## 6. Verdict
Detecting which command button was pressed, scoped to PWB wild battles, with zero false positives, is
**static-feasible** — the signal (`w20` at `0xab1e34`, or the action at `[x21+0x10]`) and the gate
(`pwb_encounter` scratch `+0xF8`, reachable from the cave) are both confirmed in 1.0.2. A **distinct
5th CATCH button is not** static-feasible. So v0.7 Integrated Catch, if pursued statically, could only
be a **RUN-repurpose** feature, not a new button.

## 7. Owner decision (2026-11-01): v0.7 Integrated Catch SHELVED
The owner declined the RUN-repurpose UX (it would remove the ability to flee a PWB wild battle) and
chose to **keep the existing Catch Variant** as the "battle-then-catch" answer. v0.7 Integrated Catch
is therefore **not being built**; this document stands as the completed static-feasibility record.

**Offline id↔label narrowing:** the main four buttons' event id is produced via the frame-indexed
table (recomp `table[view+8]`), not constant stubs; only ids 5 and 6 have constant writer stubs
(`0xab49d0`→5, `0xab4a20`→6), and the id==6 path diverts at `0xab1e38` into a battle-object
interaction consistent with FIGHT/move-select.

**Live confirmation (2026-11-01, PK 1.0.2 on Eden `de7e6e01d4-master`).** A throwaway
instrumentation patch (`tools/probe_menu.py`: cave at `0xab1e34` copies `w20` → scratch `+0x04`,
press counter `+0x00`) was deployed standalone over base PWB1 and the chosen-button id was read back
over the stub during a real wild battle:

| press (counter) | on-screen button | captured event id |
|---|---|---|
| #4 (last press) | **Run** | **4** |
| #3 | Pokémon/Bag | 3 |
| #2 | Bag/Pokémon | 2 |
| #1 | Fight | (ticked past the sampler; = 1 by elimination) |

**RUN = event id 4 → action 4, confirmed** — exactly the disassembly's prediction. This also proves
the detection mechanism end-to-end on hardware: the cave captured the id for genuine presses into
scratch and it read back live. The 2↔3 (Bag/Pokémon) labels depend on the exact press order and are
not individually pinned, but they are irrelevant to the (shelved) feature, which only needed RUN.

Capture method note (this build): a register can't be read without a breakpoint (banned), so the
patch copies the id to scratch; and the guest halts at every battle-scene stop, so the sampler had to
continuously `$c` while reading scratch at each stop (`tools/pump_and_read.py`) — a one-off throwaway,
not the read-only observer. Confirms the reviewer's read that live observation on this build needs
continuous continue-servicing.
