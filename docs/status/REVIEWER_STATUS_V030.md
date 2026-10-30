# Wild Battles EXP — reviewer status at v0.3.0-alpha (2026-10-30, ~02:15)

**Headline:** the complete progression loop works through the game's native systems and is
frozen in version control:

```
wild battle → KO → faint → native EXP → level-up → evolution → return to exploration
```

Repo `github.com:avishayil/wild-battles-exp`, commits `f2e37b3` (v0.3.0-alpha code) and
`1be423e` (regression matrix + release-gate docs). Three byte-verified builds regenerate
from `tools/build_patch.py`: **main unified** (34 records), **Catch Variant** (28), add-on.

## What v0.3.0-alpha contains (all runtime-verified)
| Hook | Site (mem) | Function |
|---|---|---|
| A — faint | `0x28BF34` | clear instant-end flag once the command menu exists |
| C — model guard | `0xA9C650` | "no joint" for resource-less wild models (post-faint crash fix) |
| A2 — XP | `0x9D8A44` | bypass the predicate's `+0x4A4` gate; its flags check still excludes static encounters |
| R — HP capture | `0x9E41D0` | record the wild Pokémon's HP (slot 12) at battle end |
| A3 — exit | `0x28BD20` | state-5 result `1→3` **only on verified KO** (captured HP == 0), one-shot |
| A4 — evolution | `0x319EC4` | after-battle next-state `4→1` when `evolve_pending` (set only by A3's rewrite) |

## Regression matrix (full table in `research/EXPERIMENT_LOG.md`)
**PASS:** wild-KO flow (many runs) · flee (HP gate correctly blocks the rewrite; game's own
flee path runs) · trainer isolation (zero hook activity, fully vanilla) · evolution
(Caterpie 6→7 on wild-KO EXP → native cutscene → Metapod, reproduced from a reloaded save) ·
consecutive encounters / one-shot re-arm · intentional catching under the Catch Variant ·
PP/HP persistence between battles (an earlier PP-reset report did **not** reproduce).

**PARTIAL:** multi-species HP capture (Pidgey confirmed end-to-end; the flee capture showed
a live-HP read on a second species) · save/reload (mid-session reloads worked; no dedicated
pass).

**DEFERRED — the open release gates:** scripted Snorlax (Route 12/16) and a real legendary.
Unreachable in the early-game development save.

---

## Mapped leftovers

### P0 — release gates (blocked on save progression)
1. **Scripted Snorlax test.** Protocol ready: v0.3 instrumented build is deployed, every
   hook has a counter, disposable snapshot taken (`bak/save-20261030-020748`). Expected if
   isolation holds: `clear`=0 is **not** expected (Snorlax battles legitimately carry the
   instant-end flag — hook A *will* clear it, making Snorlax faintable; that is a real
   behavioral risk to measure), `REWRITE_CNT` must stay 0 unless HP hits 0, and the
   catch opportunity must still appear. This is exactly where the reviewer's "measure before
   adding a PWB marker" rule applies — hook A's menu-gated clear is the most likely place a
   marker becomes necessary, since the flags check protects A2 but nothing yet
   distinguishes PWB's synthesized battles from a real static encounter *for hook A*.
2. **Real legendary test** (e.g. Zapdos): same protocol, same decision rule.
3. **Decision after 1–2:** if any non-PWB effect is observed, introduce an explicit PWB
   encounter identity (set in PWB's own injected setup routine at `0x305970`, cleared at
   encounter teardown) and gate hook A (and A3/A4 if needed) on it — with trace evidence
   for where to set/clear. If the measurements are clean, keep the smaller tested patch.

### P1 — finish validation (doable in the current save)
4. **Multi-species HP capture:** KO ~4–5 different species (Pidgey/Rattata/Caterpie/
   Weedle/Nidoran) and confirm `WILD_HP→0` + rewrite each time; extend the reader to also
   log the captured species for cross-checking (reflect cave already reads `+0x78` region —
   one extra store if we want it).
5. **Dedicated save/reload pass:** save → quit Eden → relaunch → verify Metapod, levels,
   and XP persist; fight one more battle.
6. **PP recheck (close the earlier report):** use a move several times, end the battle,
   confirm PP stays consumed; repeat once under the Catch Variant (where the report arose).
7. **Catch Variant evolution check:** the variant lacks A3/A4, so a KO-without-catch
   there likely does **not** trigger evolution (the `evolve_pending` flag is never set).
   Verify and document as a variant limitation (vanilla catch-path evolution still works).

### P2 — pre-beta packaging (no blockers)
8. Tag `v0.1.0`/`v0.3.0` releases in git (commits exist; tags don't yet).
9. README: finalize the two-variant explanation and known-issues list after P0 lands.
10. Decide beta distribution (GitHub Releases zip of the two mod folders).

### Post-beta / future
11. **In-battle CATCH action** (recomp has reference work): would merge the two variants
    into one faithful FireRed-style experience. Significant new RE; explicitly out of
    scope until after beta.
12. Shiny + scripted wild encounters (the base PWB author lists untested scenarios).

## Standing constraints (unchanged)
Base PWB1 untouched; every record `pchtxt = mem + 0x100` with capstone/overlap/stack-depth
verification; patch-in-guest-memory check before trusting any run; save snapshots before
behavior changes; gdbstub memory-reads only; the AI prepares everything but the user
launches Eden.

## Question for the reviewer
Given the release gates are blocked on game progression, do you want (a) the P1 items
finished now and the beta explicitly labeled "not validated for static encounters", or
(b) hold any beta until Snorlax/legendary pass? Our lean is (b) for a public beta but (a)
is defensible with the README's current warning box.
