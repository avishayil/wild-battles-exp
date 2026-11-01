#!/usr/bin/env python3
"""e2e_autoplay_pump.py - FULLY AUTONOMOUS wild-battle harness for the fragile Eden build
(de7e6e01d4-master) that halts the guest at every battle-scene stop.

It combines, in one single-threaded loop:
  * a continue-PUMP: each tick sends $c (so the guest advances through the stops that would
    otherwise freeze it), then stops (spontaneously or via a \\x03 interrupt) and samples the
    Wild Battles EXP scratch via read_state(). This is why it works where the read-only
    observer froze. It is NOT read-only (it sends $c, by design) and is a throwaway capture.
  * autonomous INPUT: osascript keystrokes (reused from e2e_autoplay) - mashes A through the
    command menu / move pick / battle text to KO the wild Pokemon; overworld spawns walk into
    the stationary player (Let's Go), so no walking is needed (optional --walk-nudge).
  * per-species KO logging + the strict-gate verdict (slot==12 && maxhp>0), then an optional
    graceful quit.

CAVEATS (this is the fragile end of the spectrum, by the owner's choice):
  * Blind, frame-timed keystrokes: input may miss; tune --tick-seconds / --battle-taps.
  * The pump interrupt/resume cycling can occasionally wedge this build's stub -> reboot Eden.
  * Needs Eden frontmost + Accessibility granted for keystrokes to register.

PREREQ (owner): launch via ~/Launch Eden.command (MVK vars), enable the GDB stub, boot the
title. The pump drives it from boot onward - you do NOT need to reach gameplay first.

Usage: python3 -I tools/e2e_autoplay_pump.py --species 5 --quit-when-done
"""
import argparse, signal, socket, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
from e2e_autoplay import (Stub, resolve_base, read_state, SCRATCH_OFF, APP,
                          A_BTN, B_BTN, UP, DOWN, LEFT, RIGHT,
                          tap, focus_eden, quit_eden, accessibility_ok, frontmost)

def _read_stop(st, timeout):
    """Read one packet within `timeout`s; None on timeout (== guest still running free)."""
    try:
        return st._rd(timeout)
    except socket.timeout:
        return None

def ensure_stopped(st):
    """Bring the guest to a known STOPPED state (interrupt; swallow the stop reply)."""
    st.s.sendall(b'\x03')
    _read_stop(st, 2.0)

def pump_advance(st, run_window):
    """Precondition: stopped. Resume, let the guest run ~run_window (processing any queued
    keystroke), then stop. Postcondition: stopped."""
    st.s.sendall(b'$c#63')
    if _read_stop(st, run_window) is None:      # no spontaneous stop -> still running
        st.s.sendall(b'\x03')                   # interrupt (a signal, NOT a breakpoint)
        _read_stop(st, 2.0)

def pump_tick(st, sb, run_window):
    """pump_advance, then sample the scratch at the resulting stop."""
    pump_advance(st, run_window)
    return read_state(st, sb)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--species', type=int, default=5, help='distinct KO species target')
    ap.add_argument('--max-seconds', type=int, default=1200)
    ap.add_argument('--max-encounters', type=int, default=30)
    ap.add_argument('--tick-seconds', type=float, default=0.7, help='guest run-window per pump tick')
    ap.add_argument('--battle-taps', type=int, default=1, help='A-taps queued per battle tick')
    ap.add_argument('--walk-nudge', action='store_true', help='tap a direction in the overworld')
    ap.add_argument('--quit-when-done', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='send NO keystrokes; pump+read+plan only')
    a = ap.parse_args()

    try:
        st = Stub()
    except OSError as e:
        print("no gdbstub on :6543 (enable it + boot the title) — %s" % e); sys.exit(2)

    closed = {'v': False}
    def _close():
        if not closed['v']:
            closed['v'] = True
            try: st.s.sendall(b'$c#63'); time.sleep(0.2)   # leave the guest RUNNING
            except Exception: pass
            try: st.s.close()
            except Exception: pass
    def _bye(*_): _close(); sys.exit(0)
    for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try: signal.signal(_sig, _bye)
        except Exception: pass

    try:
        _run(st, a)
    finally:
        _close()

