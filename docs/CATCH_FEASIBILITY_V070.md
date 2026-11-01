# v0.7 Integrated Catch — feasibility report (offline, no emulator)

Status: **research only.** Per the reviewer decision (Option C), this maps `raulzrrs/letsgo-recomp`'s
"catch during battle" feature and assesses porting it to our static IPSwitch `.pchtxt` for
Pokémon: Let's Go, Pikachu! **v1.0.2**. **No code is implemented and the v0.6 patch is untouched.**
Do not implement until this report (or a follow-up) identifies a credible native transition.

Sources: the recomp clone at `../work/recomp` (`runtime/hle/catch_button.c`, `wildbattle.c`,
`catch_button_art.h`, `runtime/fnhook.c`, `runtime/services/fs.c`, `docs/MODO-BATALHA.md` stage 6,
`CHANGELOG.md`) and our own `docs/FUNCTION_MAP.md` / `WBEXP_STATIC_CALLGRAPH.md`. recomp guest
addresses are **Eevee 1.0.0** (and a **Pikachu 1.0.0** table in `fnhook.c`); **there is no Pikachu
1.0.2 mapping in recomp** — 1.0.2 offsets below are either ours (runtime-confirmed) or marked
*derive*.

---

## 0. The architectural gap (read this first)
recomp implements catch-during-battle as **~30 native-C HLE callbacks** (`wildbattle_configure()`),
each wrapping a guest function via `rt_register_fnhook(addr, fn)`. A hook can read/write guest
memory, inspect structs, keep C state across frames, and call the original (`rt_call_original`).
**A `.pchtxt` cannot do that.** A static patch can only overwrite guest bytes/instructions and (via
our code cave) run small hand-written AArch64 subroutines that branch on scratch memory. So the
question is not "can we call recomp's C," but **"which of these behaviors can be re-expressed as
guest-code patches + cave subroutines + scratch state, within a ~428-byte cave budget."**

The honest headline: **a full recomp-equivalent in-battle CATCH is not feasible as a pure static
patch.** The always-on pieces are trivial; the *stateful* core (gate CATCH-vs-RUN, preserve HP
across a ball-broke re-battle, scale the catch-rate float by live HP/status) is a runtime state
machine, and the 5th-button menu needs menu-internal RE + served assets. Details and the narrow
prototype that *is* worth considering are below.

---

## 1. recomp mechanism map (what the feature actually does)
Laundered through the game's own **run-away → static-battle-win → capture** path (no new capture
call is synthesized):

1. **5th CATCH button.** Rebuilds 11 RomFS menu files per language (`bin/app/battle/bin/
   battle_command_00*.arc` SARC + `layout_setting_*`/`uikit_setting_*` FlatBuffers): repaints the
   BACK button as CATCH (BACK only shows in 2-player), inserts a 5th pane, widens the uikit nav
   grid 4→5, and stores the new button's hash in `g_catch_button_hash`. Served **only during the
   mode's wild battles** via a per-read RomFS switch (`made_on()`), so trainer/2-player battles get
   the vanilla 4-button menu.
2. **Button wiring (runtime).** `views_hook` (wraps `CMD_VIEWS`) finds the button by hash
   (`BUTTON_FIND`), points its decide-callbacks at the game's own 4, but routes its view to a
   recomp-owned fake view; `invoke_hook`/`decide_hook` detect the press and overwrite the resulting
   action to **RUN (4)**, setting `g_catch.requested`.
3. **Result gate.** `battle_event_hook` (wraps battle-event update): at state 5, if result==3
   (ran away) **and** `g_catch.requested`, rewrite result→**1 (win)**; a win of **battle kind 2
   (static)** flows into `AFTER_BATTLE → CAPTURE_AFTER_BATTLE` (wild obj at `[+0xc0]`).
4. **One ball, forced exit.** `noballs_hook` returns "no balls left" after `throws>=1` so the
   capture scene withdraws after a single throw.
5. **HP/status preserve.** `reflect_hook` stashes species/HP/maxHP/status of the wild mon
   (`BPP_REFLECT`); on re-battle `setup_hook` writes HP+status back (`BPP_SETUP`).
6. **Ball-broke re-battle loop.** `dtor_hook` flags `rebattle`; `field_hook` (world tick) re-enters
   the static battle a few frames later with HP/status preserved; the throw consumes the player's
   turn by forcing a **failed escape** (`escape_hook`→yes, `escape_roll_hook`→fail) so the wild mon
   then attacks. Intro/music/dialog suppressed via more hooks.
