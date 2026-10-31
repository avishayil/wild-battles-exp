#!/usr/bin/env python3
"""Workstream F1 probe: capture the message-number setter 0xA6EF80 (read-only).

0xA6EF80 appends a numeric word w1 to a message context x0 (it's the formatter behind
"<Pokemon> got N Exp. Points!"). It has 55 callers, so we log into an 8-entry RING BUFFER in the
scratch page: per call, (w1 = the number, x30 low32 = the caller's return address). After one
wild KO, the ring holds the last 8 message-numbers; the entry whose number == the on-screen EXP
(e.g. 14) tells us the caller, and its disassembly gives the dataflow that produced the amount.

The cave uses only volatile temps (x9,x10,x16,x17 — recomputed/caller-saved) and preserves the
live inputs x0,w1,x30; no stack. Emits v0.6 unified + this one hook in the free cave tail.

  python3 -I tools/probe_f1.py --text text.bin --pwb pwb1.pchtxt --out probe_f1.pchtxt

Scratch: +0x00 count(u32); ring at +0x60, 8 * {w1 @+0, x30lo @+4}. Read with probe_f1_read.py.
"""
import argparse, struct, sys, os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_patch as bp

HOOK = 0xA6EF80
RING = 0x60   # scratch offset of the ring (8 entries * 8 bytes)

# extra AArch64 encoders (verified by capstone in the build below)
def and_imm7_w(rd, rn):   return 0x12000800 | (rn << 5) | rd          # and Wd,Wn,#7
def lsl3_w(rd, rn):       return 0x531D7000 | (rn << 5) | rd          # lsl Wd,Wn,#3  (ubfm 29,28)
def add_uxtw_x(rd, rn, rm): return 0x8B204000 | (rm << 16) | (rn << 5) | rd  # add Xd,Xn,Wm,uxtw

def cave_f1(text, base):
    w = [bp.ADRP_SCRATCH, bp.ADD_F00,             # x16 = scratch
         bp.ldr_w(17, 16, 0x00),                  # w17 = count
         and_imm7_w(9, 17),                       # w9 = count & 7
         lsl3_w(9, 9),                            # w9 = index * 8
         bp.addi_w(9, 9, RING),                   # w9 += ring base
         add_uxtw_x(10, 16, 9),                   # x10 = scratch + off (entry ptr)
         bp.str_w(1, 10, 0x00),                   # entry.number = w1
         bp.str_w(30, 10, 0x04),                  # entry.caller = x30 low32
         bp.addi_w(17, 17, 1), bp.str_w(17, 16, 0x00),  # count++
         bp.disp(text, HOOK)]                     # displaced original (ldrsb w8,[x0,#3])
    return w + [bp.ret_branch(w, base, HOOK + 4)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True); ap.add_argument('--pwb', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    text = Path(a.text).read_bytes()
    caves = bp.lay_out(text, 'classic'); bp.verify_caves(text, caves)
    recs = bp.load_pwb(a.pwb) + bp.variant_records('main', caves)
    base = max(c['base'] + len(c['words']) * 4 for c in caves.values())
    w = cave_f1(text, base)
    assert w[-2] == bp.disp(text, HOOK), 'displaced mismatch'
    # self-check: disassemble the cave and sanity-print it
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    body = b''.join(struct.pack('<I', x) for x in w)
    print("cave_f1 @0x%X:" % base)
    for i in md.disasm(body, base):
        print("  0x%X %-7s %s" % (i.address, i.mnemonic, i.op_str))
    recs.append((HOOK, struct.pack('<I', bp.b(HOOK, base))))
    recs.append((base, body))
    assert base + len(w) * 4 <= 0xD33000
    bp.overlap_check('probe_f1', recs)
    bp.emit(recs, a.out,
            ["// Wild Battles EXP - F1 probe (research; read-only): log 0xA6EF80 message numbers.",
             "// pchtxt addr = memory offset + 0x100."])
    print("wrote", a.out, "(%d records)" % len(recs))

if __name__ == '__main__':
    main()
