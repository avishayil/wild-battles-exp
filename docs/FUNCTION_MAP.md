# Function & field map — Pikachu 1.0.2 (`C208DB6A…`)

All addresses are **NSO memory offsets** (== `text.bin` offsets). To patch an instruction
at memory offset `M`, the pchtxt record address is **`M + 0x100`**.

## Hook sites used by this mod
| Mem offset | pchtxt addr | What it is | Displaced instruction |
|---|---|---|---|
| `0x28BD20` | `0x28BE20` | Battle-event update **entry** (`x0`=evt). State word `[evt+0x68]`; dispatches via jump table. Hooked for A3 (reset flags @state0, result rewrite @state5). | `sub sp,sp,#0x70` |
| `0x28BF34` | `0x28C034` | **State-4 handler** (`ldr x20,[x1,#0x60]; cbz x20,…`). `[x1+0x60]` = command-menu object. Hooked for A (clear instant-end flag). | `ldr x20,[x1,#0x60]` |
| `0x9D8A30` | `0x9D8B30` | **EXP-eligibility predicate entry** (`ldr x8,[x0,#0x80]`). Hooked for A2: return `w0=1` only when `pwb_encounter` (+0xF8, v0.4.1) **and** the PWB profile (`setup[+0x4A4]==1 && setup[+0x494]==0`) hold; else run the untouched original. (Replaces the v0.1–v0.3 in-place bypass at `0x9D8A44`.) | `ldr x8,[x0,#0x80]` |
| `0x3059B8` | `0x305AB8` | PWB's **marker write** `str w9,[x20,#0x298]` inside PWB's injected setup routine (mem `0x305970`). Hooked for M (v0.4): replay the store + set `pwb_encounter`. Its branch sits inside PWB's 32-byte `0x305AB0` record (intentional, whitelisted overlap). | `str w9,[x20,#0x298]` |
| `0xA9C650` | `0xA9C750` | **Model-joint function** entry (recomp Eevee `0xA9C700`). `x0`=model. Hooked for C (missing-resource guard). | `sub sp,sp,#0x70` |
| `0x319EC4` | `0x319FC4` | Next-state write (`str w8,[x19,#0x68]`) in the **after-battle processor** (entry `0x319A60`, Eevee `0x319BC0`). Hooked for A4: `evolve_pending && w8==4 → w8=1` (the native evolution-check state). | `str w8,[x19,#0x68]` |
| `0x9E41D0` | `0x9E42D0` | **BTL_POKEPARAM reflect** fn (recomp Eevee `0x9E4280`; consistent −0xB0 drift). `x0`=battle-Pokémon object; writes HP back to its pml object `[x0+0x60]` at battle end (won or run from). Hooked to capture the **wild** Pokémon's HP. | `str x23,[sp,#-0x40]!` |

## Key functions
| Mem offset | Role |
|---|---|
| `0x28BD20` | Battle-event update (per frame). `mov x19,x0` at `0x28BD38`; `ldr w8,[x19,#0x68]` = state. |
| `0x28BF34` | State-4 (command-menu) handler. Advances state toward 5. |
| `0x9D8A30` | **EXP-eligibility predicate**. `x8=[x0+0x80]` (battle setup). Returns 1 iff `kind([x8])<=1 && [x8+0x4A4]==0 && flags[x8+0x494] bit7==0 && bit0x800==0`. The `+0x4A4` gate is the only thing blocking PWB (PWB has `+0x4A4==1`). |
| `0x9D3BA0` | **EXP amount**. Early-out `cbz` at `0x9D3BAC` on `[setup+0x4A4]` is a **null/empty-context guard — DO NOT remove** (removing it dereferenced null → crash). It still computed a real amount for PWB once eligibility passed, so A2 alone was sufficient. |
| `0x319A60` | **After-battle processor** (`x0→x19`; state `[x19+0x68]`; jump table rodata `0xF4D08C`-style at `0xF4E564`, states 0..4). State-0 handler at `0x319EAC` picks the next state from the battle result `[bd+0x508]`: `1→state 3`, else `→state 4` (state 4 skips evolution; state 1 runs it). |
| `0xA9C650` | Model-joint lookup. Reads `[model+0x192]` (byte), `[model+0x1e8]`, `[model+0x1e0]`; two tails (`0xA9C690` proceed / `0xA9C790` safe) do `ldr x8,[x0,#0x48]!; ldr x8,[x8,#0x10]; blr x8` on the resource. |

## Key fields (relative to the battle-event object `evt`, i.e. `[x0]` at `0x28BD20`)
| Offset | Meaning |
|---|---|
| `[evt+0x68]` | battle-event **state** word (0,1,2,3,4,5,…; 4 = command menu) |
| `[evt+0x574] & 0x80` | legendary **instant-end** flag. Clear it (after the menu) → the wild Pokémon faints. |
| `[evt+0x720] → [+0x68] → [+0x508]` | **result chain**. `[+0x508]`: `1` = normal/faint, `3` = fainted-no-capture. A3 writes `3`. |
| `[evt+0x562]` | special-battle time limit ("MATCH TIME"). |

