# PWB injection — static call-graph report (v0.4.1 hardening)

Read-only analysis of the vanilla Pikachu 1.0.2 `.text` (`text.bin`) plus the base
`pwb1.pchtxt` records, to answer: **is PWB's marker (`[setup+0x298]=1`) exclusive to
synthesized ordinary-wild encounters, or can a genuine Snorlax/legendary reach it?**
All offsets are NSO memory offsets. No live state was used (no save near Snorlax).

## Mechanism — how PWB sets the marker (fully resolved)

PWB turns ordinary wild encounters into the game's *special-battle* type and injects a setup
routine that writes the marker. Three records drive it:

1. **`0x28BE84` → `mov w8,#9; nop; b 0x28be94`.** In the battle-event setup (fn `0x28BD14`),
   vanilla does `ldrb w8,[x19,#0x735]; cbz w8,0x28be90; <state++>` ... `0x28be90: mov w8,#0xc`.
   PWB replaces the `[x19+0x735]!=0` arm so it writes **9** into `[x19+0x68]` instead. i.e. the
   encounter is pushed onto the special-battle path **only when `[evt+0x735] != 0`**.
2. **`0x28CB10` → `b 0x305b10`** (PWB trampoline): `ldrb w8,[x19,#0x735]; cmp w8,#0;
   mov w2,#0xa; mov w8,#9; csel w2,w8,w2,ne` — again **branching on `[evt+0x735]`** to choose
   kind **9 vs 10**.
3. **`0x305934` → `bl 0x305970`** (vanilla called `0x2f6470`): retargets a call inside
   function **G (`0x305784`)** to PWB's **injected setup routine `0x305970`**, which copies
   config into the setup object and writes **`mov w9,#1; str w9,[x20,#0x298]`** at `0x3059B8`
   (`x20` = `x0` = the setup object). This is the marker. (Our hook M replays this exact store.)

## Finding 1 — the marker's enclosing function is virtually dispatched (UNCERTAIN exclusivity)

Function **G = `0x305784`** (which contains the retargeted `bl 0x305934` that writes the marker)
has **zero direct callers** in `.text` — it is reached only by indirect/virtual dispatch
(`ldr x8,[obj]; ldr x8,[x8,#off]; blr x8`). PWB's injected routine `0x305970` itself has only
two vanilla direct callers (`0x2fdf34`, `0x2fdf80`), and PWB **NOPs both** of them — so the
vanilla entry into that code is dead; the only live entry is the retargeted `bl` inside G.

**Consequence:** a pure static call-graph *cannot* prove the marker is exclusive to
ordinary-wild encounters, exactly as you flagged. I cannot resolve G's vtable call sites to
their originating encounter types with reads alone. **Evidence: strong for the mechanism;
insufficient for exclusivity. Verdict: UNRESOLVED offline.**

## Finding 2 — a NATIVE discriminator exists: `[evt+0x735]` (strong lead)

PWB **only reads** `[evt+0x735]` (records 1 and 2 above); **no PWB record writes it.** So it is
a *game-native* field, and the vanilla code at `0x28BE7C` also branches on it. PWB uses it as
its "this encounter should become a battleable wild" signal — the kind-9 forcing and the 9/10
selection are both gated on `[evt+0x735] != 0`.

- If genuine Snorlax/legendary encounters have `[evt+0x735] == 0`, they never take PWB's
  kind-forcing arm, which is consistent with (though not proof of) the marker not being written.
- **This is the precise quantity the live Snorlax/legendary test must capture**, alongside our
  `pwb_encounter` (+0xF8). It is also a candidate **defense-in-depth gate**: hook A already has
  `evt` in `x19`, so it could additionally require `[evt+0x735]!=0`. **I have not implemented
  that gate** — its exact semantics (what sets `0x735`, and whether it can be nonzero for a real
  static encounter) are unconfirmed, and adding an unverified gate risks breaking the working
  path. Flagged for your decision.

**Evidence: strong (PWB reads-not-writes `0x735`, vanilla branches on it). Uncertainty: whether
`0x735` can be nonzero for a real static encounter — needs the live test.**

