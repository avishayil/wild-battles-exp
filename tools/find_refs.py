#!/usr/bin/env python3
"""Find references relevant to the XP predicate hunt in the decompressed NSO.

Modes:
  bl <text.bin> <target_hex>        - find `bl target` call sites in .text
  ptr <main_dec.bin> <value_hex>    - find little-endian 64-bit pointers to value
                                      (vtable entries; reports file off and mem off)
  fieldstr <text.bin> <imm_hex>     - find str/strb/ldr/ldrb with unsigned imm to
                                      that field offset (who writes/reads +imm)
"""
import sys
import struct
from pathlib import Path

mode, path, val = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3], 16)
raw = path.read_bytes()

if mode == 'bl':
    for pos in range(0, len(raw) - 3, 4):
        w = struct.unpack_from('<I', raw, pos)[0]
        if (w & 0xFC000000) == 0x94000000:  # BL
            imm = w & 0x03FFFFFF
            if imm & 0x02000000:
                imm -= 0x04000000
            if pos + imm * 4 == val:
                print(f'bl at 0x{pos:08X} -> 0x{val:08X}')
elif mode == 'ptr':
    needle = struct.pack('<Q', val)
    i = raw.find(needle)
    while i != -1:
        if i % 8 == 0:
            print(f'ptr at file 0x{i:08X} (mem 0x{i - 0x100:08X}) -> 0x{val:08X}')
        i = raw.find(needle, i + 1)
elif mode == 'fieldstr':
    # 32-bit reg, unsigned-offset forms. imm12 scaled by 4 for word, 1 for byte.
    for pos in range(0, len(raw) - 3, 4):
        w = struct.unpack_from('<I', raw, pos)[0]
        op = w & 0xFFC00000
        imm12 = (w >> 10) & 0xFFF
        name = None
        if op == 0xB9000000 and imm12 == val // 4 and val % 4 == 0:
            name = 'str w (word)'
        elif op == 0xB9400000 and imm12 == val // 4 and val % 4 == 0:
            name = 'ldr w (word)'
        elif op == 0x39000000 and imm12 == val:
            name = 'strb'
        elif op == 0x39400000 and imm12 == val:
            name = 'ldrb'
        if name:
            print(f'{name:12s} at 0x{pos:08X}  insn={w:08X}')
else:
    sys.exit('unknown mode')