## Battle-setup fields (relative to `setup = [x0+0x80]` in the predicate)
| Offset | Meaning |
|---|---|
| `[setup]` | battle **kind** (predicate requires `<=1`). |
| `[setup+0x4A4]` | byte; `0` for normal XP-eligible battles, `1` for PWB. The predicate's gate. A2 (v0.4) uses `==1` **together with** `[setup+0x494]==0` as the PWB profile; a real legendary has the `+0x494` static-encounter bits set, so it never matches. |
| `[setup+0x494]` | flags; bit `0x80` = static encounter (deny — excludes real legendaries), bit `0x800` = deny. |

## Battle-Pokémon fields (`BTL_POKEPARAM`, relative to `b = x0` in reflect `0x9E41D0`) — runtime-confirmed
| Offset | Meaning |
|---|---|
| `[b+0x78]` | species (u16; confirmed 16 = Pidgey) |
| `[b+0x7c]` | max HP (u16) |
| `[b+0x7e]` | **current HP** (u16; 0 after a KO — the A3 gate reads the captured copy) |
| `[b+0x87]` | battle-slot id (byte; 0–5 = player party, **12 = the wild Pokémon**) |
Reflect fires at battle end (KO **and** flee), so the capture also records a live HP on flee — which is exactly what lets the A3 gate reject non-KO endings.

## Model fields (relative to `model = x0` in `0xA9C650`)
| Offset | Meaning |
|---|---|
| `[model+0x192]` | byte resource flag |
| `[model+0x1e8]` | resource object pointer |
| `[model+0x1e0]` | resource object pointer |
Guard **returns no-joint** (x0=0) when `model!=0 && [+0x1e0]==0 && !([+0x192]!=0 && [+0x1e8]!=0)`.

## Memory regions
| Region | Use |
|---|---|
| `0xD32BA8 .. 0xD33000` | zero-filled page padding at the end of `.text` (RX) — **code cave** (0x458 bytes; v0.4 uses `0xD32BA8..0xD32E08`, 608 B — caves A/C/ST/R/E/P/M laid out consecutively). |
| `0x1EE0F00 .. 0x1EE1000` | tail of `.bss` — **scratch** for flags/instrumentation. `adrp x16,#0x1EE0000` from the cave page = `0xD0008D70`. |

## Scratch layout (this mod's instrumentation; inert for gameplay)
`+0x34` clear-count · `+0x40` last state · `+0x44` states-seen mask · `+0x48` `[evt+0x720]` ·
`+0x50` `[+0x68]` · `+0x58` result · `+0x5c` entry-count · `+0xB0` model-joint entry-count ·
`+0xD8` guard-hit count · `+0xE0` result-rewrite count · `+0xE4` A2 PWB-match count · `+0xC8` captured wild HP · `+0xF8` **pwb_encounter** (v0.4: set by hook M, cleared by hook E — the per-encounter PWB identity; hooks **A, A2 and C** all gate on it as of v0.4.1) · `+0xFC` armed · `+0xFD` done · `+0xFE` have (wild HP captured) · `+0xFF` evolve_pending (A4). The state-0 reset zeroes `+0xFC..+0xFF` with one u32 store; `+0xF8` is a separate u32 slot.

## Base PWB1 (RicoSantos) — for reference
Injected routine at mem `0x305970` (pchtxt `0x305A70`, `FD7BBBA9…`), entered via a `bl`
patched at mem `0x305934` (pchtxt `0x305A34`). It reuses the special/legendary battle
system and sets config values; it also NOPs mem `0x2FDF34`/`0x2FDF80` (pchtxt
`0x2FE034`/`0x2FE080`) in a battle-teardown loop. Within this routine it writes a marker
`str w9,[x20,#0x298]` at mem `0x3059B8` **once per synthesized encounter** — hook M (v0.4)
replays that store and sets `pwb_encounter`, giving every other hook a reliable
PWB-only, per-encounter identity.

PWB forces wild encounters into the special-battle type (`mov w8,#9` at `0x28BE84`) and reaches
the marker-writing setup (`0x305970`) via a retargeted `bl` at `0x305934` inside a
**virtually-dispatched** function (`0x305784`, no direct callers) — so a pure static call graph
can't prove the marker is exclusive to ordinary-wild encounters. PWB keys its own
kind-9-vs-10 choice and state patch on the **native** field `[evt+0x735]` (it only reads,
never writes it), which is the candidate discriminator to confirm on a real static encounter.
See `WBEXP_STATIC_CALLGRAPH.md`.
