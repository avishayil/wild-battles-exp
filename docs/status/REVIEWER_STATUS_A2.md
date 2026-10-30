# Wild Battles EXP — reviewer status after A2 (2026-10-29, evening)

**Headline: the core goal works.** On Eden/macOS, with a static `.pchtxt` layered on
RicoSantos' PWB1 mod, defeating a wild Pokémon now runs the game's **native** faint →
EXP path: KO → faint animation → no crash → **"Pikachu got 12 Exp. Points!"** with
normal party XP distribution. No custom XP formula; the game's own reward code does the
work.

Working patch: `patches/pwb1_A2.pchtxt` (three coordinated hooks + the predicate bypass,
all on the `pchtxt_addr = mem + 0x100` convention). Base PWB1 mod unchanged. Save backed
up (`bak/save-20261029-175010`).

---

## The decisive root-cause correction (why earlier sessions stalled)

Every crash through the long "Eden condvar race / per-frame hook is fatal" investigation
was **one bug**: Eden's pchtxt addresses include the NSO's 0x100 header, so a record at
address `P` patches **memory `P − 0x100`**. Our static analysis used the disassembly
offset directly as the pchtxt address, so the code cave was landing 0x100 low — on a live
veneer at mem `0xD32AA8` — and smashing it. Proven by four runtime reads (PWB's own
`0x28BF84→mem 0x28BE84`, routine `0x305A70→mem 0x305970`, our hook/cave). After correcting
to `pchtxt = mem + 0x100`, hooking the per-frame battle-event function is completely
stable (500+ invocations, zero crashes). The scheduler-race theory was an artifact.

**Process fix adopted:** we now verify every patch is actually in guest memory (gdbstub
read at the intended mem offset) before trusting any run.

---

## The three mechanisms (all confirmed in-game)

| PoC | Hook (mem) | What it does | Confirmed |
|---|---|---|---|
| **A** | `0x28BF34` (state-4 handler) | Clears legendary instant-end flag `[evt+0x574] &= ~0x80` once the command menu is up (gated on `[x1+0x60]!=null`), so a wild KO **faints** instead of instant-ending | Rattata faints; `clear_cnt=1` |
| **C** | `0xA9C650` (model-joint fn = recomp Eevee `0xa9c700`) | recomp's model-joint guard: returns `x0=0` (no-joint) when the model is present but its resources are missing (`model!=0 && +0x1e0==0 && !(+0x192 && +0x1e8)`), else runs original | Post-faint `@0x360` crash gone; `guard_hit>0` |
| **A2** | `0x9D8A44` (in eligibility predicate `0x9D8A30`) | Bypasses the predicate's `+0x4A4` gate (`cbz → b 0x9d8a58`) so its **existing flags check** decides eligibility | Predicate returns 1; XP awarded |

### Why A2 is a principled discriminator, not a hack
Step-1 instrumentation showed the predicate failed **only** on `[setup+0x4A4]==1` (`kind=0`,
`flags=0` both already passed). Normal XP-eligible battles have `+0x4A4==0`; PWB has `==1`.
Bypassing that gate lets the predicate's **own flags check** run, which denies static
encounters (`flags` bit `0x80`) and `0x800` — i.e. **real legendaries stay ineligible**
(static, flags set) while PWB wild battles (flags `0`) become eligible. So legendary
exclusion is structural, via the game's own flag, not a guessed marker.

The downstream amount function (`0x9D3BA0`, with its own `+0x4A4` early-out) was **not** a
blocker — it computed a real 12 EXP. We did **not** touch its null guard.

---

## Instrumentation evidence (final run)
```
states=[0 1 2 3 4 5] STATE5!  result=1
clear=1  guard=2  pred_cnt=1
kind=0  +0x4a4=1  flags=0x0  => PRED_RET=1
0 crash lines; Eden healthy
In-game: "Pikachu got 12 Exp. Points!" + party XP distribution
```
Full detail in `work/pocC_investigation.md`; experiment matrix in
`work/experiment_matrix.md`.

---

## What remains

1. **A3 — skip the catch sequence (next).** After a KO the result field is still `1`, so
   the catch menu still appears (you must Run Away to finish). recomp rewrites the result
   chain `[evt+0x720]→[+0x68]→[+0x508]` from `1` to `3` ("fainted, no capture") at
   `state==5`. State 5 is now confirmed reachable and the pointer chain is valid, so this
   is an isolated change. Plan: gate on `state==5 && result==1 && wild HP==0 &&
   once-per-encounter`, per recomp, preserving flee/scripted/intentional-catch.
2. **A4 / regression.** Level-ups and evolution after a KO-induced level; repeated wild
   encounters; exact XP across levels; and **validate that trainers, real legendaries,
   intentional captures and fleeing are unaffected** (the flags-based legendary exclusion
   needs a real legendary test).
3. **Scope / discriminator.** A2 relies on the predicate's flags check for legendary
   exclusion rather than a PWB-only marker. This is principled but **unvalidated against
   an actual legendary battle** — must be tested before the patch is considered safe for
   general play. Until then the patch is marked unsafe for scripted encounters.

## Open questions for the reviewer
- Agree A3 is the right next step, with the `state==5 && result==1 && HP==0 && once`
  gating? Any additional condition recomp uses that we should mirror?
- Is the flags-check legendary exclusion acceptable as the discriminator, pending a
  legendary regression test, or do you want an explicit PWB marker wired in first?
- Anything in recomp's `after_battle_hook` (evolution path) we should pre-empt before A3,
  or handle only if A4 surfaces an issue?

## Constraints still honored
Base PWB1 unchanged; separate reversible patch; `pchtxt = mem + 0x100` on every record
with overlap + disassembly verification; save backups; memory-read gdbstub only (no
breakpoints); no AI app-launch (user launches Eden); amount/`+0x4A4` null guard untouched.
