# PoC C static investigation — post-faint crash (2026-10-29 ~18:15)

## Confirmed facts
- Fault halts at nnSdk svc trampoline, `ret` after **svc #0x1A = ArbitrateLock**
  (thread 0x50). Per switchbrew: ArbitrateLock(W0=owner thread_handle, X1=mutex addr, W2=self tag).
- Registers at halt: **x0(handle)=0**, **x1(mutex addr)=0x21640e46a8**, **x2(tag)=0x81ff**,
  x19=x1. mem[x1] = `ff810000 00000000 01000000 ...` -> mutex word = **0x81ff** (owner tag,
  no waiters bit). The mutex object is VALID and mapped.
- Eden's lock-wait path (`KConditionVariable::WaitForAddress`, k_condition_variable.cpp) only
  reads the tag at `addr`(=x1, valid) and EARLY-RETURNS here (test_tag 0x81ff !=
  (handle 0 | HandleWaitMask 0x40000000)). **It never reads `@0x360`.**
  => The `Unmapped Read64 @0x360/@0x368` is NOT produced by the ArbitrateLock HLE.

## Guest call chain of thread 0x50 (identical across all crashes)
  beluga+0x39340  blr x8        ; vtable dispatch: x8=[x19]; x8=[x8+0x18]; call method of obj x19
  ...-> beluga+0x393cc bl ...    ; nested
  ...-> beluga+0x1f8d0 bl ...
  ...-> beluga+0x20ffc add x20,x19,#0x310 ; mov x0,x20 ; bl <lock fn>  -> locks mutex at [obj+0x310]
  ...-> nnSdk lock -> svc 0x1A ArbitrateLock(handle=0, addr=obj+0x310, tag=0x81ff)
  (the object x19 differs per frame; deepest-frame obj's mutex is at +0x310 = x1)

## CORRECTION (reviewer): x0=0 is the RESULT CODE, not the input handle
- Registers were captured at the `ret` AFTER svc; ArbitrateLock returns its result in W0, so
  x0=0 = ResultSuccess. The original input handle (W0) is NOT recoverable post-svc. The earlier
  "handle=0 / inconsistent mutex bookkeeping" hypothesis is WITHDRAWN. The lock most likely
  SUCCEEDED, which shifts suspicion to the instruction(s) AFTER the lock returns.

## What this REFUTES
- The `@0x360/@0x368` offsets do NOT match recomp's model_joint fields (+0x192/+0x1e0/+0x1e8).
  => recomp's model-joint guard is most likely NOT the fix for this crash (reviewer's caution
  confirmed). Do not port it on symptom similarity.

## Still unresolved
- The exact instruction that reads `[null+0x360]` is not pinned: the svc-trampoline halt PC
  obscures whether it is a guest LDP `[xN,#0x360]` with xN=null or an Eden HLE read. Memory-read-
  only inspection through the svc PC cannot settle this.

## Proposed next step (targeted instrumentation, not a blind patch)
- Keep PoC A. Add a read-only tracer hook at the thread-0x50 vtable-dispatch site
  (beluga+0x39334: `ldr x8,[x19]; ldr x8,[x8,#0x18]; blr x8`) to log the object pointer x19 and
  its validity each call, and at the lock-caller (beluga+0x20ffc, obj x19 whose +0x310 is locked),
  to capture the object as it transitions toward the null/handle=0 state during faint-completion.
  This finds WHERE the object becomes invalid, which blind register inspection cannot.
