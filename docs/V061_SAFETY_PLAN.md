# v0.6.1 — Compatibility & Safety: validation plan

Status: **planning** · Baseline: `main` @ v0.6.0-beta (classic profile, 37 unified records,
cave `0xD32BA8..0xD32E54`, 428 B free) · Scope: **protect game progression and raise regression
confidence; no new gameplay behavior.**

This plan operationalizes the Nov 1 2026 architecture review (Findings A–E, Workstreams 1–2). It
separates work by what can be done **offline now** (no Eden, no save, no commit) from what is
**gated on a late-game save / the owner launching Eden**. The single release-blocking gate is
unchanged: **genuine scripted special-battle isolation** (Snorlax / legendary / Electrode).

---

## 0. Guardrails (unchanged, enforced by this plan)

- Generator is the source of truth; ship only if `build_patch.py` exits 0 (capstone +
  stack-balance + overlap). `pchtxt = mem + 0x100`. Never modify base PWB1 records; never remove
  the `0x9D3BA0` `+0x4A4` guard.
- **Default (`classic`) build stays byte-identical to v0.6.0-beta** unless a change is intentional
  *and* documented. Every generator change is diffed against the frozen baseline before it lands.
- AI never launches Eden; GDB stub reads only; `$c` before detach. Back up saves before
  behavior-changing runs. No game-derived bytes committed.

---

## 1. Offline workstream (no save / no launch required) — **delivered this pass**

