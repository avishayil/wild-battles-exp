# PWB wild-battle crash isolation — experiment matrix

| # | EXP mod | Tracer | Party slot 1 | Follower | Crash? | Crash PC / fault / SVC | Max state | Notes |
|---|---------|--------|--------------|----------|--------|------------------------|-----------|-------|
| 0 | on | trace4 | partner (Pikachu) | ? | YES | nnSdk+0xd9838 / read@0xd0 / svc0x1C WaitProcessWideKeyAtomic | 0 | pre-isolation run (2026-10-29 15:48); one state=0 sample then crash |
| 1 | OFF | none | partner (Pikachu) | yes | **NO** | — (benign surface.cpp format asserts only) | full battle: menu→3 moves→KO→catch menu | STABLE. Contradicts follower hypothesis; implicates tracer. |
| 2 | OFF | none | non-partner | yes | SKIPPED | — | — | unnecessary: run 1 (partner-first) already stable ⇒ follower hypothesis contradicted |
| 3 | on | trace5 (safe scratch) | partner | yes | YES | nnSdk+0xd9838 / @0xd0 / svc0x1C | 0 (calls=1) | IDENTICAL crash to trace4 ⇒ scratch location irrelevant |
| 4 | on | **no-op hook** | partner | yes | YES | nnSdk+0xd9838 / @0xd0 / svc0x1C | n/a | detour-only, functionally == vanilla ⇒ **the 0x28BD20 hook itself is fatal** |

## Root cause (static, confirmed)
trace4 scratch `beluga+0x1956830` is **mid-.bss** (.bss=0x160c030..0x1ee1000) = live game globals. Our 0x20-byte writes corrupt game state ⇒ condvar/mutex crash (svc0x1C fault@0xd0). Earlier tracers used `0x1EE0F00` = .bss TAIL (last 0x100 bytes, safe). Fix = trace5: trace4 logic + scratch back to the .bss tail.

## DECISIVE CONCLUSION
Any detour-hook at `0x28BD20` (per-frame battle-event update) deterministically crashes PWB wild battles on this Eden build (`de7e6e01d4`), even a no-op. Crash = Eden condvar-HLE null-deref `@0xd0` on a SIBLING thread (0x50), from the detour perturbing battle-init thread sync — NOT cave content. Baseline (no hook) is stable. ⇒ (a) hook-based tracing at 0x28BD20 is dead; use hook-free gdbstub observation. (b) the recomp-style per-frame `+0x574&0x80` clear is likely not viable via pchtxt here; prefer injecting from battle SETUP (PWB hooks 0x305A70 safely) or another non-per-frame point.

