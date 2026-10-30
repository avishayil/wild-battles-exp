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
HOOK_P    = 0x9D8A30   # XP-eligibility predicate entry: ldr x8,[x0,#0x80] (conditional PWB override)
HOOK_M    = 0x3059B8   # inside PWB's injected setup routine: str w9,[x20,#0x298] (PWB marker write)
                       #   runs only for PWB's synthesized battles -> set pwb_encounter scratch flag
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

PWB_MARKER_WORD = 0xB9029A89  # str w9,[x20,#0x298] (PWB's own, at mem 0x3059B8 after PWB applies)
def disp(text, mem):  # the original instruction word displaced by a hook
    if mem == 0x3059B8:
        return PWB_MARKER_WORD
    return struct.unpack_from('<I', text, mem)[0]

def ret_branch(body, base, target):
    return b(base + len(body)*4, target)

# ----- the three code caves (bodies in memory-offset space at CAVE_BASE+) -----
def cave_A(text, base):   # PoC A v3: clear instant-end flag ONLY for a PWB encounter; set armed
    # x19 = evt ; x1 = handler ctx ([x1+0x60] = command-menu object)
    # pwb_encounter (scratch +0xF8) is set by HOOK_M from PWB's own setup routine, so it is
    # true only for PWB's synthesized battles -> a real legendary/Snorlax is never touched.
    A = lambda i: base+i*4
    Lskip = A(19)                                              # index of the first restore (LDP_1617)
    w = [STP_910, STP_1617, ADRP_SCRATCH, ADD_F00,
         ldrb_w(17,16,0xF8), cbz_w(17,A(5),Lskip),              # 4,5  pwb_encounter?
         ldr_x(9,1,0x60),    cbz_x(9,A(7),Lskip),               # 6,7  command menu up?
         ldr_w(17,19,0x574), movz_w(10,0x80), tst_w(17,10), bcond(0,A(11),Lskip),  # 8-11 flag 0x80 set?
         bic_w(17,17,10), str_w(17,19,0x574),                   # 12,13 clear it
         ldr_w(17,16,0x34), addi_w(17,17,1), str_w(17,16,0x34), # 14-16 clear_cnt++
         movz_w(17,1), strb_w(17,16,0xFC),                      # 17,18 armed = 1
         LDP_1617, LDP_910,                                     # A(19) = Lskip (restores)
         disp(text,HOOK_A)]
    return w + [ret_branch(w, base, HOOK_A+4)]

def cave_C(text, base):   # PoC C v2: model-joint guard (recomp port), gated on pwb_encounter.
    # Returns x0=0 ("no joint") for a resource-less model, but ONLY inside an active PWB
    # encounter (scratch +0xF8). Outside a PWB battle it runs the untouched original, so a
    # vanilla model is never altered (v0.4.1). The guard still only triggers for the exact
    # resource-missing condition recomp documented; the +0xF8 check just scopes it to PWB.
    A = lambda i: base+i*4
    Lintc, Lorig, Lrest = A(16), A(26), A(25)
    return [STP_1617,ADRP_SCRATCH,ADD_F00,
            ldrb_w(17,16,0xF8), cbz_w(17,A(4),Lrest),               # 3,4  pwb_encounter? else restore+orig
            ldr_w(17,16,0xB0),addi_w(17,17,1),str_w(17,16,0xB0),    # 5-7  entry count (PWB only)
            LDP_1617,
            cbz_x(0,A(9),Lorig), ldr_x(9,0,0x1e0), cbnz_x(9,A(11),Lorig),      # 9-11 model/[+0x1e0]
            ldrb_w(9,0,0x192), cbz_w(9,A(13),Lintc), ldr_x(9,0,0x1e8), cbnz_x(9,A(15),Lorig),  # 12-15
            STP_1617,ADRP_SCRATCH,ADD_F00, ldr_w(17,16,0xD8),addi_w(17,17,1),str_w(17,16,0xD8),LDP_1617,  # 16-22
            movz_x(0,0), RET,                                       # 23,24 no-joint
            LDP_1617, disp(text,HOOK_C), b(A(27),HOOK_C+4)]         # 25=Lrest restore, 26=Lorig, 27 return

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

def cave_M(text, base):  # PWB marker hook: replay str w9,[x20,#0x298] + set pwb_encounter (+0xF8)
    A = lambda i: base+i*4
    w = [STP_1617, ADRP_SCRATCH, ADD_F00,
         movz_w(17,1), strb_w(17,16,0xF8),      # pwb_encounter = 1
         LDP_1617, disp(text,HOOK_M)]           # disp = str w9,[x20,#0x298]
    return w + [ret_branch(w, base, HOOK_M+4)]

