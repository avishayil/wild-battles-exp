#!/usr/bin/env python3
"""pump_and_read.py - ONE-OFF capture for this fragile Eden build, where the guest halts
at every battle-scene stop and freezes unless a client services $c. It continuously
sends $c (advancing the guest through those stops so it doesn't freeze) and samples the
menu-probe scratch (+0x00 counter, +0x04 last button id) at each stop, printing the id
whenever it changes.

Run it, then navigate to the WILD-battle command menu and press buttons; each confirmed
press prints its id. This is a throwaway research capture, NOT shipped tooling, and NOT
the read-only observer (it does send $c, by design, to keep the guest alive).

Usage: python3 -I tools/pump_and_read.py [--seconds 60]
"""
import argparse, socket, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
from e2e_autoplay import Stub, resolve_base, SCRATCH_OFF

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=60.0)
    a = ap.parse_args()
    st = Stub()
    base = None
    for _ in range(20):                       # resolve base before any $c (qXfer works)
        base = resolve_base(st)
        if base is not None:
            break
        time.sleep(0.3)
    if base is None:
        print("could not resolve module base"); st.s.close(); sys.exit(2)
    sb = base + SCRATCH_OFF
    print(f"base=0x{base:x} scratch=0x{sb:x} — go to the command menu and press buttons")
    last = None
    def sample():
        nonlocal last
        d = st.rd(sb, 8)                       # m-read only valid while stopped
        if len(d) == 8:
            c, i = struct.unpack('<II', d)
            if (c, i) != last:
                print(f"  press #{c}: button id = {i} (0x{i:x})")
                last = (c, i)
    end = time.time() + a.seconds
    while time.time() < end:
        st.s.sendall(b'$c#63')                 # advance (keeps the guest from freezing)
        st.s.settimeout(0.8)
        try:
            st._rd()                           # a spontaneous stop
            sample()
            continue
        except socket.timeout:
            pass
        st.s.sendall(b'\x03')                  # running free -> interrupt to sample (not a breakpoint)
        st.s.settimeout(2.0)
        try:
            st._rd()
            sample()
        except socket.timeout:
            pass
    st.s.sendall(b'$c#63'); time.sleep(0.3); st.s.close()  # leave it running, clean close
    print("done — resumed the guest, closed cleanly")

if __name__ == '__main__':
    main()
