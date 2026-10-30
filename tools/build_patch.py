#!/usr/bin/env python3
"""
build_patch.py - regenerate the "Wild Battles EXP" pchtxt from source addresses.

Target: Pokemon: Let's Go, Pikachu! v1.0.2, program NSO build-id
        C208DB6A4EF4361F28B8402BE0F7CD9A...  (verify before use)

What this produces
------------------
The native wild-KO EXP add-on: 4 hooks + 3 code caves that make a defeated wild
Pokemon FAINT (not instant-end), survive the faint, award native EXP, and end the
battle without the catch screen.

CRITICAL ADDRESS CONVENTION (the bug that cost this project days)
----------------------------------------------------------------
Eden/IPSwitch pchtxt record addresses are FILE offsets into the decompressed NSO,
which includes the 0x100-byte NSO header. Therefore:

        pchtxt_record_address = memory_offset + 0x100

All *analysis* (disassembly of work/text.bin, branch targets, adrp pages) is done in
MEMORY-offset space. Only the emitted record address gets +0x100. Getting this wrong
makes a code cave land 0x100 low, on top of a live veneer, and corrupts the game.

Inputs
------
  text.bin   : the carved .text of the decompressed NSO (memory offset == file offset).
               text.bin[X] is the instruction at memory offset X.
               Build it per docs/REPRODUCE.md (hactool: nso0 --uncompressed, drop 0x100).
  pwb1.pchtxt: RicoSantos' base "Wild Battles" mod (to merge into the unified build).

Usage
-----
  python3 -I build_patch.py --text text.bin --pwb pwb1.pchtxt \
          --out-addon wbexp_addon.pchtxt --out-unified wild_battles_exp.pchtxt

Requires: capstone (pip install capstone) for self-verification.
"""
import argparse, struct, sys
from pathlib import Path

try:
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    MD = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
except ImportError:
    print("need capstone: pip install capstone", file=sys.stderr); sys.exit(1)

NSOBID = "C208DB6A4EF4361F28B8402BE0F7CD9A00000000000000000000000000000000"
PCHTXT_OFF = 0x100  # pchtxt record addr = mem offset + 0x100

# ----- memory offsets of the hook sites + the code cave (from static analysis) -----
HOOK_A    = 0x28BF34   # state-4 handler: ldr x20,[x1,#0x60]   (clear instant-end flag)
HOOK_C    = 0xA9C650   # model-joint fn entry: sub sp,sp,#0x70  (missing-resource guard)
HOOK_ST   = 0x28BD20   # battle-event update entry: sub sp,sp,#0x70 (reset + result rewrite)
HOOK_A2   = 0x9D8A44   # in XP predicate 0x9D8A30: cbz w9,#0x9d8a58 (bypass +0x4A4 gate)
HOOK_R    = 0x9E41D0   # BTL_POKEPARAM reflect fn entry: str x23,[sp,#-0x40]! (wild HP capture)
HOOK_E    = 0x319EC4   # after-battle processor (entry 0x319A60): str w8,[x19,#0x68] next-state write
CAVE_BASE = 0xD32BA8   # start of the loader-provided .text page padding (zero-filled, RX)
SCRATCH   = 0x1EE0F00  # safe .bss-tail scratch page (module+0x1EE0F00..0x1EE1000)

