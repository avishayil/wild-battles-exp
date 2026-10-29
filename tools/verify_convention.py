#!/usr/bin/env python3
"""Verify the IPSwitch address convention for pwb1_original.pchtxt against a
vanilla decompressed NSO: file_off = pchtxt_addr + 0x100.

For every record: vanilla bytes must DIFFER from patch bytes, and both must
disassemble as plausible AArch64. Prints a side-by-side diff per record.

Usage: python3 -I verify_convention.py <pchtxt> <main_dec.bin>
"""
import sys
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

FILE_OFF_DELTA = 0x100

def parse_pchtxt(path):
    recs = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('@'):
            continue
        addr_s, hex_s = line.split(None, 1)
        recs.append((int(addr_s, 16), bytes.fromhex(hex_s.strip())))
    return recs

def main():
    pchtxt, binpath = sys.argv[1], sys.argv[2]
    blob = Path(binpath).read_bytes()
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.skipdata = True
    ok = bad = 0
    for addr, patch in parse_pchtxt(pchtxt):
        off = addr + FILE_OFF_DELTA
        vanilla = blob[off:off + len(patch)]
        differs = vanilla != patch
        # disassemble both streams at the pchtxt address
        def dis(b):
            return ['{:08x}: {:<8s} {}'.format(i.address, i.mnemonic, i.op_str)
                    for i in md.disasm(b, addr)]
        v_dis, p_dis = dis(vanilla), dis(patch)
        n_insn = len(patch) // 4
        v_valid = sum(1 for l in v_dis if '.byte' not in l)
        status = 'OK ' if differs and v_valid == n_insn else 'WARN'
        if status == 'OK ':
            ok += 1
        else:
            bad += 1
        print(f'[{status}] 0x{addr:08X} len={len(patch):3d} differs={differs} '
              f'vanilla_valid_insns={v_valid}/{n_insn}')
        for i in range(max(len(v_dis), len(p_dis))):
            v = v_dis[i] if i < len(v_dis) else ''
            p = p_dis[i] if i < len(p_dis) else ''
            print(f'    V {v:<60s} | P {p}')
    print(f'\n{ok} records OK, {bad} records WARN (convention: file_off = addr + 0x{FILE_OFF_DELTA:X})')

if __name__ == '__main__':
    main()
