#!/usr/bin/env python3
"""probe_menu.py - throwaway instrumentation patch to pin the battle command-menu
id<->button map on PK 1.0.2 (research/CATCH_STEP1_MENU_RE.md follow-up #1).

NOT a shipped mod. Deployed STANDALONE (without the Wild Battles EXP mod). It hooks
CMD_DECIDE just after it loads the chosen-button id into w20 (mem 0xab1e34,
`ldr w20,[x0,#4]`), copies that id to the scratch page, and returns. A register can't
be read over the gdbstub without a (banned) breakpoint, so we capture it to scratch and
poll scratch read-only instead - the standard safe technique here.

Scratch layout (module+0x1EE0F00; whole page free since the main mod isn't loaded):
  +0x00  u32  press counter (increments on every menu decision)
  +0x04  u32  last chosen-button id (w20)

Usage:
  python3 -I tools/probe_menu.py --text ../work/text.bin --out ../work/wbexp_menuprobe.pchtxt
Then (owner) deploy it alone, open a wild battle, press one command button at a time;
read scratch +0x00/+0x04 between presses to label each button's id.
"""
import argparse, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir

# reuse the audited encoders + constants (import-safe: main() is __main__-guarded)
from build_patch import (NSOBID, PCHTXT_OFF, CAVE_BASE, CAVE_END_PAGE,
                          STP_1617, LDP_1617, ADRP_SCRATCH, ADD_F00,
                          ldr_w, str_w, addi_w, b, MD)

HOOK_MENU = 0xab1e34          # CMD_DECIDE: ldr w20,[x0,#4]  (w20 = chosen-button id)
PREIMAGE  = 0xB9400414        # ldr w20,[x0,#4]

def build(text):
    got = struct.unpack_from('<I', text, HOOK_MENU)[0]
    if got != PREIMAGE:
        raise SystemExit("preimage mismatch at 0x%X: got 0x%08X want 0x%08X (wrong NSO?)"
                         % (HOOK_MENU, got, PREIMAGE))
    base = CAVE_BASE
    body = [
        ldr_w(20, 0, 4),            # 0  replicate displaced insn: w20 = id (event+4)
        STP_1617,                   # 1  save x16,x17
        ADRP_SCRATCH,               # 2  adrp x16,#0x1EE0000  (PC-rel from cave page 0xD32000)
        ADD_F00,                    # 3  add  x16,x16,#0xf00  -> x16 = scratch 0x1EE0F00
        ldr_w(17, 16, 0x00),        # 4  counter
        addi_w(17, 17, 1),          # 5  ++
        str_w(17, 16, 0x00),        # 6  store counter
        str_w(20, 16, 0x04),        # 7  lastid = w20
        LDP_1617,                   # 8  restore x16,x17
    ]
    body.append(b(base + len(body) * 4, HOOK_MENU + 4))  # 9  return to the cmp at 0xab1e38
    end = base + len(body) * 4
    if end > CAVE_END_PAGE:
        raise SystemExit("cave overruns page: 0x%X > 0x%X" % (end, CAVE_END_PAGE))
    redirect = b(HOOK_MENU, base)                         # 0xab1e34 -> cave
    return [(HOOK_MENU, struct.pack('<I', redirect)),
            (base, b''.join(struct.pack('<I', w) for w in body))]

def selfcheck(records):
    for mem, data in records:
        print("; disasm @ 0x%08X (pchtxt 0x%08X):" % (mem, mem + PCHTXT_OFF))
        for i in MD.disasm(data, mem):
            print("    0x%08x: %-8s %s" % (i.address, i.mnemonic, i.op_str))

def emit(records, path):
    lines = [f"@nsobid-{NSOBID}", "",
             "// THROWAWAY menu id<->button probe (research/CATCH_STEP1_MENU_RE.md).",
             "// Deploy STANDALONE. scratch +0x00 press counter, +0x04 last button id.",
             "@enabled"]
    for mem, data in records:
        lines.append("%08X %s" % (mem + PCHTXT_OFF, data.hex().upper()))
    lines.append("@stop")
    Path(path).write_text("\n".join(lines) + "\n")

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    recs = build(Path(a.text).read_bytes())
    selfcheck(recs)
    emit(recs, a.out)
    print("wrote", a.out)