## Finding 3 — marker lifetime (the v0.4.1 fixes)

The marker lives in the setup object at `[setup+0x298]`; our mirror is scratch `+0xF8`,
set by hook M. In vanilla terms the setup object is torn down per battle, but **our scratch
flag's lifetime is ours to manage**, and your review found two gaps, both now fixed on branch
`v0.4.1-encounter-isolation-hardening`:

- **A2 (cave_P) now requires `+0xF8`** in addition to the profile (`setup[+0x4A4]==1 &&
  setup[+0x494]==0`), so a non-PWB battle that happens to share the profile cannot get modified
  XP eligibility.
- **Hook C (cave_C) now requires `+0xF8`** — outside a PWB encounter it runs the untouched
  original, so a resource-less vanilla model is never force-returned "no joint".
- **Catch Variant now includes hook E** (after-battle), whose only live effect there is to
  **clear `+0xF8`** (its A4 state-redirect stays inert — `evolve_pending` is never set without
  cave_ST). Previously the catch variant set the marker and never cleared it.

**Ordering note (important):** the marker must NOT be cleared at battle-event state 0 — PWB's
setup (`0x305970`, which sets it) runs *before* the battle-event state machine ticks, so a
state-0 clear would wipe it before hook A (state 4) reads it. Cleanup therefore has to be at
battle *end* (after-battle processor, hook E). **Whether hook E fires on every termination path
(KO / capture / flee / abort) is not established statically** and must be confirmed live — this
is the "regression evidence for marker cleanup" item.

## Differential verification (offline, done)
`build_patch.py` rebuilds clean (capstone + stack-balance + overlap). A relocation-normalized
cave diff vs the frozen v0.4.0 build shows the **only** changes are: unified → cave_C and cave_P
gained the `+0xF8` gate; catch → same two gates plus cave_E added. A/ST/R/E/M byte-identical.

## Live regression evidence collected (v0.4.1, 2026-10-30, gdbstub scratch trace)

**Session 1 — unified build.** 2 wild KOs, 1 flee, 1 trainer battle:
- New gates didn't regress the working path: in each PWB wild battle `PWB_ENC=1` set first, then
  hook A fired (`clear`++), and **A2 (`A2_PWB`++) and C (`guard`++) still fired** — both now
  gated on `+0xF8` and both engaged correctly.
- KOs: `WILD_HP=0` → result `1→3` → `REWRITE_CNT` 1→2 → **`PWB_ENC` cleared to 0.**
- Flee: hook A armed but `WILD_HP=20` (non-KO) → **A3 did not rewrite** (`REWRITE_CNT` held) →
  **`PWB_ENC` cleared to 0.**
- Trainer battle: **`PWB_ENC` stayed 0 throughout; `clear`/`A2_PWB`/`guard`/`REWRITE_CNT` all
  frozen** — fully vanilla, and no stale marker leaked from the preceding flee. (Confirms cave_C
  now falls through to the original when `+0xF8==0`.)

**Session 2 — catch variant.** 1 KO+capture, 1 flee:
- KO+capture: `PWB_ENC=1`, hooks fired (gated), catch screen stayed, caught; **`PWB_ENC` cleared
  to 0 after the capture** (hook E on the capture path).
- Second battle: `PWB_ENC` re-set **fresh** from 0 (no leak), then cleared again after the flee.

⇒ **Marker cleanup confirmed on KO, capture, and flee paths; no leak into the following battle;
the three P0 gate fixes behave as intended.**

## Still outstanding (not blocked by the above)
1. **`[evt+0x735]` on a real static encounter** (needs a save at Snorlax/legendary): is it 0?
   does `pwb_encounter` stay 0? does the capture opportunity survive? — the remaining beta gate.
2. **Multi-species HP:** observed slots so far: wild `12`, HP capture `0` (KO) and `20` (flee);
   widen to 4–5 species and optionally log species alongside `R`.
3. Save → quit → relaunch persistence pass; PP control test (base PWB vs EXP vs catch).
