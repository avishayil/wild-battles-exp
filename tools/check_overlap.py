#!/usr/bin/env python3
"""Assert every record of a new pchtxt is disjoint from every record of the
existing pwb1 mod (and that both target the same nsobid).

Usage: python3 -I check_overlap.py <new.pchtxt> <pwb1.pchtxt>
Exits nonzero on any overlap or nsobid mismatch.
"""
import sys
from pathlib import Path

def parse(path):
    nsobid, recs = None, []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith('@nsobid-'):
            nsobid = line[len('@nsobid-'):]
        elif line and not line.startswith('@') and not line.startswith('//'):
            a, h = line.split(None, 1)
            addr = int(a, 16)
            recs.append((addr, addr + len(bytes.fromhex(h.strip()))))
    return nsobid, recs

new_id, new = parse(sys.argv[1])
old_id, old = parse(sys.argv[2])
fail = False
if new_id != old_id:
    print(f'nsobid mismatch: {new_id} vs {old_id}')
    fail = True
for a0, a1 in new:
    for b0, b1 in old:
        if a0 < b1 and b0 < a1:
            print(f'OVERLAP: new [0x{a0:X},0x{a1:X}) vs pwb1 [0x{b0:X},0x{b1:X})')
            fail = True
if fail:
    sys.exit(1)
print(f'OK: {len(new)} new record(s) disjoint from {len(old)} pwb1 record(s); same nsobid.')
