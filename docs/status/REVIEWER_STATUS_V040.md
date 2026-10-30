# Wild Battles EXP — reviewer status at v0.4.0-alpha (2026-10-30)

**Headline:** v0.4.0-alpha is shipped and live-verified. The per-encounter PWB isolation you
flagged as the P0 design risk at v0.3 is now implemented — the faint hook and the XP override
no longer key off menu/flags proxies, they key off **PWB's own per-encounter marker**. Repo
`github.com:avishayil/wild-battles-exp`, commit `88448f5` on `main`, tag `v0.4.0-alpha`,
prerelease published with the three Eden-importable zips. All artifacts regenerate byte-for-byte
from `tools/build_patch.py`.

## What changed since v0.3.0-alpha (and why it answers your P0 note)

Your v0.3 brief called out the real risk precisely: *hook A's menu-gated instant-end-flag clear
would also fire in a genuine Snorlax/legendary battle (those legitimately carry the `0x80`
flag), making it faintable and letting A3 rewrite the result — the flags check only protected
A2 (XP), nothing protected hook A.* You recommended adding an explicit PWB marker **only with
trace evidence**, and predicted hook A was where it would become necessary. That is exactly what
v0.4 does:

| Hook | v0.3 | v0.4 |
|---|---|---|
| **M** (new) `0x3059B8` | — | Replays PWB's own marker write (`str w9,[x20,#0x298]`, inside PWB's injected setup) and sets a scratch flag `pwb_encounter` (+0xF8). |
| **A** faint `0x28BF34` | clears `0x80` when the command menu exists | …**and only when `pwb_encounter` is set**. |
| **A2** XP `0x9D8A30` | blunt one-word bypass of the `+0x4A4` gate at `0x9D8A44` (global) | predicate-**entry** wrapper: force eligibility **only** for the PWB profile (`setup[+0x4A4]==1 && setup[+0x494]==0`), otherwise run the **untouched** original predicate. |
| **E** after-battle `0x319EC4` | A4 evolution redirect | …**plus** clears `pwb_encounter` each battle, so it re-arms per encounter. |

C (crash guard), ST (state machine / A3 result rewrite), R (HP capture) are **byte-identical** to
v0.3 (a relocation-normalized diff confirms it); only A/E/P/M changed. Build self-verifies with
capstone + a dataflow stack-balance check + an overlap check (one intentional overlap: M's branch
sits inside PWB's 32-byte `0x305AB0` record, whitelisted).

## Live regression (gdbstub scratch trace, reader now surfaces `PWB_ENC`)

| Test | Result |
|---|---|
| Wild KO #1 | `PWB_ENC=1` at setup → hook A fires (`clear`,`armed`) → verified KO (`WILD_HP=0`) → result `1→3` → auto-exit → `PWB_ENC` cleared. |
| Wild KO #2 (consecutive) | **`PWB_ENC` re-set, one-shot re-armed** — identical pass. Proves the marker fires *per encounter*, not once at init. |
| Trainer battle | **Fully vanilla**: `PWB_ENC` never set, no hook activity, `REWRITE_CNT` unchanged. |
| Wild KO #3 (Pidgey) | Identical clean pass. |
| Flee | Hook A armed (`PWB_ENC=1`) but the result rewrite **did not fire** (no verified KO); native flee path ran. |

Zero crashes. `REWRITE_CNT` advanced exactly once per KO (1→2→3), never on trainer or flee.

## The open gate — reframed, and where I'm stuck

**I still cannot run the Snorlax/legendary live test** — the development save has nothing near
them, and that hasn't changed.

What *has* changed is the nature of the risk. In vanilla LGP, ordinary wild Pokémon aren't
battled at all (motion-catch); the **only** vanilla wild *battles* are Snorlax and the legendaries,
via the game's "special battle" system. **PWB works by routing ordinary wild encounters through
that same special-battle system.** So a PWB wild battle and a real Snorlax battle are the *same
battle type* at the engine level — which is why isolation is the whole ballgame, and why the
trainer-battle PASS above is reassuring but **not** decisive (trainers use a different system;
Snorlax shares PWB's).

The entire v0.4 isolation therefore rests on one unverified proposition:

> **PWB's marker (`str w9,[x20,#0x298]` at mem `0x3059B8`) is written only when PWB synthesizes
> an ordinary-wild encounter, and never on the scripted Snorlax/legendary path.**

If that holds, a real Snorlax never sets `pwb_encounter`, so hooks A and A2 are inert on it and
the capture opportunity is preserved. If PWB injects its marker into a setup function that the
scripted path *also* reaches, isolation fails and v0.4 is no safer than v0.3 for static encounters.

### A save-independent way to (partially) settle it
PWB injects at the seam around mem `0x305920`–`0x3059C4` (vanilla `bl 0x2f6470` at `0x305934`;
the marker lands at `0x3059B8` where vanilla has a `blr x8` virtual dispatch). **I propose a
static call-graph analysis of that injection site**: determine which encounter-setup entry points
reach it, and whether the scripted-special-battle entry (Snorlax/legendary) is among them. That
needs no save and would either (a) give offline evidence the marker is exclusive to the
ordinary-wild path, or (b) surface a concrete failure mode to fix before beta. It won't fully
replace a live test, but it's the strongest thing available without save progress.

## Save-independent backlog I can do now (P1)
1. **Multi-species HP-capture:** KO ~4–5 species, confirm `WILD_HP→0` + rewrite each time; I can
   add a one-store species log to cross-check `R`'s capture.
2. **Dedicated save/reload pass:** save → quit Eden → relaunch → verify levels/XP/Metapod persist,
   fight one more. (Only spot-checked so far.)
3. **PP recheck (close the earlier report):** use a move repeatedly, end battle, confirm PP stays
   consumed; repeat under the Catch Variant where the report arose. (Our hooks touch no PP; `R`
   writes back HP/EXP/status only — leaning base-PWB limitation, want to confirm/attribute.)
4. **Catch Variant evolution limitation:** it lacks A3/A4, so a KO-without-catch there likely
   won't evolve (`evolve_pending` is never set). Verify and document as a variant limitation.

## Questions for you
1. **Beta timing.** Given v0.4 *structurally* excludes non-PWB battles (both risky hooks now
   require PWB's marker), and given I can't reach Snorlax/legendary — would you accept a public
   beta labeled "structurally isolated to PWB encounters; not yet live-tested against scripted
   static encounters," or do you still want the gate held until a live Snorlax/legendary run?
2. **Offline gate work.** Is the static call-graph analysis of PWB's injection site worth doing
   now, or would you rather I not spend RE effort there and simply wait for a save that reaches
   Snorlax?
3. **P1 ordering.** Of the four backlog items, which do you want first? My lean: save/reload pass
   (cheap, user-visible) → multi-species → catch-variant evo doc → PP.
4. **PP scope.** Is the PP-reset behavior in scope at all, or acceptable to document as a base-PWB
   limitation and move on?

## Standing constraints (unchanged)
Base PWB1 untouched; every record `pchtxt = mem + 0x100`; capstone + stack-balance + overlap +
differential-vs-last-good verification; verify bytes in guest memory before trusting a run; gdbstub
memory-reads only (no breakpoints); save snapshots before behavior changes; the AI prepares
everything, the owner launches Eden.