## N1 (gdbstub OFF, no-op hook, async GPU on, frame_gen 2)
CRASH. Party = partner Pikachu first (user-confirmed; the bird in the screenshot was the WILD Pidgey encountered, not a follower). Same party order as the STABLE baseline ⇒ party order is constant across all runs; the hook is the sole variable. (recomp #6 follower hypothesis already contradicted by the stable baseline, which was also Pikachu-first.) gdbstub exonerated (crashes with it OFF). Without gdbstub, Eden logs-and-continues: Write32@0xd0=2, Write32@0xb8, Read64@0x2100000048, Read64@0x10, then PC->0x0. Same 0xd0 object corruption, more fully expressed. Backtrace (post-cascade) beluga offsets 0x2F8E1C/0x2F77D8/0x315248/0x13D290/0x13C9EC/0x2328C/0x20F78/0x22D48 + nnSdk 0xAF8F8/0xB3C58 (condvar area).

## N2 (gdbstub OFF, no-op hook, async GPU OFF, frame_gen 1)
CRASH — IDENTICAL signature to N1: Write32@0xd0=2, Write32@0xb8, Read64@0x2100000048, Read64@0x10, PC->0. Only the ASLR ptr value at 0xb8 differs (0x647ad4b8 vs 0x643b05a8). ⇒ async-GPU/frame-gen threading NOT the mechanism. KEY: the crash is DETERMINISTIC (identical fault addresses across independent launches + settings) ⇒ argues AGAINST a nondeterministic scheduler race, FOR a deterministic corruption. A SINGLE detour at the state-0 battle-event entry (fires during battle INIT) reliably nulls an object the sync path later derefs. ⇒ fragile window = battle init. NEXT: hook the STATE-4 handler (post-init) instead of the per-frame entry 0x28BD20.
(Eden reverted async->true/framegen->2 in config on exit, but they were applied at boot; identical crash confirms irrelevance.)

## N3 — STATE-4 HOOK (0x28BF34), entry 0x28BD20 left vanilla — **NO CRASH** ✅
Reached the command menu (=state 4, hook fires) with no crash; Eden healthy ~53% CPU, 0 unmapped-access log lines. BREAKTHROUGH: hooking the battle-event function AFTER init is safe; only the state-0 ENTRY hook (0x28BD20, during init) is fatal. ⇒ the fragile window is battle INIT, and we can inject the +0x574 flag-clear at state 4 (recomp's exact point). CONFIRMED stable through a full fight (hit -> fainted -> ran away), 0 crash lines. State-4 hook is behavior-preserving (no-op) and stable end-to-end. Reviewer bar MET: 3 independent wild battles with the state-4 hook, all clean (full fight+faint+run, plus 2 more incl. a mid-battle run). 0 crash lines total. State-4 hook = deterministically STABLE.

## *** ROOT CAUSE (definitive, overturns the timing theory) ***
Runtime gdbstub reads prove: a pchtxt record at address P patches MEMORY OFFSET P-0x100
(pchtxt addresses include the NSO 0x100 header). Confirmed 4x:
 - PWB pchtxt 0x28BF84 (28018052) -> mem 0x28BE84
 - PWB routine pchtxt 0x305A70 (FD7BBBA9) -> mem 0x305970
 - our hook pchtxt 0x28BF34 (1d9b2a14) -> mem 0x28BE34
 - our cave pchtxt 0xD32BA8 -> mem 0xD32AA8
Our static analysis used disasm offset AS the pchtxt addr (0x100 too low), so:
 - the cave (pchtxt 0xD32BA8) landed at mem 0xD32AA8 = a LIVE code veneer (adrp/ldr/add/br),
   OVERWRITING it. When the game called that veneer during battle -> ran our cave -> crash.
 => ALL the "detour crashes" were self-inflicted code corruption, NOT an Eden condvar/timing
    race. The condvar @0xd0 fault was the downstream symptom of the smashed veneer.
FIX: emit every pchtxt record address = mem_offset + 0x100. Cave then lands in true padding
(mem 0xD32BA8, confirmed zeros); hooks land on the intended instruction. Rebuilt
patches/pwb1_trace_s4.pchtxt accordingly (hook pchtxt 0x28C034, cave pchtxt 0xD32CA8).
Also invalidates the earlier "state-4 hook is safe/unsafe" and "entry hook fatal" results:
they used the wrong addresses. Must re-test with corrected addressing.

## *** SUCCESS (corrected addressing) — state-4 tracer, 2026-10-29 ~17:37 ***
Patch verified in guest memory: hook 1d9b2a14 @mem 0x28BF34, cave @mem 0xD32BA8, veneer
@mem 0xD32AA8 INTACT. Full battle (encounter->KO->run) NO CRASH; hook fired count=542 (per-frame
at menu), stable. => hooking the battle-event state-4 handler is SAFE; prior crashes were purely
the mis-addressed cave smashing the 0xD32AA8 veneer.
Captured at state=4 in a PWB wild battle:
  [evt+0x68]  = 4           (state 4 = command menu)
  [evt+0x574] = 0x00000080  => legendary INSTANT-END flag 0x80 is SET (recomp's target to clear)
  [evt+0x298] = 0x3f800000  => float 1.0 (ratio/timer; NOT a PWB marker)
  [evt+0x735] = 1           => byte, discriminator candidate (need non-PWB battle to confirm)
NEXT: (1) build the real fix = clear [evt+0x574]&=~0x80 at state 4, gated to PWB (via +0x735 or a
setup marker), to make the wild Pokemon faint -> native EXP via predicate 0x9D8A30. (2) port the
model-joint guard (recomp) to avoid the faint-animation null-model crash. (3) confirm XP awarded,
no double-XP, and real legendaries/trainers unaffected. Remember: pchtxt addr = mem + 0x100.

## *** PoC A RESULT — FAINT CONFIRMED (2026-10-29 ~17:58) ***
CLEAR_CNT=1 (flag [evt+0x574]&0x80 cleared exactly once at state 4, menu-gated). In-game: the
wild Rattata PLAYED THE FAINT ANIMATION (screenshot: lying down, eyes closed; MATCH TIME timer
still running) -> clearing 0x80 routes a PWB wild KO into the native FAINT path. Core architecture
VALIDATED.
Then a NEW post-faint crash (NOT the old veneer crash; veneer intact):
  Unmapped Read64 @ 0x360 and @ 0x368 ; x0=0x0 (NULL object)
  pc=nnSdk+0xd9828 (svc trampoline) lr=nnSdk+0xb51cc
  backtrace: nnSdk+0xac694 / beluga+0x21008 / +0x1f8d4 / +0x393d0 / +0x39344 / +0x4900 / nnSdk+0x849bc / nnrtld+0xac
  (generic nn::os thread-wait framework; a thread derefs [null+0x360])
Since the faint ANIMATION rendered (model present), this is likely NOT recomp's model-joint guard
but the POST-FAINT result/reward transition hitting objects PWB never created. recomp's remaining
mechanisms: (B) force XP-eligibility predicate 0x9D8A30=true for PWB; (D) rewrite result
[evt+0x720]->[+0x68]->[+0x508] from 1 to 3 at state==5 ("fainted, no capture"); (C) model-joint
guard if needed. NEXT: investigate the post-faint null@0x360 (which fn/object), then implement B/D.

## *** DIAGNOSTIC (diagD) — decision-gate answers (2026-10-29 ~18:10) ***
PoC A active (CLEAR_CNT=1, Rattata fainted). Captured up to the crash:
  last_state = 4 ; states seen = {0,1,2,3,4}  => STATE 5 NOT REACHED (stuck at state 4)
  result chain VALID: [evt+0x720]=0x21b1bdf5c0 -> [+0x68]=0x21b1bdb790 -> [+0x508] result = 1
  PRED_cnt = 1  => native XP-eligibility predicate 0x9D8A30 DID FIRE (reward path reached!)
  entry_cnt climbs (battle-event loops at state 4); clear_cnt=1
Crash (unchanged signature): svc 0x1A ArbitrateLock on a NULL object, x0=0, reads [null+0x360]/[+0x368];
  thread 0x50; pc=nnSdk+0xd9828 lr=nnSdk+0xb51cc; stack nnSdk+0xac694/beluga+0x21008/+0x1f8d4/+0x393d0/+0x39344/+0x4900/nnSdk/nnrtld.
DECISION GATE: crash is BEFORE state 5 => state-5 result rewrite (PoC D) is PREMATURE/unreachable.
  The faint-completion path (thread 0x50) locks a null object's mutex (+0x360). This is the
  missing-resource/model territory (PoC C), NOT PoC D. SEPARATELY: predicate fired (PRED_cnt=1),
  so native XP eligibility is already reached - isolate the reward independently later.
NEXT: find what object thread 0x50 locks (null +0x360) in the faint-completion, and why it's null
  in a PWB wild battle (recomp's model_joint_hook guards a missing model/joint here; Eevee 0xa9c700,
  Pikachu equivalent reads +0x1e0/+0x1e8/+0x192 - TBD). result stays 1 (not 3) because state 5 never runs.

## Isolation test: TRAINER battle (2026-10-30 ~01:05, catch-variant build = hooks A/C/A2 active)
Fully vanilla in-game: normal KOs, faint animations, XP, victory dialogue. Counters untouched:
clear=0 (hook A never fired — instant-end flag not present in trainer battles), guard=0 (model
guard passed through), 0 crashes. A2 bypass moot (trainer battles have +0x4A4==0 natively).
=> First hard evidence of trainer-battle isolation. Remaining isolation: real legendary, scripted.

## OPEN ISSUE (deferred, 2026-10-30 ~01:10): PP not preserved between PWB wild battles
User report: ThunderShock always back at 30/30 PP from fight to fight, no Pokemon Center visit
(observed under the catch variant). Likely BASE-PWB limitation: PWB synthesizes battles from the
special/legendary system; the full end-of-battle write-back that persists PP in trainer battles may
never run (the reflect fn 0x9E41D0 writes back HP/EXP/status only — PP not in its field list; and
none of our hooks touch PP). TRIAGE PLAN: (1) user checks whether player HP persists after a
damaging battle (HP persists+PP resets => base-PWB; HP resets too => no write-back at all);
(2) attribution test under base PWB only (2 battles, watch PP). Handle after A4.

## *** A4 EVOLUTION — PASS (2026-10-30 ~02:03) ***
Finding: after-battle processor entry mem 0x319A60 (Eevee 0x319BC0 − 0x160); its state-0 handler
reads the battle result [bd+0x508]: result==1 -> state 3, else -> state 4 (evolution SKIPPED).
Our A3 result=3 therefore skipped evolution (Caterpie reached L7, no evolution).
Fix (A4): hook the next-state write 0x319EC4 (str w8,[x19,#0x68]); when evolve_pending (+0xFF,
set only by A3's verified-KO rewrite) && w8==4 -> w8=1 (the native evolution-check state); one-shot
clear; +0xFF zeroed by the existing state-0 reset.
Test: reloaded L6 Caterpie save, leveled 6->7 purely on wild-KO EXP -> native evolution cutscene ->
METAPOD (screenshot). Battles still end faint->EXP->auto-exit. 0 crashes.
Also: PP/HP persistence re-checked under hardened build: BOTH persist correctly between battles ->
earlier PP report could not be reproduced; downgraded (recheck once more pre-release).

## Regression matrix status (2026-10-30 ~02:10, v0.3.0-alpha)
| Test | Status |
|---|---|
| Ordinary wild KO (XP, auto-exit) | PASS (many, incl. 2-KO+flee matrix) |
| Flee (no XP-rewrite, vanilla end) | PASS (HP gate blocked rewrite) |
| Trainer battle isolation | PASS (no hook fires, fully vanilla) |
| Evolution on KO level-up (A4) | PASS (Caterpie 6->7 -> Metapod) |
| Consecutive encounters / one-shot reset | PASS (REWRITE_CNT per-battle, flags re-arm) |
| Catch variant: intentional catching | PASS (Caterpie caught under catch build) |
| PP/HP persistence between battles | PASS under v0.3 (earlier PP report not reproduced) |
| Multi-species HP capture | PARTIAL (Pidgey confirmed; more species advisable) |
| Save/reload XP persistence | PARTIAL (user save/reload mid-session OK; full pass pending) |
| **Scripted Snorlax (Route 12/16)** | **DEFERRED — unreachable in early-game save. OPEN RELEASE GATE** |
| **Real legendary (e.g. Zapdos)** | **DEFERRED — unreachable in early-game save. OPEN RELEASE GATE** |