7. **Catch-rate bonus.** `catch_value_hook` (wraps `CATCH_VALUE`, which returns a float 0..255 in
   `s0`) multiplies by `catch_factor() = (3·maxHP − 2·HP)/maxHP`, ×2.5 for sleep/freeze else ×1.5
   for other status — i.e. HP/status bonus applied to the computed float.
8. **Strings/art.** In-battle lines rewritten at runtime by line index (`msg_hook`); button art is
   generated offline by `tools/catch_button_art.py` (no game art reused), embedded in
   `catch_button_art.h`, and re-assembled into the SARC/FlatBuffers at runtime.

---

## 2. Pikachu 1.0.2 equivalents (functions & offsets)
**Already ours** (runtime-confirmed in `FUNCTION_MAP.md`; we hook these today):

| recomp (Eevee 1.0.0) | role | **our PK 1.0.2** | we hook as |
|---|---|---|---|
| `BATTLE_EVENT_UPDATE 0x28be80` | battle-event update; result chain `[evt+0x720]→[+0x68]→[+0x508]` (1 win / 3 run) | **`0x28BD20`** | A3 (result rewrite) |
| `BPP_REFLECT 0x9e4280` | wild write-back; `+0x78` species, `+0x7c` maxHP, `+0x7e` HP, `+0x87` slot(12) | **`0x9E41D0`** | R (HP capture) |
| `EXP_ENABLED 0x9d8ae0` | XP eligibility; `setup+0x4a4`, `+0x494` | **`0x9D8A30`** | P (A2) |
| `STATIC_SETUP 0x28c770` | special-battle setup; clock `[evt+0x562]`, flag `[evt+0x574]&0x80` | **`0x28C740`** | A (timer zero) |
| `MODEL_JOINT 0xa9c700` | model-joint guard | **`0xA9C650`** | C |
| `AFTER_BATTLE 0x319bc0` | after-battle processor (state `[+0x68]`) | **`0x319A60`** | E (A4) |
| command menu: state-4 handler region | `[x1+0x60]` = command-menu object | **`0x28BF34`** (state-4 handler) | A (flag-clear) |

The field offsets recomp uses (`+0x78/+0x7c/+0x7e/+0x87`, result chain, `+0x4a4/+0x494`,
`+0x562/+0x574`) are **identical to our runtime-confirmed values** — strong corroboration that the
recomp map is reliable and that our existing hooks already sit on the catch feature's battle-side
functions.