# ----- AArch64 encoders (all operate in memory-offset space) -----
def ldr_x(rt,rn,off): assert off%8==0; return 0xF9400000|((off//8)<<10)|(rn<<5)|rt
def str_x(rt,rn,off): assert off%8==0; return 0xF9000000|((off//8)<<10)|(rn<<5)|rt
def ldr_w(rt,rn,off): return 0xB9400000|((off//4)<<10)|(rn<<5)|rt
def str_w(rt,rn,off): return 0xB9000000|((off//4)<<10)|(rn<<5)|rt
def ldrb_w(rt,rn,off):return 0x39400000|(off<<10)|(rn<<5)|rt
def strb_w(rt,rn,off):return 0x39000000|(off<<10)|(rn<<5)|rt
def ldrh_w(rt,rn,off): return 0x79400000|((off//2)<<10)|(rn<<5)|rt
def addi_w(rd,rn,imm):return 0x11000000|(imm<<10)|(rn<<5)|rd
def movz_w(rd,i):     return 0x52800000|(i<<5)|rd
def movz_x(rd,i):     return 0xD2800000|(i<<5)|rd
def lslv_w(rd,rn,rm): return 0x1AC02000|(rm<<16)|(rn<<5)|rd
def orr_w(rd,rn,rm):  return 0x2A000000|(rm<<16)|(rn<<5)|rd
def cmp_i(rn,imm):    return 0x71000000|(imm<<10)|(rn<<5)|31
def tst_w(rn,rm):     return 0x6A000000|(rm<<16)|(rn<<5)|31
def bic_w(rd,rn,rm):  return 0x0A200000|(rm<<16)|(rn<<5)|rd
def cbz_x(rt,cur,t):  return 0xB4000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def cbnz_x(rt,cur,t): return 0xB5000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def cbz_w(rt,cur,t):  return 0x34000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def cbnz_w(rt,cur,t): return 0x35000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def bcond(c,cur,t):   return 0x54000000|(((t-cur)>>2 &0x7FFFF)<<5)|c
def b(cur,t):         return 0x14000000|(((t-cur)>>2)&0x3FFFFFF)
NE, HI = 1, 8
RET = 0xD65F03C0
STP_1617, LDP_1617 = 0xA9BF47F0, 0xA8C147F0    # stp/ldp x16,x17,[sp,#-0x10]!/[sp],#0x10
STP_910,  LDP_910  = 0xA9BF2BE9, 0xA8C12BEC-3  # stp/ldp x9,x10 (see verify below)
STP_910, LDP_910 = 0xA9BF2BE9, 0xA8C12BE9
# adrp x16, module+0x1EE0000 then add x16,x16,#0xf00 -> x16 = module+0x1EE0F00
# (adrp is PC-relative from the cave's page 0xD32000; 0xD0008D70 reaches 0x1EE0000)
ADRP_SCRATCH = 0xD0008D70
ADD_F00      = 0x913C0210

def disp(text, mem):  # the original instruction word displaced by a hook
    return struct.unpack_from('<I', text, mem)[0]

def ret_branch(body, base, target):
    return b(base + len(body)*4, target)

# ----- the three code caves (bodies in memory-offset space at CAVE_BASE+) -----
def cave_A(text, base):   # PoC A: clear instant-end flag [evt+0x574]&=~0x80, set armed
    A = lambda i: base+i*4
    body = [STP_1617, ldr_x(16,1,0x60), cbz_x(16,A(2),A(16)), ldr_w(17,19,0x574),
            movz_w(16,0x80), tst_w(17,16), bcond(0,A(6),A(16)), bic_w(17,17,16),
            str_w(17,19,0x574), ADRP_SCRATCH, ADD_F00, ldr_w(17,16,0x34),
            addi_w(17,17,1), str_w(17,16,0x34), movz_w(17,1), strb_w(17,16,0xFC),
            LDP_1617, disp(text,HOOK_A)]
    return body + [ret_branch(body, base, HOOK_A+4)]

def cave_C(text, base):   # PoC C: model-joint guard (recomp port); return x0=0 if resources missing
    A = lambda i: base+i*4
    Lintc, Lorig = A(14), A(23)
    return [STP_1617,ADRP_SCRATCH,ADD_F00, ldr_w(17,16,0xB0),addi_w(17,17,1),str_w(17,16,0xB0),LDP_1617,
            cbz_x(0,A(7),Lorig), ldr_x(9,0,0x1e0), cbnz_x(9,A(9),Lorig),
            ldrb_w(9,0,0x192), cbz_w(9,A(11),Lintc), ldr_x(9,0,0x1e8), cbnz_x(9,A(13),Lorig),
            STP_1617,ADRP_SCRATCH,ADD_F00, ldr_w(17,16,0xD8),addi_w(17,17,1),str_w(17,16,0xD8),LDP_1617,
            movz_x(0,0), RET, disp(text,HOOK_C), b(A(24),HOOK_C+4)]

def cave_ST(text, base):  # entry hook: reset flags@state0; result 1->3 @state5 on VERIFIED KO (one-shot)
    A = lambda i: base+i*4
    Lnot0, Lchain, Ldone = A(8), A(15), A(44)
    w = [STP_910, STP_1617, ADRP_SCRATCH, ADD_F00, ldr_w(17,0,0x68), str_w(17,16,0x40),
         cbnz_w(17,A(6),Lnot0), str_w(31,16,0xFC),     # state==0: zero armed/done/have (u32 @+0xFC)
         cmp_i(17,31), bcond(HI,A(9),Lchain),
         movz_w(9,1), lslv_w(9,9,17), ldr_w(10,16,0x44), orr_w(10,10,9), str_w(10,16,0x44),
         ldr_x(9,0,0x720), str_x(9,16,0x48), cbz_x(9,A(17),Ldone),
         ldr_x(10,9,0x68), str_x(10,16,0x50), cbz_x(10,A(20),Ldone),
         ldr_w(17,10,0x508), str_w(17,16,0x58),
         ldr_w(9,0,0x68), cmp_i(9,5), bcond(NE,A(25),Ldone),       # state == 5
         cmp_i(17,1), bcond(NE,A(27),Ldone),                        # result == 1
         ldrb_w(9,16,0xFC), cbz_w(9,A(29),Ldone),                   # armed (PWB faint forced)
         ldrb_w(9,16,0xFD), cbnz_w(9,A(31),Ldone),                  # !done (one-shot)
         ldrb_w(9,16,0xFE), cbz_w(9,A(33),Ldone),                   # have (wild HP captured)
         ldr_w(9,16,0xC8), cbnz_w(9,A(35),Ldone),                   # wild HP == 0 (verified KO)
         movz_w(9,3), str_w(9,10,0x508),              # result = 3 ("fainted, no capture")
         movz_w(9,1), strb_w(9,16,0xFD),              # done = 1
         strb_w(9,16,0xFF),                           # evolve_pending = 1 (A4)
         ldr_w(9,16,0xE0), addi_w(9,9,1), str_w(9,16,0xE0),
         ldr_w(17,16,0x5c), addi_w(17,17,1), str_w(17,16,0x5c),   # Ldone
         LDP_1617, LDP_910, disp(text,HOOK_ST)]
    return w + [ret_branch(w, base, HOOK_ST+4)]

def cave_R(text, base):  # reflect capture: wild (slot>=6) HP -> scratch +0xC8, have=1 @+0xFE
    A = lambda i: base+i*4
    LO = 3
    Lskip = A(10)
    w = [STP_1617, ADRP_SCRATCH, ADD_F00,
         ldrb_w(17,0,0x87), cmp_i(17,6), bcond(LO,A(5),Lskip),
         ldrh_w(17,0,0x7e), str_w(17,16,0xC8),
         movz_w(17,1), strb_w(17,16,0xFE),
         LDP_1617, disp(text,HOOK_R)]
    return w + [ret_branch(w, base, HOOK_R+4)]

def cave_E(text, base):  # A4: after-battle next-state redirect 4 -> 1 when evolve_pending (one-shot)
    A = lambda i: base+i*4
    Lstore = A(8)
    w = [STP_1617, ADRP_SCRATCH, ADD_F00,
         ldrb_w(17,16,0xFF), cbz_w(17,A(4),Lstore),   # evolve_pending?
         cmp_i(8,4), bcond(NE,A(6),Lstore),            # only the would-skip (state 4) transition
         movz_w(8,1),                                  # -> state 1: the evolution check
         strb_w(31,16,0xFF),                           # one-shot clear (Lstore)
         LDP_1617, disp(text,HOOK_E)]
    # NOTE: index 8 (strb wzr) only runs on the redirect path? No: Lstore=A(8) IS the strb -> it
    # also runs on the skip paths, clearing a stale flag either way (safe: flag wants clearing).
    return w + [ret_branch(w, base, HOOK_E+4)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    ap.add_argument('--pwb', help='base Wild Battles pwb1.pchtxt (for --out-unified)')
    ap.add_argument('--out-addon', required=True)
    ap.add_argument('--out-unified')
    ap.add_argument('--out-catch-unified', help='unified CATCH variant: XP but keep the post-KO catch screen (no A3)')
    a = ap.parse_args()
    text = Path(a.text).read_bytes()

    # lay the three caves out consecutively in the .text padding
    cA = CAVE_BASE;            wA = cave_A(text, cA)
    cC = cA + len(wA)*4;       wC = cave_C(text, cC)
    cS = cC + len(wC)*4;       wS = cave_ST(text, cS)
    cR = cS + len(wS)*4;       wR = cave_R(text, cR)
    cE = cR + len(wR)*4;       wE = cave_E(text, cE)
    end = cE + len(wE)*4
    assert end <= 0xD33000, "caves overflow .text padding (0xD33000)"

    # verify every cave: returns land correctly, displaced originals preserved
    def dis(words, base): return list(MD.disasm(b''.join(struct.pack('<I',x) for x in words), base))
    for name, w, base, ret, dorig in [
        ('A', wA, cA, HOOK_A+4,  disp(text,HOOK_A)),
        ('C', wC, cC, HOOK_C+4,  disp(text,HOOK_C)),
        ('ST',wS, cS, HOOK_ST+4, disp(text,HOOK_ST)),
        ('R', wR, cR, HOOK_R+4,  disp(text,HOOK_R)),
        ('E', wE, cE, HOOK_E+4,  disp(text,HOOK_E))]:
        ins = dis(w, base)
        assert ins[-1].mnemonic=='b' and int(ins[-1].op_str[1:],16)==ret, (name,'ret',ins[-1].op_str)
        assert struct.pack('<I',w[-2])==struct.pack('<I',dorig), (name,'displaced')
        # STACK-BALANCE: compute push/pop depth linearly; every internal branch must land
        # on an instruction with the same depth, so pushes/pops stay paired on all paths.
        depth_before = {}
        d_cur = 0
        for i in ins:
            depth_before[i.address] = d_cur
            if i.mnemonic=='stp' and '#-' in i.op_str and i.op_str.endswith('!'): d_cur += 1
            if i.mnemonic=='ldp' and '], #' in i.op_str: d_cur -= 1
        assert d_cur == 0, (name,'net stack imbalance at cave end')
        for br in ins:
            if br.mnemonic in ('cbz','cbnz') or br.mnemonic.startswith('b.'):
                tgt = int(br.op_str.split('#')[-1],16)
                if base <= tgt < base+len(w)*4:   # internal branch
                    assert depth_before[tgt] == depth_before[br.address], \
                        (name,'branch crosses push/pop boundary',hex(br.address),hex(tgt),
                         depth_before[br.address],depth_before[tgt])
    # A2 in-place bypass: cbz w9,#0x9d8a58 -> b #0x9d8a58
    assert disp(text,HOOK_A2)==0x340000A9, "0x9D8A44 is not the expected cbz; wrong build?"
    assert disp(text,HOOK_R)==0xF81C0FF7, "0x9E41D0 is not the expected str x23,[sp,#-0x40]!; wrong build?"
    assert disp(text,HOOK_E)==0xB9006A68, "0x319EC4 is not the expected str w8,[x19,#0x68]; wrong build?"
    bypass = b(HOOK_A2, 0x9D8A58)

    # hooks: each site branches to its cave (bytes are PC-relative, placed at mem+0x100)
    recs = [(HOOK_A, struct.pack('<I', b(HOOK_A, cA))),
            (HOOK_C, struct.pack('<I', b(HOOK_C, cC))),
            (HOOK_ST,struct.pack('<I', b(HOOK_ST, cS))),
            (HOOK_A2,struct.pack('<I', bypass)),
            (HOOK_R, struct.pack('<I', b(HOOK_R, cR))),
            (HOOK_E, struct.pack('<I', b(HOOK_E, cE))),
            (cA, b''.join(struct.pack('<I',x) for x in wA)),
            (cC, b''.join(struct.pack('<I',x) for x in wC)),
            (cS, b''.join(struct.pack('<I',x) for x in wS)),
            (cR, b''.join(struct.pack('<I',x) for x in wR)),
            (cE, b''.join(struct.pack('<I',x) for x in wE))]

    def emit(records, path, header_comment):
        lines = [f"@nsobid-{NSOBID}", ""] + header_comment + ["@enabled"]
        for mem, data in records:
            lines.append("%08X %s" % (mem + PCHTXT_OFF, data.hex().upper()))
        lines.append("@stop")
        Path(path).write_text("\n".join(lines) + "\n")

    emit(recs, a.out_addon,
         ["// Wild Battles EXP - ADD-ON (requires base Wild Battles mod also enabled).",
          "// pchtxt addr = memory offset + 0x100."])
    print("wrote", a.out_addon)

    if a.out_unified:
        assert a.pwb, "--pwb required for --out-unified"
        pwb_recs = []
        for ln in Path(a.pwb).read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith('@') and not ln.startswith('//'):
                addr, hx = ln.split(None,1)
                pwb_recs.append((int(addr,16)-PCHTXT_OFF, bytes.fromhex(hx.strip())))  # store as mem
        merged = pwb_recs + recs
        # pairwise overlap check (in pchtxt space)
        rngs = [(m+PCHTXT_OFF, m+PCHTXT_OFF+len(d)) for m,d in merged]
        for i in range(len(rngs)):
            for j in range(i+1, len(rngs)):
                if rngs[i][0] < rngs[j][1] and rngs[j][0] < rngs[i][1]:
                    raise SystemExit("OVERLAP between records %d and %d" % (i,j))
        emit(merged, a.out_unified,
             ["// Wild Battles EXP (UNIFIED) - base Wild Battles + native wild-KO EXP in ONE mod.",
              "// Load this alone; do NOT also enable the separate 'Wild Battles' mod.",
              "// pchtxt addr = memory offset + 0x100."])
        print("wrote", a.out_unified, "(%d records, overlap-checked)" % len(merged))

    if a.out_catch_unified:
        assert a.pwb, "--pwb required for --out-catch-unified"
        # Catch variant: faint + crash-guard + native XP, but NO result rewrite -> the
        # vanilla post-KO catch screen stays, so players can still catch what they battle.
        catch_recs = [(HOOK_A, struct.pack('<I', b(HOOK_A, cA))),
                      (HOOK_C, struct.pack('<I', b(HOOK_C, cC))),
                      (HOOK_A2,struct.pack('<I', bypass)),
                      (cA, b''.join(struct.pack('<I',x) for x in wA)),
                      (cC, b''.join(struct.pack('<I',x) for x in wC))]
        pwb_recs2 = []
        for ln in Path(a.pwb).read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith('@') and not ln.startswith('//'):
                addr, hx = ln.split(None,1)
                pwb_recs2.append((int(addr,16)-PCHTXT_OFF, bytes.fromhex(hx.strip())))
        merged2 = pwb_recs2 + catch_recs
        rngs = [(m+PCHTXT_OFF, m+PCHTXT_OFF+len(d)) for m,d in merged2]
        for i in range(len(rngs)):
            for j in range(i+1, len(rngs)):
                if rngs[i][0] < rngs[j][1] and rngs[j][0] < rngs[i][1]:
                    raise SystemExit("OVERLAP (catch variant) records %d/%d" % (i,j))
        emit(merged2, a.out_catch_unified,
             ["// Wild Battles EXP - CATCH VARIANT (unified). Battle -> KO -> native EXP ->",
              "// the normal catch screen (you can still catch what you battled).",
              "// Mutually exclusive with the main unified mod: enable only ONE of them.",
              "// pchtxt addr = memory offset + 0x100."])
        print("wrote", a.out_catch_unified, "(%d records, overlap-checked)" % len(merged2))

if __name__ == '__main__':
    main()