def _run(st, a):
    st.cmd('qSupported:hwbreak+'); st.cmd('?')
    ensure_stopped(st)

    # resolve the module base (beluga.nss maps a few seconds into boot); pump if not yet mapped
    base = None
    for i in range(200):
        base = resolve_base(st)
        if base is not None:
            break
        pump_advance(st, a.tick_seconds)       # advance boot until the main module maps
    if base is None:
        print("could not resolve module base (is the title booting?)"); sys.exit(2)
    sb = base + SCRATCH_OFF
    print(f"connected base=0x{base:x}; scratch=0x{sb:x}; tick={a.tick_seconds}s dry_run={a.dry_run}",
          flush=True)

    if not a.dry_run:
        if not accessibility_ok():
            print("ACCESSIBILITY not granted — keystrokes will no-op. Grant it, then rerun."); sys.exit(3)
        print("focusing eden…", "ok" if focus_eden() else "WARN not frontmost", flush=True)

    t0 = time.time()
    elapsed = lambda: time.time() - t0
    ko = {}
    encounters = 0
    last_pe = 0
    walk_cycle = [RIGHT, LEFT, UP, DOWN]
    last_log = 0

    while len(ko) < a.species and encounters < a.max_encounters and elapsed() < a.max_seconds:
        # queue input for THIS tick's run-window, then advance+sample
        in_battle = (last_pe == 1)
        if not a.dry_run and not frontmost().lower().startswith(APP):
            focus_eden()
        if in_battle:
            for _ in range(max(1, a.battle_taps)):
                tap(a.dry_run, A_BTN)
        elif a.walk_nudge:
            tap(a.dry_run, walk_cycle[encounters % len(walk_cycle)])

        s = pump_tick(st, sb, a.tick_seconds)
        if s is None:
            continue

        if elapsed() - last_log > 4:
            print(f"[{int(elapsed())}s] state={s['state']} pe={s['pe']} species={s['species']} "
                  f"slot={s['slot']} wild_hp={s['wild_hp']} rw={s['rw']}", flush=True)
            last_log = elapsed()

        if s['pe'] == 1:                                   # in a PWB battle
            if last_pe == 0:
                encounters += 1
                print(f"[{int(elapsed())}s] >>> encounter #{encounters} (species={s['species']})", flush=True)
            last_pe = 1
            continue

        if last_pe == 1:                                   # battle just ended -> record
            sp = s['species']
            if sp:
                ko.setdefault(sp, dict(slot=s['slot'], maxhp=s['maxhp'], rewrote=s['rw'],
                                       result=s['result'], have=s['have']))
                print(f"[{int(elapsed())}s] <<< battle end: species={sp} slot={s['slot']} "
                      f"maxhp={s['maxhp']} result={s['result']} rw={s['rw']} "
                      f"(distinct KO: {len(ko)}/{a.species})", flush=True)
            last_pe = 0

    # ---- summary ----
    print("\n==== autoplay (pump) summary ====")
    print(f"elapsed={int(elapsed())}s encounters={encounters} distinct_KO_species={len(ko)}")
    all_ok = bool(ko)
    for sp, r in sorted(ko.items()):
        ok = (r['slot'] == 12 and r['maxhp'] > 0 and sp != 0)
        all_ok &= ok
        print(f"  species={sp:<5} slot={r['slot']:<3} maxhp={r['maxhp']:<4} result={r['result']} "
              f"rw={r['rewrote']}  {'OK' if ok else 'ANOMALY (slot!=12 or maxhp<=0)'}")
    print(f"strict-gate evidence: {'ALL species slot==12 & maxhp>0' if all_ok else 'INCOMPLETE/ANOMALOUS'}")

    if a.quit_when_done:
        s = pump_tick(st, sb, a.tick_seconds)
        if s and s['pe'] == 0:
            print("overworld — quitting eden gracefully"); quit_eden(a.dry_run)
        else:
            print("NOT quitting: not safely at overworld")

if __name__ == '__main__':
    main()
