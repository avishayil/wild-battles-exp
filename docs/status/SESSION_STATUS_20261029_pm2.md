# Wild Battles EXP — decisive crash isolation (2026-10-29, late PM)

Follow-on to `SESSION_STATUS_20261029_pm.md`. Read that + `Wild_Battles_XP_Findings.md`
first. This records a decisive result that reframes the whole approach.

## Headline
**Any detour-hook at the per-frame battle-event function `0x28BD20` deterministically
crashes PWB wild battles on this Eden build — even a functional no-op.** The crash is
an Eden condvar-HLE null-deref (`unmapped read @0xd0`) on a *sibling* thread, caused by
the control-flow detour perturbing battle-init thread timing, NOT by anything the hook
computes. Our tracer code, the renderer, the environment, and the missing-follower
hypothesis are all **exonerated**.

## The experiment matrix that proves it (full table in `work/experiment_matrix.md`)
| Run | EXP mod / hook | Party | Result |
|---|---|---|---|
| baseline | OFF (no hook) | partner Pikachu 1st | **No crash** — full battle: menu → 3 moves → KO → catch menu |
| trace4 | hook 0x28BD20, scratch in **mid-.bss** | partner 1st | Crash `@0xd0` after 1 hook call |
| trace5 | hook 0x28BD20, scratch in **safe .bss tail** | partner 1st | **Identical** crash `@0xd0` ⇒ scratch irrelevant |
| no-op | hook 0x28BD20, cave = `sub sp,sp,#0x70; ret` only | partner 1st | **Identical** crash `@0xd0` ⇒ the hook detour itself is fatal |

All three crashing runs share the exact fault: `pc=nnSdk+0xd9838` (an `svc 0x1C`
`WaitProcessWideKeyAtomic` trampoline), `lr=nnSdk+0xb4c30`, thread `0x50`, stack
`beluga+0x21124 → +0x1f8d4 → +0x393d0 → +0x39344 → +0x4900 → nnSdk → nnrtld`. That stack
is a thread locking a mutex embedded at `[obj+0x330]` and waiting on a condvar; it does
**not** contain our hook `0x28BD20` — a different thread crashes. Details in
`work/crash_20261029_1548.txt`.

## Why this happens (and why recomp doesn't hit it)
- Baseline PWB is stable, so the PWB battle path itself is fine.
- The only change in the crashing runs is that `0x28BD20`'s first instruction becomes a
  branch to a cave (which replays the displaced `sub sp,sp,#0x70` and returns). The cave
  body is provably side-effect-free (reads only; scratch in verified-safe `.bss` tail;
  flags are re-established by the callee before any branch). The no-op proves even
  *zero* body still crashes.
- So the crash is a **timing/scheduling perturbation**: the extra branches shift when
  Eden's cooperative scheduler switches threads / services an SVC, pushing a battle-init
  condvar into a state where Eden's HLE dereferences null `+0xd0`.
- **recomp (`letsgo-recomp`) is a static recompiler**: its equivalent "hook" is a
  compile-time HLE callback inlined into native code with **no runtime detour and no
  timing cost**, so it never perturbs the schedule. A pchtxt detour-hook at the same
  logical point cannot replicate that for *per-frame* code on Eden. **recomp ≠ pchtxt
  for timing-sensitive battle-loop code** — this is the crux.

## Eden config state (relevant to the race)
- `use_multi_core=false` (already single-core — so this is cooperative-scheduler timing,
  not host parallelism; toggling multicore won't help).
- `use_asynchronous_gpu_emulation=true`, `frame_gen_multiplier=2`, `async_presentation=false`,
  `cpu_backend=0` (Dynarmic), `cpu_accuracy=0`.
- Renderer Vulkan (`backend=1`). gdbstub now **disabled** (left clean for normal play;
  `tools/dbg.sh` re-enables it for the next experiment).

## Options for the reviewer (ranked by cost)
1. **Cheap config probe (low confidence):** disable async GPU + frame generation
   (`use_asynchronous_gpu_emulation=false`, `frame_gen_multiplier=1`) and retry the
   **no-op hook**. If the race closes, hook-based tracing/patching at `0x28BD20` becomes
   viable again. ~1 encounter to test.
2. **Pivot the PATCH to battle-SETUP injection (most promising):** PWB already hooks
   `0x305A70` (battle setup) and runs with no crash. Instead of clearing `+0x574&0x80`
   from a per-frame hook, research whether the delayed-faint effect can be produced from
   setup — e.g., configure the battle so a wild KO reaches the faint/EXP path without a
   per-frame flag edit, or install a one-shot that runs at a safe, non-per-frame point.
   recomp needed the clear *delayed to after the command menu* (clearing early hangs the
   opening); the open question is whether an equivalent can be staged from setup.
3. **Hook-free tracing** to still gather `state 4/5` data without crashing: observe the
   battle-event object via gdbstub memory reads only. Blocker: `0x28BD20` is
   virtual-dispatched (`blr`, no static `bl` callers), so we must first find a global /
   vtable object that reaches `evt` to poll `[global]→evt→fields`. Non-trivial but
   crash-free.
4. **Eden-side fix (heavy, not shippable):** we have Eden source; the `@0xd0` condvar
   HLE null-deref looks like an Eden robustness bug. Patching Eden would unblock locally
   but isn't a solution for end users of the mod.

## Recommendation
Do **1** first (one cheap encounter — it could cheaply revive the straightforward path).
If it still crashes, pursue **2** as the real strategy and use **3** only if we still need
runtime state data. Treat **4** as diagnostic-only.

## Clean state for handoff
- Crashing hook **disabled** (`…/Wild Battles EXP/exefs/pwb1_exp.pchtxt.off`); base PWB
  (`Wild Battles/pwb1.pchtxt`) still active → game is playable.
- gdbstub off, renderer Vulkan. Save snapshot `bak/save-20261029-121905/` intact.
- Patches on disk: `patches/pwb1_trace5.pchtxt` (safe-scratch tracer, crashes anyway),
  `patches/pwb1_noop.pchtxt` (no-op bisection hook). `tools/dbg.sh` preps a run
  (re-enables gdbstub, deploys a patch, starts `tools/scratchread.py`) but does not
  launch Eden (policy).
