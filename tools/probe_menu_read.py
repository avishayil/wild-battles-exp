#!/usr/bin/env python3
"""probe_menu_read.py - read-only poller for the throwaway menu id<->button probe
(tools/probe_menu.py). Prints the scratch press-counter and last chosen-button id as
they change, so each command button can be labeled by pressing it in a wild battle.

Reads only. Never sends $c (attaches to an already-running game, like e2e_autoplay
--no-resume). Clean socket close on any signal (safe for the single-connection stub).

Usage: python3 -I tools/probe_menu_read.py     # after the owner boots into gameplay
"""
import argparse, signal, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
from e2e_autoplay import Stub, resolve_base, SCRATCH_OFF

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=8.0,
                    help='poll for this long then exit cleanly (0 = until signal)')
    a = ap.parse_args()
    st = Stub()
    signal.signal(signal.SIGINT, lambda *_: (st.s.close(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (st.s.close(), sys.exit(0)))
    base = None
    for _ in range(40):                        # ~12s to resolve base (guest already running)
        base = resolve_base(st)
        if base is not None:
            break
        time.sleep(0.3)
    if base is None:
        print("could not resolve module base (is the title in gameplay?)"); st.s.close(); sys.exit(2)
    sb = base + SCRATCH_OFF
    print(f"connected base=0x{base:x}; scratch=0x{sb:x}")
    d0 = st.rd(sb, 8)
    if len(d0) == 8:
        c0, i0 = struct.unpack_from('<II', d0, 0)
        print(f"  current: press counter={c0}, last button id={i0} (0x{i0:x})")
    print(f"  watching for {a.seconds}s — press a command button now…")
    last = None
    t_end = time.time() + a.seconds
    while a.seconds == 0 or time.time() < t_end:
        d = st.rd(sb, 8)
        if len(d) == 8:
            cnt, bid = struct.unpack_from('<II', d, 0)
            if (cnt, bid) != last:
                print(f"  press #{cnt}: button id = {bid} (0x{bid:x})")
                last = (cnt, bid)
        time.sleep(0.3)
    st.s.close()
    print("  (window ended, closed cleanly)")

if __name__ == '__main__':
    main()