def cave_P(text, base):  # A2 v3: conditional XP eligibility — PWB ENCOUNTER + PWB profile only
    # x0 = battle controller; setup = [x0+0x80]. Force eligibility (w0=1) ONLY when this is an
    # active PWB encounter (scratch +0xF8 set by HOOK_M) AND setup matches the PWB profile
    # ([+0x4A4]==1 && [+0x494]==0); otherwise fall through to the untouched original predicate
    # (including its own +0x4A4 gate). The +0xF8 gate (v0.4.1) stops a non-PWB battle that
    # happens to share the profile from receiving modified XP eligibility.
    A = lambda i: base+i*4
    Lorig = A(20)
    w = [STP_1617,
         ADRP_SCRATCH, ADD_F00, ldrb_w(17,16,0xF8), cbz_w(17,A(4),Lorig),  # 1-4  pwb_encounter?
         ldr_x(16,0,0x80), cbz_x(16,A(6),Lorig),                           # 5,6  setup = [x0+0x80]
         ldrb_w(17,16,0x4A4), cmp_i(17,1), bcond(NE,A(9),Lorig),           # 7-9  +0x4A4 == 1
         ldr_w(17,16,0x494), cbnz_w(17,A(11),Lorig),                       # 10,11 +0x494 == 0
         ADRP_SCRATCH, ADD_F00, ldr_w(17,16,0xE4), addi_w(17,17,1), str_w(17,16,0xE4),  # 12-16 a2_pwb_cnt
         LDP_1617, movz_w(0,1), RET,                                       # 17-19 eligible: w0=1
         LDP_1617, disp(text,HOOK_P)]                                      # 20=Lorig: restore + original
    return w + [ret_branch(w, base, HOOK_P+4)]

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
         strb_w(31,16,0xF8),                           # clear pwb_encounter every after-battle
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
    cP = cE + len(wE)*4;       wP = cave_P(text, cP)
    cM = cP + len(wP)*4;       wM = cave_M(text, cM)
    end = cM + len(wM)*4
    assert end <= 0xD33000, "caves overflow .text padding (0xD33000)"

    # verify every cave: returns land correctly, displaced originals preserved
    def dis(words, base): return list(MD.disasm(b''.join(struct.pack('<I',x) for x in words), base))
    for name, w, base, ret, dorig in [
        ('A', wA, cA, HOOK_A+4,  disp(text,HOOK_A)),
        ('C', wC, cC, HOOK_C+4,  disp(text,HOOK_C)),
        ('ST',wS, cS, HOOK_ST+4, disp(text,HOOK_ST)),
        ('R', wR, cR, HOOK_R+4,  disp(text,HOOK_R)),
        ('E', wE, cE, HOOK_E+4,  disp(text,HOOK_E)),
        ('P', wP, cP, HOOK_P+4,  disp(text,HOOK_P)),
        ('M', wM, cM, HOOK_M+4,  disp(text,HOOK_M))]:
        ins = dis(w, base)
        assert ins[-1].mnemonic=='b' and int(ins[-1].op_str[1:],16)==ret, (name,'ret',ins[-1].op_str)
        assert struct.pack('<I',w[-2])==struct.pack('<I',dorig), (name,'displaced')
        # STACK-BALANCE dataflow: propagate push/pop depth along fall-through and branch
        # edges; ret and the final external b end a path and must be at depth 0.
        idx = {i.address: k for k, i in enumerate(ins)}
        def delta(i):
            if i.mnemonic=='stp' and '#-' in i.op_str and i.op_str.endswith('!'): return 1
            if i.mnemonic=='ldp' and '], #' in i.op_str: return -1
            return 0
        depth = {ins[0].address: 0}
        work = [ins[0].address]
        cave_lo, cave_hi = base, base+len(w)*4
        while work:
            addr = work.pop()
            i = ins[idx[addr]]
            d_out = depth[addr] + delta(i)
            succs = []
            is_uncond_b = (i.mnemonic=='b')
            is_branch = i.mnemonic in ('cbz','cbnz') or i.mnemonic.startswith('b.') or is_uncond_b
            if i.mnemonic=='ret':
                assert depth[addr]==0, (name,'ret with unbalanced stack',hex(addr),depth[addr])
                continue
            if is_branch:
                tgt = int(i.op_str.split('#')[-1],16)
                if cave_lo <= tgt < cave_hi:
                    succs.append(tgt)
                else:
                    assert d_out==0, (name,'cave exit with unbalanced stack',hex(addr),d_out)
            if not is_uncond_b and idx[addr]+1 < len(ins):
                succs.append(ins[idx[addr]+1].address)
            for t in succs:
                if t in depth:
                    assert depth[t]==d_out, (name,'depth conflict',hex(t),depth[t],d_out)
                else:
                    depth[t]=d_out; work.append(t)
    assert disp(text,HOOK_P)==0xF9404008, "0x9D8A30 is not the expected ldr x8,[x0,#0x80]; wrong build?"
    assert disp(text,HOOK_R)==0xF81C0FF7, "0x9E41D0 is not the expected str x23,[sp,#-0x40]!; wrong build?"
    assert disp(text,HOOK_E)==0xB9006A68, "0x319EC4 is not the expected str w8,[x19,#0x68]; wrong build?"
    # HOOK_M lives inside PWB's injected routine (only present once PWB's records are applied);
    # its displaced word is PWB's own marker write str w9,[x20,#0x298].
    assert b(HOOK_M, cM)  # (sanity; the displaced word is asserted by replaying it in cave_M)

    # hooks: each site branches to its cave (bytes are PC-relative, placed at mem+0x100)
    recs = [(HOOK_A, struct.pack('<I', b(HOOK_A, cA))),
            (HOOK_C, struct.pack('<I', b(HOOK_C, cC))),
            (HOOK_ST,struct.pack('<I', b(HOOK_ST, cS))),
            (HOOK_P, struct.pack('<I', b(HOOK_P, cP))),
            (HOOK_R, struct.pack('<I', b(HOOK_R, cR))),
            (HOOK_E, struct.pack('<I', b(HOOK_E, cE))),
            (cA, b''.join(struct.pack('<I',x) for x in wA)),
            (cC, b''.join(struct.pack('<I',x) for x in wC)),
            (cS, b''.join(struct.pack('<I',x) for x in wS)),
            (cR, b''.join(struct.pack('<I',x) for x in wR)),
            (cE, b''.join(struct.pack('<I',x) for x in wE)),
            (cP, b''.join(struct.pack('<I',x) for x in wP)),
            (cM, b''.join(struct.pack('<I',x) for x in wM)),
            (HOOK_M, struct.pack('<I', b(HOOK_M, cM)))]   # redirect PWB's marker write -> cave_M

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
        INTENTIONAL = {HOOK_M+PCHTXT_OFF}  # HOOK_M redirect (pchtxt 0x305AB8) inside PWB's 0x305AB0/32B record
        for i in range(len(rngs)):
            for j in range(i+1, len(rngs)):
                if rngs[i][0] < rngs[j][1] and rngs[j][0] < rngs[i][1]:
                    a_lo = max(rngs[i][0], rngs[j][0])
                    if a_lo in INTENTIONAL:
                        continue
                    raise SystemExit("OVERLAP (unified) records %d/%d" % (i,j))
        emit(merged, a.out_unified,
             ["// Wild Battles EXP (UNIFIED) - base Wild Battles + native wild-KO EXP in ONE mod.",
              "// Load this alone; do NOT also enable the separate 'Wild Battles' mod.",
              "// pchtxt addr = memory offset + 0x100."])
        print("wrote", a.out_unified, "(%d records, overlap-checked)" % len(merged))

    if a.out_catch_unified:
        assert a.pwb, "--pwb required for --out-catch-unified"
        # Catch variant: faint + crash-guard + native XP, but NO result rewrite -> the
        # vanilla post-KO catch screen stays, so players can still catch what they battle.
        # NOTE (v0.4.1): the catch variant includes hook E purely to CLEAR pwb_encounter (+0xF8)
        # after each battle — without it the marker, set by hook M, would persist into the next
        # (possibly non-PWB) battle. cave_E's A4 state-redirect stays inert here: evolve_pending
        # (+0xFF) is only ever set by cave_ST's verified-KO rewrite, which this variant omits.
        catch_recs = [(HOOK_A, struct.pack('<I', b(HOOK_A, cA))),
                      (HOOK_C, struct.pack('<I', b(HOOK_C, cC))),
                      (HOOK_P, struct.pack('<I', b(HOOK_P, cP))),
                      (HOOK_E, struct.pack('<I', b(HOOK_E, cE))),
                      (cA, b''.join(struct.pack('<I',x) for x in wA)),
                      (cC, b''.join(struct.pack('<I',x) for x in wC)),
                      (cP, b''.join(struct.pack('<I',x) for x in wP)),
                      (cE, b''.join(struct.pack('<I',x) for x in wE)),
                      (cM, b''.join(struct.pack('<I',x) for x in wM)),
                      (HOOK_M, struct.pack('<I', b(HOOK_M, cM)))]
        pwb_recs2 = []
        for ln in Path(a.pwb).read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith('@') and not ln.startswith('//'):
                addr, hx = ln.split(None,1)
                pwb_recs2.append((int(addr,16)-PCHTXT_OFF, bytes.fromhex(hx.strip())))
        merged2 = pwb_recs2 + catch_recs
        rngs = [(m+PCHTXT_OFF, m+PCHTXT_OFF+len(d)) for m,d in merged2]
        INTENTIONAL = {HOOK_M+PCHTXT_OFF}  # HOOK_M redirect (pchtxt 0x305AB8) inside PWB's 0x305AB0/32B record
        for i in range(len(rngs)):
            for j in range(i+1, len(rngs)):
                if rngs[i][0] < rngs[j][1] and rngs[j][0] < rngs[i][1]:
                    a_lo = max(rngs[i][0], rngs[j][0])
                    if a_lo in INTENTIONAL:
                        continue
                    raise SystemExit("OVERLAP (catch) records %d/%d" % (i,j))
        emit(merged2, a.out_catch_unified,
             ["// Wild Battles EXP - CATCH VARIANT (unified). Battle -> KO -> native EXP ->",
              "// the normal catch screen (you can still catch what you battled).",
              "// Mutually exclusive with the main unified mod: enable only ONE of them.",
              "// pchtxt addr = memory offset + 0x100."])
        print("wrote", a.out_catch_unified, "(%d records, overlap-checked)" % len(merged2))

if __name__ == '__main__':
    main()