**Not yet mapped to 1.0.2** (recomp gives Eevee 1.0.0 → Pikachu **1.0.0**; re-derive for 1.0.2 by
instruction-matching, recomp's own method = `tools/addrmap.py`). Anchors to start from:

| name | Eevee 1.0.0 | PK 1.0.0 | note |
|---|---|---|---|
| `CAPTURE_AFTER_BATTLE` | `0x31a0e0` | `0x31a0b0` | wild obj `[+0xc0]`; ≈ `−0x160` from Eevee like `AFTER_BATTLE` → *derive ~`0x319F80`, verify* |
| `CATCH_VALUE` | `0x7de080` | `0x7de0b0` | float catch value in `s0` |
| `CAPTURE_JUDGE` | `0x7dcb00` | `0x7dcb30` | shakes `[+0x128]`, ≥4 caught |
| `NO_BALLS_LEFT` | `0x919970` | `0x9199a0` | bag check |
| `CAN_ESCAPE` | `0xa5c350` | `0xa5c360` | 5 = yes |
| `ESCAPE_ROLL` | `0x9f7300` | `0x9f7310` | 0 = failed to flee |
| `RUN_ASK` | `0x7de440` | `0x7de470` | capture-exit dialog |
| `CMD_VIEWS / CMD_DECIDE / BUTTON_FIND` | `0xab2730 / 0xab1e80 / 0x368330` | `0xab2740 / 0xab1e90 / 0x3682d0` | menu internals (new RE) |
| `WORLD_TICK` | `0x2f78d0` | `0x2f78a0` | re-battle driver |

Caution: inter-build drift is **not uniform** (`BATTLE_EVENT` −0x160, `STATIC_SETUP` −0x30), so the
PK-1.0.0 column is a starting anchor only; each 1.0.2 address must be instruction-matched.

---

## 3. Classification per requirement
Legend: **S** = static-patchable (constant-return / byte edit); **S+cave** = static but needs a
cave subroutine + scratch state (like our existing hooks); **Asset** = LayeredFS file;
**Runtime** = needs native runtime support recomp has but a `.pchtxt` lacks.

| Requirement | Class | Notes |
|---|---|---|
| No 5-min clock in wild battle | **S** (done) | we already zero `[evt+0x562]` in cave_A |
| EXP eligibility on | **S+cave** (done) | hook P |
| Escape always allowed (`CAN_ESCAPE`→5) | **S** | single constant return |
| Force failed escape (`ESCAPE_ROLL`→0) | **S** | but only wanted on the re-battle turn → really **S+cave** (needs state) |
| One ball then exit (`NO_BALLS_LEFT`→1 after a throw) | **S+cave** | "after a throw" needs a scratch counter |
| 5th CATCH button artwork + layout | **Asset** | pre-bake with `tools/catch_button.py`; but see §5 "always-on" problem |
| Button wiring / press detection (`views/invoke/decide`) | **Runtime** | allocates a fake view, calls `BUTTON_FIND` at runtime, routes to recomp state |
| Gate result 3→1 **only when CATCH pressed** | **Runtime / S+cave (hard)** | needs a "CATCH pressed" scratch flag set from the menu path — the menu hook is the blocker |
| Preserve wild HP/status across re-battle | **S+cave (hard)** | stash on reflect, restore on setup — two cave subroutines + scratch, mirrors recomp |
| Ball-broke → re-enter battle (frame-delayed) | **Runtime** | recomp drives it from `WORLD_TICK` across frames with a C state machine |
| Catch-rate × HP/status (float in `s0`) | **Runtime** | intercepting a computed FP return and scaling by live HP/status is not a clean static edit |
| In-battle string rewrites | **Asset** (approx) | a static mod could patch the encrypted `.dat` for ONE language instead of runtime line-rewrite |

---

## 4. Minimal native-transition proposal (the only credible static slice)
Do **not** attempt the full feature. The narrowest transition that reuses what we already have:

> **"CATCH ends the battle at current HP and routes to the native capture"** — i.e. reproduce
> recomp steps 2–3 only (press → RUN action → result 3→1 → `AFTER_BATTLE`/`CAPTURE_AFTER_BATTLE`),
> dropping the one-ball limit, the HP-preserving re-battle loop, and the catch-rate bonus.

Even this needs, at minimum: (a) a **5th button** served via LayeredFS (pre-baked), (b) a
**menu-press→scratch-flag** hook (the hard, un-RE'd part), and (c) a **result-gate cave** that flips
`[+0x508] 3→1` only when that flag is set (so ordinary RUN still flees). We already own the
result-chain hook site (`0x28BD20`) and the scratch mechanism, so (c) is within reach; **(b) is the
blocker** — it requires new RE of the command-menu internals (`CMD_VIEWS`/`BUTTON_FIND`/uikit
hashes) in 1.0.2 and a cave subroutine to detect the CATCH view and set the flag.

Important simpler alternative already shipped: our **Catch Variant** already battles the wild mon
then shows the native catch screen after the KO. If the goal is "battle then catch," that exists
today; the recomp feature's distinct value is *catching mid-battle without KO, with HP-scaled
odds*, which is the expensive stateful part.

---

## 5. State-machine & save-safety risks
- **Cave budget.** v0.6 leaves **~428 B** free (`0xD32BA8..0xD33000`; strict-gate variant ~408 B).
  The minimal slice's menu-detect + result-gate subroutines plausibly fit; the full feature (HP
  preserve + re-battle + rate bonus) does **not** — it would need a new executable-space strategy
  (additional cave regions, or abandoning the static approach). Document before any attempt.
- **Always-on menu.** recomp serves the 5-button menu *only* during its wild battles (per-read
  RomFS switch). A static LayeredFS asset is **unconditional** → the 5th CATCH button would appear
  in **trainer and 2-player battles too**, where pressing it (routed to RUN) could flee a trainer
  battle or misbehave. This is a correctness risk with no clean static fix.
- **Re-battle loop.** The ball-broke re-entry is a cross-frame host state machine with forced
  inputs; a naive static version risks leaving the battle in a bad state (soft-lock / corrupted
  party) → **save-corruption risk**. Out of scope for a static slice.
- **Result-gate false positives.** Flipping `3→1` without a reliable "CATCH pressed" signal would
  convert genuine flees into wins→captures — exactly the isolation failure class we've been careful
  about. The gate MUST be driven by a verified menu-press flag.
- **Catch at current HP.** Whether the native static-win→capture uses the wild mon's *current*
  battle HP (vs a reset) is **unverified** — recomp explicitly re-writes HP via `reflect/setup`, so
  the native path may not preserve it on its own.

---

## 6. Recommended first prototype (if/when pursued) + pass/fail
Smallest safe experiment, **read-mostly**, to decide go/no-go before building the feature:
1. **RE the command menu in 1.0.2** (offline) — **DONE, PASS: see `research/CATCH_STEP1_MENU_RE.md`.**
   `CMD_DECIDE` = `0xab1dd0`; chosen-button id in `w20` at `0xab1e34`; 7-way switch (jump table
   `0xf9823c`) → per-id action at `[x21+0x10]`; the `pwb_encounter` scratch gate (`+0xF8`) is
   reachable from a cave. A static hook **can** set a scratch flag iff a specific button is pressed
   in a PWB wild battle, zero false positives. Caveat that reshapes step 2: a *new* 5th button is not
   static-feasible, so the slice must repurpose RUN. One live id↔label read remains before wiring.
2. **Result-gate prototype** (only if step 1 passes): on a *normal* RUN, flip `[+0x508] 3→1` gated
   on the step-1 flag and let the capture run. **Pass:** choosing the gated action ends the battle
   and the native capture screen opens on the wild mon at a sane state, while an un-gated RUN still
   flees. **Fail:** capture screen doesn't open, or opens with wrong/garbage mon → native win→capture
   needs more setup than a result flip; stop.
3. Only if 1–2 pass, scope the 5th-button asset + the always-on-menu mitigation separately.

No prototype touches a real trainer/legendary battle; all on a disposable early-game save; gdbstub
reads-only; v0.6 stays the deployed build.

## 7. Explicit unresolved questions
1. **Menu observability (the crux): RESOLVED — see `research/CATCH_STEP1_MENU_RE.md`.** Yes: the
   chosen-button id is in `w20` at `0xab1e34` (event+4) and the per-id action at `[x21+0x10]`, and
   the PWB gate (`pwb_encounter` scratch `+0xF8`) is reachable from a cave trampolined off the uikit
   `CMD_DECIDE` — so a static hook can set a scratch flag iff a specific button is pressed in a PWB
   wild battle, zero false positives. **But** a *distinct 5th CATCH button* is NOT static-feasible
   (needs per-allocation runtime view/callback wiring); a static slice must repurpose an existing
   button (RUN), which is a UX decision for the owner. One live id↔label confirmation remains.
2. **1.0.2 offsets:** all capture/menu functions in §2's second table need instruction-matched
   1.0.2 addresses (recomp only has 1.0.0).
3. **Native HP at capture:** does the static-win→capture use current battle HP without recomp's
   reflect/setup writes?
4. **Always-on 5th button:** any static way to hide it in trainer/2-player battles? (recomp uses a
   per-read RomFS switch we can't replicate.)
5. **Cave space:** is there a second usable code-cave region in 1.0.2 beyond `0xD32BA8..0xD33000`,
   or an alternative injection, to fit anything past the minimal slice?
6. **Re-battle feasibility:** is a frame-delayed battle re-entry even expressible without a host
   tick callback? Current assessment: no.

---

## Verdict
Reproducing recomp's in-battle CATCH **as a static `.pchtxt` is not feasible in full** — it is a
stateful native-runtime feature (menu wiring, HP-preserving re-battle, FP catch-rate scaling) plus
conditionally-served assets. A **minimal "CATCH = end battle → native capture at current HP"** slice
*might* be feasible and reuses hooks we already own, but it is **gated on new command-menu RE
(unresolved question #1)** and still carries the always-on-button and result-gate risks. Recommend:
keep v0.7 in research; do the bounded step-1 menu RE to settle go/no-go before committing; and treat
the existing **Catch Variant** as the shipped "battle-then-catch" answer in the meantime. Full
parity would realistically require runtime support a static mod doesn't have — i.e. a different
delivery vehicle than IPSwitch.