These are the contained, high-value items. They need no copyrighted game files to *run* in CI
(the generator's byte checks need `text.bin`, which stays local). **Status: 1.1–1.5 implemented
and verified offline** (default build byte-identical to v0.6; `tests/` green; CI added). The
build-touching changes (1.4, 1.5) were re-diffed against the frozen v0.6 baseline — default
output unchanged.

### 1.1 Documentation correctness (Finding E) — **done in this pass**
- `docs/FUNCTION_MAP.md`: `0x9D3BA0` relabeled — the "EXP amount" reading is disproven; award path
  is the eligible-predicate branch in `0x9F28B8`. ✔
- `README.md`: the "never touches a real battle" claim is now scoped to the verified cases with the
  open scripted-encounter gate called out. ✔
- `AGENTS.md`: Catch Variant note made precise — it omits A3/R but **retains hook E** for
  `pwb_encounter` cleanup (A4 redirect inert). ✔

**Acceptance:** no doc states `0x9D3BA0` computes PWB EXP; no doc claims unconditional special-battle
isolation; Catch Variant's hook-E role is documented.

### 1.2 Trace regression hardening (Finding C) — **done**
Extend `tools/trace_assert.py` (keep the permissive default; add opt-in strictness):
- `--strict` / complete-session mode: an episode whose marker is still set at session end is a
  **FAIL** (not "open"); require every episode to observe `PWB_ENC==0` after the KO/exit.
- Event-sequence assertions, not just "hooks fired only when `PWB_ENC==1`": assert the *ordering*
  (marker set → … → result rewrite at most once → marker clear) and that `done`/rewrite happen
  inside the episode that owns them.
- Distinguish **"hook gating works"** from **"the encounter was correctly classified"** — add a
  note/field the reader can populate (e.g. native `[evt+0x735]`) so a future special-encounter
  trace can be asserted, and fail-closed if the classifier field is absent in strict mode.
- Ship **synthetic failing fixtures** under `tools/fixtures/` (stale marker, double rewrite, wrong
  slot, missing termination) and a `tests/` runner that asserts each fixture fails as expected and
  the real v0.5 fixture passes.

**Acceptance:** `tests/` runs with no game files; the good fixture passes in both modes; each
negative fixture FAILs in strict mode for the intended reason; CI runs this.

### 1.3 CI without copyrighted files (Finding D) — **done**
Add `.github/workflows/ci.yml` (host `github.com`, repo `avishayil/wild-battles-exp`) that runs:
- generator **unit tests** (AArch64 encoders, branch range/alignment) — pure, no `text.bin`;
- `trace_assert.py` over good + negative fixtures;
- **pchtxt lint** of committed `mods/*`: every record line is `@nsobid`-headed, `@enabled`/`@stop`
  wrapped, 8-hex address + even-length hex payload, addresses within known regions;
- **manifest integrity**: recompute SHA-256 of each committed `mods/*.pchtxt` and compare to
  `build-manifest.json` (catches a stale `mods/` vs manifest drift without needing `text.bin`);
- **doc-link + package-contents** checks (release zip layout `<Mod>/exefs/*.pchtxt`; no `*.nso`,
  keys, saves, or `text.bin` tracked).

**Acceptance:** CI is green on `main`; it fails if a committed mod's bytes drift from the manifest
hash, if a fixture regresses, or if a game file is ever staged.

### 1.4 Generator build-time hardening (Finding D) — **done**
Strengthen `build_patch.py` so more corruption fails at build time (keep default bytes identical):
- **Verify *all* hook-site preimages**, not only P/R/E. Assert each `disp(text, HOOK_x)` equals the
  documented original instruction (A, C, ST, M included), with the M-record's expected PWB bytes
  asserted before the overlap is whitelisted.
- **Cave-padding assertion:** the intended cave region in `text.bin` is all-zero padding before any
  bytes are emitted into it.
- **Explicit branch range/alignment:** every `b`/`cb*`/`b.cond` displacement is 4-aligned and
  within the signed imm range for its form (fail loudly instead of silently masking).
- **Artifact hash self-check:** after emit, recompute and (optionally, `--verify-manifest`) compare
  packaged artifact hashes to committed `build-manifest.json`.

**Acceptance:** build still exits 0 and reproduces v0.6.0-beta **byte-for-byte**; flipping any
hook-site/cave/branch assumption makes the build fail with a precise message. A unit test exercises
each new assertion with a crafted bad input.

### 1.5 Stricter HP/identity gate (Finding B) — **done; PROMOTED TO DEFAULT in v0.6.2**
> **Update (v0.6.2):** the strict gate is now the **default** (`--hp-gate strict`), after the live
> acceptance below was met — `slot==12 & maxhp>0` on every wild KO across Weedle/Pidgey/Rattata/
> Oddish, gathered by the autonomous harness (`docs/LIVE_TESTING.md`). `--hp-gate slot6` restores the
> old gate. The text below is the original v0.6.1 plan (when strict was opt-in).

- Add an **opt-in** generator option (default = current behavior, byte-identical). The strict path
  tightens A3/ST to require, on the rewrite: `pwb_encounter && captured_slot == 12 &&
  captured_species != 0 && captured_max_hp > 0 && captured_hp == 0 && result == 1 &&
  !already_processed` (today: `slot >= 6`, no `max_hp`/`slot==12`).
- Default builds **do not change**; the strict variant is produced only for the live multi-species
  test. It may become default **only after** it's verified clean across ≥5 species live.

**Acceptance:** default build byte-identical to v0.6; strict build exits 0 and differs only in the
A3/ST (and, if needed, R) caves; documented as pending live verification.

---

## 2. Gated workstream (needs a save + the owner launching Eden)

### 2.1 Scripted special-encounter isolation — **the one P0 release gate** (Finding A / WS1)
Deliver a **read-only diagnostic build** (trace-only; no result rewrite / no behavior change) and a
fixed protocol. For each encounter, capture over the GDB stub: `pwb_encounter` (+0xF8), native
`[evt+0x735]`, setup `[+0x4A4]`/`[+0x494]`, instant-end flag `[evt+0x574]&0x80`, timer `[evt+0x562]`,
hook counters, `[evt+0x720]→[+0x68]→[+0x508]` result chain, and the capture/exit transition.

Three-way contrast on **backed-up, disposable saves**: **vanilla**, **base PWB1**, **Wild Battles
EXP**, so an observed difference is attributed correctly.

Matrix (P0 first):

| Scenario | Why | Priority |
|---|---|---|
| Snorlax (Route 12/16) | unique scripted battle + capture | P0 |
| A legendary (e.g. Zapdos) | special-battle preservation | P0 |
| Scripted Electrode (Power Plant) | different special-encounter trigger | P0 |
| Early-game, partner menu locked | inherited PWB softlock risk | P1 |
| Pikachu-only, no follower | upstream recomp edge case | P1 |
| Catch Variant: success/fail capture | EXP-duplication + lifecycle | P1 |
| Shiny wild | rare-encounter behavior | P1 |
| Two-player encounter | menu/input scoping | P2 |
| GO Park | distinct initiation | P2 |

**Pass criteria (P0):** on a genuine Snorlax/legendary/Electrode, `pwb_encounter` stays **0**, the
native timer/result/capture behavior is **identical to vanilla**, and no mod hook increments.
**Fail-closed:** if any special encounter sets `pwb_encounter`, do **not** promote to stable; add a
real discriminator (candidate: native `[evt+0x735]`) and re-gate.

**Unblock options (no save redistribution):** either advance a disposable dev save to Route 12, or
recruit a tester with their **own** legally-obtained progressed save who runs the **trace-only**
diagnostic build on a disposable backup and returns the trace log. No saves are exchanged.

### 2.2 Progression control tests (WS1)
- **Catch Variant duplicate-EXP** measurement (measure before calling it a bug).
- **PP / HP persistence** vs vanilla and base PWB across consecutive encounters + save-reload.
- **Early-game compatibility** before the partner-interaction menu unlock (inherited softlock risk).
- **Multi-species HP/slot**: confirm `slot==12`, `species!=0`, `max_hp>0` hold live — the evidence
  that lets 1.5's strict gate become default.

---

## 3. Sequencing & exit

1. **Now (offline):** 1.1 ✔ → 1.2 → 1.3 → 1.4 → 1.5. Each build-touching step re-diffed against the
   frozen v0.6 baseline.
2. **When a save exists (owner launches):** 2.1 P0 matrix, then 2.2 controls.
3. **Promote v0.6.1:** all offline acceptance criteria met **and** the P0 special-encounter gate
   passes three-way clean. Until then, prereleases stay labeled experimental; no stable claim.

**Non-goal:** no Catch feature, no EXP scaling, no new game-version port in v0.6.1 (those are v0.7+,
tracked separately). EXP multipliers resume only after the award/write path in `0x9F28B8` is pinned
(see `research/EXP_SEAM_INVESTIGATION.md`).
