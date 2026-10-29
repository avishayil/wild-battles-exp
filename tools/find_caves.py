#!/usr/bin/env python3
"""Find candidate code caves in the carved .text: 4-aligned runs of zero bytes
or NOP (d503201f) sleds of at least --min bytes, excluding pwb1's ranges.

Usage: python3 -I find_caves.py <text.bin> <pwb1.pchtxt> [--min 0x40]
Addresses printed are NSO memory offsets (same space as pchtxt records).
"""
import sys
import struct
from pathlib import Path

text = Path(sys.argv[1]).read_bytes()
MIN = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x40

excl = []
for line in Path(sys.argv[2]).read_text().splitlines():
    line = line.strip()
    if line and not line.startswith(('@', '/', '#')):
        a, h = line.split(None, 1)
        addr = int(a, 16)
        excl.append((addr, addr + len(bytes.fromhex(h.strip()))))

def excluded(a, b):
    return any(a < e1 and e0 < b for e0, e1 in excl)

runs = []
run_start = None
kind = None
for pos in range(0, len(text) - 3, 4):
    w = struct.unpack_from('<I', text, pos)[0]
    k = 'zero' if w == 0 else ('nop' if w == 0xD503201F else None)
    if k and k == kind:
        continue
    if run_start is not None and (pos - run_start) >= MIN and not excluded(run_start, pos):
        runs.append((run_start, pos, kind))
    run_start = pos if k else None
    kind = k
for a, b, k in runs:
    print(f'cave 0x{a:08X}..0x{b:08X} len=0x{b-a:X} ({k})')
print(f'{len(runs)} caves >= 0x{MIN:X} bytes (pwb1 ranges excluded)')
