#!/usr/bin/env python3
"""Research probe (Workstream F): find where PWB's awarded EXP amount is computed.

Round 1 disproved the obvious candidate: `0x9D3BA0` returns 0 for PWB (and trainer) battles and
its result is discarded, so it is NOT the amount source. PWB's EXP is awarded on the
*eligible-predicate* branch (predicate `0x9D8A30`, forced true by A2, callers `0x9F28E8` /
`0x9F619C`), through a reward path (`0xa089e0` a candidate). This round instruments that branch
to show which path runs for a PWB wild KO and starts pinning the amount — read-only.

It emits the normal v0.6 UNIFIED build plus logging hooks in the free cave tail. Deploy this in
place of the normal mod for the measurement run.

  python3 -I tools/probe_exp.py --text text.bin --pwb pwb1.pchtxt --out probe_exp.pchtxt

Each site logs a hit counter and (optionally) one 32-bit register into the scratch page; read
with tools/probe_exp_read.py.
"""
import argparse, struct, sys, os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # find the sibling module under -I
import build_patch as bp   # encoders, layout, emit, disp, b, ret_branch

# (hook site, label, register to log or None, scratch value-slot). Counter is at slot+4.
# Sites are instructions that are position-independent to displace (reg-reg / ldp / stp-prologue).
SITES = [
    (0x9F28F0, 'pred_caller_9F28E8_eligible', 0,    0x10),  # fall-through after the eligible tbz; w0=forced result
    (0x9F61A4, 'pred_caller_9F619C_eligible', 0,    0x18),  # fall-through after the eligible tbz
    (0xA089E0, 'a089e0_reward_entry',         1,    0x20),  # candidate reward fn entry; w1 = slot arg
]

def probe_cave(text, base, site, reg, slot):
    w = [bp.STP_1617, bp.ADRP_SCRATCH, bp.ADD_F00]
    if reg is not None:
        w.append(bp.str_w(reg, 16, slot))                        # log the register (read-only)
    w += [bp.ldr_w(17, 16, slot + 4), bp.addi_w(17, 17, 1), bp.str_w(17, 16, slot + 4)]  # count++
    w += [bp.LDP_1617, bp.disp(text, site)]                      # restore + displaced original
    return w + [bp.ret_branch(w, base, site + 4)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    ap.add_argument('--pwb', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    text = Path(a.text).read_bytes()

    caves = bp.lay_out(text, 'classic')
    bp.verify_caves(text, caves)
    recs = bp.load_pwb(a.pwb) + bp.variant_records('main', caves)

    base = max(c['base'] + len(c['words']) * 4 for c in caves.values())
    for site, label, reg, slot in SITES:
        w = probe_cave(text, base, site, reg, slot)
        assert w[-2] == bp.disp(text, site), (hex(site), 'displaced mismatch')
        recs.append((site, struct.pack('<I', bp.b(site, base))))
        recs.append((base, b''.join(struct.pack('<I', x) for x in w)))
        base += len(w) * 4
    assert base <= 0xD33000, "probe caves overflow .text padding"
    bp.overlap_check('probe', recs)

    bp.emit(recs, a.out,
            ["// Wild Battles EXP - EXP-SEAM PROBE round 2 (research; read-only).",
             "// v0.6 unified + logs the eligible-predicate reward branch (which path runs).",
             "// pchtxt addr = memory offset + 0x100."])
    print("wrote", a.out, "(%d records)" % len(recs))
    for site, label, reg, slot in SITES:
        print("  +0x%02X %s (reg w%s)" % (slot, label, reg))

if __name__ == '__main__':
    main()
