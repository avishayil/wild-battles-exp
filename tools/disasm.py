#!/usr/bin/env python3
"""Disassemble a window of the carved .text (addresses = NSO memory offsets).

Usage: python3 -I disasm.py <text.bin> <start_hex> <end_hex> [--func]
With --func, expand the window to the enclosing function: scan back for a
prologue (pacibsp / stp x29,x30,[sp,#-N]! / sub sp) preceded by ret/b, and
forward to the first ret at the same nesting.
"""
import sys
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

blob = Path(sys.argv[1]).read_bytes()
start, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
func = '--func' in sys.argv

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.skipdata = True

def insn_at(a):
    for i in md.disasm(blob[a:a+4], a):
        return i
    return None

if func:
    # scan back for a prologue
    a = start
    while a > max(0, start - 0x4000):
        i = insn_at(a)
        if i and (i.mnemonic == 'pacibsp' or
                  (i.mnemonic == 'stp' and 'x29, x30' in i.op_str and '!' in i.op_str) or
                  (i.mnemonic == 'sub' and i.op_str.startswith('sp, sp'))):
            prev = insn_at(a - 4)
            if prev and prev.mnemonic in ('ret', 'b', 'br', 'brk') or prev is None:
                start = a
                break
        a -= 4
    else:
        start = a
    # forward to first ret/ b after end
    a = end
    while a < min(len(blob), end + 0x4000):
        i = insn_at(a)
        if i and i.mnemonic in ('ret',):
            end = a + 4
            break
        a += 4

for i in md.disasm(blob[start:end], start):
    print(f'0x{i.address:08x}: {i.mnemonic:<8s} {i.op_str}')
