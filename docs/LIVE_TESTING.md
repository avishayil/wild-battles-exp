# Live gdbstub testing on Eden (macOS / MoltenVK)

How to observe the mod's scratch instrumentation live on the fragile Eden nightly
(`de7e6e01d4-master`, MoltenVK, Apple Silicon). Every rule here was learned the hard way on
2026-11-01 — follow it exactly and a session "just works" without crashing or hanging Eden.

The AI never launches Eden; the owner does. The AI only reads over the stub and drives the
read-only observer. **Reads only: never software breakpoints, and the reader never sends `$c`.**

## Status (2026-11-01): two SEPARATE findings — don't conflate them
1. **MoltenVK device loss — RESOLVED.** The `Vulkan::MasterSemaphore::Wait`→`abort` crashes
   (`Vulkan::Device::ReportLoss()` → `VK_ERROR_DEVICE_LOST`) were caused by launching **without**
   the MoltenVK stability env vars — a Finder double-click doesn't set them. Launching with
   `MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1 MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0` makes **normal
   gameplay stable** (owner-confirmed). This nightly (`de7e6e01d4-master`) is **fine for play.**
   The supported local startup is **`~/Launch Eden.command`** (it sets both vars and launches the
   app); do not double-click the `.app` directly. Keep the GDB stub **disabled** for ordinary play.
2. **GDB-stub observation — still limited, and this is largely EXPECTED, not a broken build.**
   That `m`/`qXfer` reads aren't serviced while a `$c` is outstanding is standard GDB **all-stop**
   behavior (continue stays outstanding until the target stops). This build's `qSupported` this
   session was `PacketSize=4000;qXfer:features:read+;qXfer:threads:read+;qXfer:libraries:read+;
   vContSupported+;QStartNoAckMode+` — **no `QNonStop+`**, so non-stop reads-while-running are not
   advertised. The earlier Eden build tolerated a non-standard "`$c` then poll `m`" workflow; this
   one does not. The **repeated early-boot stops** are a *further, separate* issue. **Do not
   attribute the debugger limits to MoltenVK, and the graphics fix is NOT proof that GDB
   observation now works.** A future *bounded* experiment (not now, not a continue-pump): a
   standards-compliant single client doing continue → interrupt (protocol `\x03`) → read while
   stopped → resume; viable because the mod already records results in scratch. First check
   `qSupported` for `QNonStop+` before assuming non-stop is available.

## This build's gdbstub quirks (why the steps are what they are)
- **Boot present-crash (resolved — see Status #1):** without the MoltenVK env vars the GPU present
  path aborts at boot; always launch via `~/Launch Eden.command`. This is a *graphics* issue,
  distinct from the gdbstub behavior below.
- **Boots halted:** with gdbstub on, the title halts at boot until a client sends `$c`.
- **`$c` blocks reads:** after a client sends `$c`, the stub won't answer `m`/`qXfer` until a
  stop → the *reader* must never `$c`. A throwaway **kick** client does the one `$c` and leaves.
- **Single connection, re-listens only on a clean close:** killing a client mid-packet (or one
  that had sent `$c`) **wedges** the stub (no re-listen → reboot). Clean closes are fine.
- **`monitor get info` is empty** → resolve the module base via `qXfer:libraries:read`
  (main NSO = `beluga.nss`, the module whose span to the next is exactly `0x1EE1000`;
  scratch = base + `0x1EE0F00`).
- **Config clobber:** Eden rewrites `use_gdbstub` in `qt-config.ini` from its in-memory GUI
  state on launch. Toggle it in the **GUI** (Emulation → Configure → Debug), not the file.
- **Cache:** the real shader/pipeline cache is `~/.cache/eden/shader/` (NOT
  `~/.local/share/eden/shader/`). Keep it for fast boots; only clear it for a genuine
  stale-cache boot crash.

## Session steps
1. **(owner)** Launch Eden from a terminal with the MoltenVK vars:
   ```sh
   MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1 MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0 \
     ~/Applications/eden.app/Contents/MacOS/eden
   ```
2. **(owner)** Enable the GDB stub: Emulation → Configure → Debug → **Enable GDB Stub** (`:6543`).
3. **(AI)** Start the attach orchestrator (waits for the stub, kicks past boot, attaches):
   ```sh
   tools/live_attach.sh --species 5        # read-only observer; add --max-seconds etc. as needed
   ```
4. **(owner)** Boot the Let's Go title. It'll blink at boot (the kick continues it), then you
   reach the controller screen → press a button → load the save → play.
5. **(AI)** The observer resolves the base and logs per-encounter `slot/species/maxhp/rewrite`,
   printing a strict-gate verdict (all KO species `slot==12 && maxhp>0`) at the caps.
6. **(AI)** Stop the observer when done — any signal triggers a **clean** socket close (safe;
   it never `$c`'d, so the stub re-listens).
7. **(owner)** Disable the GDB stub in the GUI (or the next casual launch hangs at boot).

## Tools
- `tools/live_attach.sh` — the orchestrator (kick + attach), with all rules encoded.
- `tools/e2e_autoplay.py` — the read-only observer (`--input none`), base resolution via
  `qXfer:libraries`, per-species logging + verdict; `--no-resume` (attach to a running game),
  clean-exit on any signal. `--input keystroke` can mash A via `osascript` (needs Eden
  frontmost + Accessibility) but is optional — the owner playing the battles works the same.

## Autonomous harness (pump-driven) — `tools/e2e_autoplay_pump.py`
The read-only observer **freezes** on this build: the guest halts at every battle-scene stop
(boot, encounter, menu, turn) and needs `$c` servicing. `e2e_autoplay_pump.py` is a throwaway
capture that continuously pumps `$c` (so the guest never freezes) and samples the EXP scratch at
each stop, while driving input via `osascript` — a fully autonomous wild-battle player:
- boot: the base-resolve loop pumps past "launching…"; `--boot-nav-taps N` A-taps through
  controller-select + title + save-load into the overworld.
- roam: `--walk-nudge` HOLDS WASD (the left-stick mapping) across a run-window, cycling all 4
  directions, to walk the grass and trigger spawns (an instantaneous tap never lands because the
  guest is stopped most of the time — input must be *held/tapped across* a `$c` run-window).
- battle: a clean A down→up each tick (`pump_tap`) advances Fight → move → KO → EXP → end.
- records per-encounter `slot/species/maxhp/result/rw` (species is only valid after the KO
  reflect at `state 8`; the post-transition read captures it) and prints the strict-gate verdict;
  `--quit-when-done` Ctrl+Q's and auto-clicks the "quit?" dialog's Yes.
- Prereqs: Accessibility granted to the app running it, Eden frontmost, GDB stub on.
- NOT read-only (it sends `$c` by design); a one-off research capture, not shipped.

### Strict-gate live-accept evidence (2026-11-01, Eden `de7e6e01d4-master`)
Gathered autonomously by the harness (and the earlier read runs) on the **current** build —
previously we only had the older-build v0.5 fixture. Across runs, every wild KO had **`slot==12`
and `maxhp>0`** (`result=3`, the wild-KO-no-capture path; `rw` incrementing = A3 rewrite firing):

| species (natdex) | slot | maxhp | verdict |
|---|---|---|---|
| 13 Weedle | 12 | 15 | OK |
| 16 Pidgey | 12 | 15/17 | OK |
| 19 Rattata | 12 | 15 | OK |
| 43 Oddish | 12 | 15/16 | OK |

4 distinct species, `slot==12` on every KO → the live-accept the reviewer parked strict-gate
promotion on is now satisfied on this build. (Promotion remains the owner's call.)