- Do NOT implement PoC D (state 5 unreached) or the model-joint guard (offsets don't match) yet.

## UPDATE 2 (object tracers + static @0x360 search) — crash NOT pinned
- Object tracers at beluga+0x39334 (dispatch) and +0x20FFC (lock): objects are VALID and counts
  are HUGE (dispatch cnt~1900, lock cnt~57000) and KEEP CLIMBING AFTER the crash log. => these
  backtrace sites are high-frequency GENERIC worker paths, NOT the crash site. gdbstub 'g'/backtrace
  has been showing a NON-crashing parked thread (0x50 at a lock), not the faulting thread.
- Static search for the faulting access: the only `ldr [reg,#0x360]`+`[reg,#0x368]` pairs in .text
  (5 sites: 0x2466C,0x4F0814,0x4F1294,0xCE9914,0xCEAA50) are ALL adrp-GLOBAL based (base = adrp
  0x15fb000/0x1601000/0x1610000) -> they read @0x16xx360, NOT @0x360. And `ldp [reg,#0x360]` is
  impossible (0x360/8=0x6C exceeds the signed 7-bit ldp offset range +-63). => the @0x360/@0x368
  fault is NOT a static null-base load; it's a dynamic pointer-chain deref or an Eden HLE read,
  which memory-read-only gdbstub tooling cannot cheaply localize.
- CONCLUSION: pinning this crash to an exact instruction has hit diminishing returns with the
  available tools (no breakpoints; gdbstub shows wrong thread; fault not statically locatable).

## What IS solid
- Clearing [evt+0x574]&0x80 at state 4 -> wild Pokemon FAINTS (visual, repeatable).
- XP-eligibility predicate 0x9D8A30 FIRES once in that sequence (pred_cnt=1).
- Battle-event state stalls at 4 (never reaches 5); result chain valid, result=1.
- The crash is a separate post-faint fault on an unidentified thread; model-joint guard refuted.

## Options for the GOAL (not just this crash)
A. Accept that forcing a faint hits uninitialized PWB faint-completion resources; port recomp's
   FULL coordinated set (flag-clear + state-5 result 1->3 + after-battle handling + model guard)
   together, matching recomp wildbattle.c, rather than one-at-a-time — recomp needs them jointly.
B. Avoid the fragile faint entirely: the catch-phase reward sequence (0xA58Axx) already runs on a
   PWB KO (KO -> catch menu). Inject XP there (award EXP for the defeated mon) WITHOUT forcing a
   faint. Keeps the vanilla PWB end-of-battle flow; sidesteps the faint-completion crash.
C. Different crash-capture technique (e.g., instrument the actual faulting thread by hooking the
   battle-end/faint-completion functions specifically, or build an Eden debug build that prints
   the faulting PC+thread) — higher effort.

## MODEL-JOINT FUNCTION LOCATED: mem 0xA9C650 (Pikachu 1.0.2 == recomp Eevee 0xa9c700)
Structural match to recomp's model_joint: entry 0xA9C650 (sub sp,#0x70), arg0(x0)->x21=model,
arg1(x1)->x19. Reads R8(model,0x192)@0xA9C670, R64(model,0x1e8)@0xA9C67C, [+0x1e8+0x54] ldar,
then [model+0xe0]->[+0x420]. Two tails: "proceed" (0xA9C690, uses +0x1e8 resource) and "safe"
(0xA9C790, uses +0x1e0 resource); both do `ldr x8,[x0,#0x48]!; ldr x8,[x8,#0x10]; blr x8` virtual
calls on the resource object. Function does NOT read +0x360 -> consistent with recomp's note that a
missing resource PROPAGATES to a later deref (the @0x360 crash is downstream). recomp's guard is
MORE aggressive than the fn's own checks: when model present but +0x1e8 resource absent (and +0x1e0
not set) it sets result=no-joint(0) and SKIPS the function; the fn's internal safe-path still
processes +0x1e0. A1 step1 (this experiment): instrument 0xA9C650 entry during the PWB faint to
confirm it IS called with a missing-resource model, BEFORE porting the guard. Discriminator for PWB
still unresolved (reviewer: don't assume +0x735); recomp uses g_active.

## *** PoC C RESULT — CRASH FIXED (2026-10-29 ~19:02) ***
Model-joint guard @0xA9C650 deployed (patches/pwb1_pocC.pchtxt) + PoC A flag-clear.
In-game: encounter -> KO -> faint -> ~2s black screen -> CATCH SEQUENCE (get ready/bag/help/run).
NO CRASH (0 crash lines), Eden healthy. GUARD_HIT=4 (guard intercepted resource-less model-joint
lookups), clear=2. => recomp's model_joint guard PORTS CORRECTLY and resolves the post-faint
@0x360 crash (a missing-resource propagation, exactly as recomp documented). The faint lifecycle
now completes.
REMAINING: the battle still routes to the CATCH sequence (PWB default) instead of ending as
"fainted, no capture" + awarding XP. Next: (A3/PoC D) recomp's result rewrite [evt+0x720]->[+0x68]
->[+0x508] 1->3 at state==5 to skip the mandatory capture; (A2/PoC B) confirm/enable native XP.
State 5 should now be REACHABLE (crash gone) -> PoC D now applicable. Re-add state tracer to confirm.

## *** STEP 1 RESULTS (2026-10-29 ~19:11) — state 5 reached; XP gate identified ***
With PoC A + C (stable faint, no crash):
- STATES REACHED = {0,1,2,3,4,5}  => STATE 5 IS NOW REACHED. result chain value = 1.
  => PoC D (result 1->3 at state 5) is now APPLICABLE (crash previously blocked state 5).
- XP predicate 0x9D8A30: inputs kind=0, [setup+0x4A4]=1, flags(+0x494)=0x0 => RETURNS 0.
  The ONLY failing condition is [setup+0x4A4]=1 (predicate requires +0x4A4==0; the 0x9D8A44
  `cbz w9,#0x9d8a58` falls through to `mov w0,0; ret` at 0x9D8A48). kind<=1 OK, flags bit7/0x800
  clear OK. => native XP is gated OFF solely by +0x4A4. Normal XP battles have +0x4A4==0; PWB=1.
- guard=2 (model guard fired), no crash.
A2 PLAN: make the predicate proceed to the flags check despite +0x4A4!=0. Minimal: change 0x9D8A44
  `cbz w9,#0x9d8a58` -> unconditional `b #0x9d8a58`. Then the EXISTING flags check (bit7=static-
  encounter=0x80 deny, 0x800 deny) still gates REAL legendaries (static, flags set) while PWB
  (flags=0) becomes eligible => natural PWB-vs-legendary discrimination via flags. NOTE downstream:
  AMOUNT fn 0x9D3BA0 also has a +0x4A4 early-out (amount=0 if +0x4A4!=0) — if XP still 0 after the
  predicate fix, that's the next gate (do NOT remove its null guard; needs a separate approach).

## *** A2 SUCCESS — NATIVE XP AWARDED (2026-10-29 ~19:20) — CORE GOAL ACHIEVED ***
Working stack: PoC A (flag-clear 0x28BF34) + PoC C (model guard 0xA9C650) + A2 (predicate
+0x4A4-gate bypass @0x9D8A44: cbz->b 0x9d8a58). patches/pwb1_A2.pchtxt.
Result: wild encounter -> KO -> faint -> NO CRASH -> **"Pikachu got 12 Exp. Points!"** (measured amount from the native formula) + party XP distribution ("party pokemon want exp too").
Trace: PRED_RET=1 (predicate now eligible for PWB), state 5 reached, result=1, guard=2, 0 crashes.
The downstream AMOUNT fn +0x4A4 early-out was NOT a blocker (XP > 0). So: DEFEAT WILD POKEMON ->
EARN XP works. flags check (bit0x80 static / 0x800) still naturally gates real legendaries.
REMAINING: (A3) result rewrite [evt+0x720]->[+0x68]->[+0x508] 1->3 at state==5 to skip the catch
sequence (currently result=1 -> catch menu still appears after KO); (A4) level-up/evolution,
repeated encounters, PWB-vs-legendary/trainer regression, validate exact XP amount (level before/after).

## *** A3 SUCCESS — FULL FLOW COMPLETE (2026-10-29 ~23:38) ***
patches/pwb1_A3.pchtxt = A (flag-clear+arm) + C (model guard) + entry-hook (reset flags@state0;
rewrite result [r68+0x508] 1->3 @state5 when armed & result==1 & !done) + A2 bypass.
In-game: KO -> faint -> native EXP -> **returned to the overworld immediately (NO catch screen)**.
Trace: result 1 -> 3 at state 5, REWRITE_CNT=1, done=1 (one-shot), states advanced 0..12 (battle
completed), NO CRASH. Next encounter: armed reset to 1, done=0, result=1 again -> per-encounter
one-shot RESET verified (re-arms cleanly). guard=2.
=> FULL GAMEPLAY LOOP WORKS: fight wild Pokemon -> defeat -> earn native XP -> return to exploration,
no catch, no crash. Core mod objective COMPLETE.
REMAINING (hardening, not core): A4 evolution (test a KO that hits evo level; port recomp after_battle
state 4->1 if it doesn't trigger); regression (trainers, real legendary, intentional catch, flee,
repeated encounters, save/reload XP retention); strengthen PWB discriminator (A2 bypass is global +
flags-gated; A3 armed-gated — validate vs a real legendary before release). HP==0 check still deferred
(proxy = armed + result==1).
