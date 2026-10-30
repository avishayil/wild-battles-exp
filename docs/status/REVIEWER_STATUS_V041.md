# Wild Battles EXP — reviewer status at v0.4.1-alpha (2026-10-30)

Record of the v0.4.1 review cycle: the reviewer accepted v0.4.0, held the public beta, and
flagged three source-level scoping gaps beyond the already-known marker-exclusivity question.
All three were fixed and live-verified; v0.4.1-alpha shipped as an experimental prerelease.

## Reviewer decision
**Continue hardening; hold promotion to public beta pending static-encounter safety.** The new
hook M (tracking PWB's own setup activity rather than inferring from battle-state flags) was
accepted as an architectural improvement, and the v0.4 regression (two consecutive KOs, trainer,
Pidgey, flee — all correct, no crashes) was accepted as encouraging. But the marker is only a
reliable discriminator if PWB's setup routine is exclusive to synthesized ordinary-wild
encounters, which must be investigated now rather than waiting for game progression.

## P0 findings (all confirmed in source and fixed)
1. **A2 was profile-gated, not marker-gated.** `cave_P` checked `setup[+0x4A4]==1 &&
   setup[+0x494]==0` but not `pwb_encounter` (+0xF8). A non-PWB battle sharing the profile could
   have received modified XP eligibility. **Fix:** require `pwb_encounter` in addition to the
   profile.
2. **Catch Variant leaked the marker.** It included hook M (set `pwb_encounter`) but not hook E
   (clear it), so the marker could persist into a later, possibly non-PWB, battle. **Fix:** add
   hook E to the variant (its A4 state-redirect stays inert — `evolve_pending` is never set
   without cave_ST), so the marker clears after each battle.
3. **Hook C was not encounter-scoped.** The model-joint guard acted on resource fields without
   checking `pwb_encounter`. **Fix:** gate it on the marker — outside a PWB battle it runs the
   untouched original.

Also noted: HP capture accepts battle slot `>= 6` (observed wild slot `12`) — validate across
multiple species before treating the HP gate as universally reliable.

## Static call-graph analysis (approved, done)
See [`../WBEXP_STATIC_CALLGRAPH.md`](../WBEXP_STATIC_CALLGRAPH.md). Marker mechanism fully
mapped (forced kind-9 + injected setup at `0x305970`, reached via a retargeted `bl` at
`0x305934`, writing `[setup+0x298]=1`). The enclosing function is **virtually dispatched**, so
offline analysis cannot prove exclusivity to ordinary-wild encounters. Lead: PWB only *reads*
the native field `[evt+0x735]` (never writes it) to pick kind 9-vs-10 — the discriminator to
confirm on a live static encounter. Lifecycle: the marker must be cleared at **after-battle**
(not state 0, which precedes it), and coverage of all termination paths needed live confirmation.

## Live regression evidence (gdbstub scratch trace)
- **Unified:** 2 wild KOs, a flee, a trainer battle. A2/C still fire inside PWB battles with the
  new gates; the marker clears on KO and flee; the trainer battle is fully vanilla with no leaked
  marker (confirms C falls through to the original when the marker is clear).
- **Catch Variant:** a KO+capture and a flee. The marker clears on **both** the capture and flee
  paths and re-sets fresh next battle — no leak.

⇒ All three P0 fixes behave as intended; marker cleanup confirmed on KO, capture and flee.

## Outcome
Fixes implemented on a dedicated branch, differential-verified against v0.4.0 (unified: only
cave_C + cave_P changed; catch: + cave_E; all other caves byte-identical), then merged and
released as **v0.4.1-alpha** (experimental prerelease). v0.4.0-alpha preserved by its tag as the
prior baseline.

## Still open (unchanged beta gate)
A live scripted-Snorlax / legendary isolation test (measure `pwb_encounter` and `[evt+0x735]`
there; capture opportunity must survive), multi-species HP capture, a save/reload persistence
pass, and a PP control test. Public beta remains held until the static-encounter test passes.

## Standing constraints (unchanged)
Base PWB1 untouched; every record `pchtxt = mem + 0x100`; capstone + stack-balance + overlap +
differential-vs-last-good verification; verify bytes in guest memory before trusting a run;
gdbstub memory-reads only (no breakpoints); save snapshots before behavior changes; the AI
prepares everything, the owner launches the emulator.
