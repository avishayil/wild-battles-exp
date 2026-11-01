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
CAVE_END_PAGE = 0xD33000  # the .text padding page ends here; caves must stay below it

# Expected original instruction word at each hook site. verify_preimages() asserts text.bin
# matches these before any records are emitted, so building against the wrong NSO fails loudly
# instead of landing a hook on an unexpected instruction. (HOOK_M's word is the UNPATCHED game
# instruction; PWB's own record overwrites it with the marker store — see verify_pwb_marker.)
PREIMAGE = {
    HOOK_A:  0xF9403034,  # ldr x20,[x1,#0x60]
    HOOK_C:  0xD101C3FF,  # sub sp,sp,#0x70
    HOOK_ST: 0xD101C3FF,  # sub sp,sp,#0x70
    HOOK_P:  0xF9404008,  # ldr x8,[x0,#0x80]
    HOOK_R:  0xF81C0FF7,  # str x23,[sp,#-0x40]!
    HOOK_E:  0xB9006A68,  # str w8,[x19,#0x68]
    HOOK_M:  0xD63F0100,  # blr x8  (unpatched; PWB overwrites it with its marker store)
}

def _chk_rel(cur, t, imm_bits):
    """Assert a branch displacement is 4-aligned and fits the signed immN*4 range; return it.
    imm_bits=26 for b (±128 MB), 19 for cbz/cbnz/b.cond (±1 MB). Does not alter the encoding."""
    d = t - cur
    assert d % 4 == 0, ("branch misaligned", hex(cur), hex(t), d)
    lo, hi = -(1 << (imm_bits + 1)), (1 << (imm_bits + 1)) - 4
    assert lo <= d <= hi, ("branch out of range", hex(cur), hex(t), d, "imm%d" % imm_bits)
    return d

# ----- AArch64 encoders (all operate in memory-offset space) -----
def ldr_x(rt,rn,off): assert off%8==0; return 0xF9400000|((off//8)<<10)|(rn<<5)|rt
def str_x(rt,rn,off): assert off%8==0; return 0xF9000000|((off//8)<<10)|(rn<<5)|rt
def ldr_w(rt,rn,off): return 0xB9400000|((off//4)<<10)|(rn<<5)|rt
def str_w(rt,rn,off): return 0xB9000000|((off//4)<<10)|(rn<<5)|rt
def ldrb_w(rt,rn,off):return 0x39400000|(off<<10)|(rn<<5)|rt
def strb_w(rt,rn,off):return 0x39000000|(off<<10)|(rn<<5)|rt
def ldrh_w(rt,rn,off): return 0x79400000|((off//2)<<10)|(rn<<5)|rt
def strh_w(rt,rn,off): return 0x79000000|((off//2)<<10)|(rn<<5)|rt
def addi_w(rd,rn,imm):return 0x11000000|(imm<<10)|(rn<<5)|rd
def movz_w(rd,i):     return 0x52800000|(i<<5)|rd
def movz_x(rd,i):     return 0xD2800000|(i<<5)|rd
def lslv_w(rd,rn,rm): return 0x1AC02000|(rm<<16)|(rn<<5)|rd
def orr_w(rd,rn,rm):  return 0x2A000000|(rm<<16)|(rn<<5)|rd
def cmp_i(rn,imm):    return 0x71000000|(imm<<10)|(rn<<5)|31
def tst_w(rn,rm):     return 0x6A000000|(rm<<16)|(rn<<5)|31
def bic_w(rd,rn,rm):  return 0x0A200000|(rm<<16)|(rn<<5)|rd
def cbz_x(rt,cur,t):  _chk_rel(cur,t,19); return 0xB4000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def cbnz_x(rt,cur,t): _chk_rel(cur,t,19); return 0xB5000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def cbz_w(rt,cur,t):  _chk_rel(cur,t,19); return 0x34000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def cbnz_w(rt,cur,t): _chk_rel(cur,t,19); return 0x35000000|(((t-cur)>>2 &0x7FFFF)<<5)|rt
def bcond(c,cur,t):   _chk_rel(cur,t,19); return 0x54000000|(((t-cur)>>2 &0x7FFFF)<<5)|c
def b(cur,t):         _chk_rel(cur,t,26); return 0x14000000|(((t-cur)>>2)&0x3FFFFFF)
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
def cave_A(text, base, timer=True):   # clear instant-end flag ONLY for a PWB encounter; set armed; (v0.6) drop timer
    # x19 = evt ; x1 = handler ctx ([x1+0x60] = command-menu object)
    # pwb_encounter (scratch +0xF8) is set by HOOK_M from PWB's own setup routine, so it is
    # true only for PWB's synthesized battles -> a real legendary/Snorlax is never touched.
    # v0.6: once the instant-end flag is cleared, also zero evt+0x562 (the special-battle's
    # 300s "MATCH TIME" limit the setup fn 0x28C740 writes together with the 0x80 flag). 0 = no
    # limit (recomp sets the same field to 0). Only on the PWB-gated flag-clear path, so a real
    # legendary/Snorlax keeps its countdown. Live-verified: >5 min with no timeout. `timer`
    # selects the build-time profile (classic = remove the timer; `timed` keeps it).
    A = lambda i: base+i*4
    timer_ins = [strh_w(31,19,0x562)] if timer else []          # clear the 300s battle timer (v0.6)
    Lskip = A(19 + len(timer_ins))                              # index of the first restore (LDP_1617)
    w = [STP_910, STP_1617, ADRP_SCRATCH, ADD_F00,
         ldrb_w(17,16,0xF8), cbz_w(17,A(5),Lskip),              # 4,5  pwb_encounter?
         ldr_x(9,1,0x60),    cbz_x(9,A(7),Lskip),               # 6,7  command menu up?
         ldr_w(17,19,0x574), movz_w(10,0x80), tst_w(17,10), bcond(0,A(11),Lskip),  # 8-11 flag 0x80 set?
         bic_w(17,17,10), str_w(17,19,0x574),                   # 12,13 clear instant-end flag
         ] + timer_ins + [                                      # 14   (classic profile) clear timer
         ldr_w(17,16,0x34), addi_w(17,17,1), str_w(17,16,0x34), # clear_cnt++
         movz_w(17,1), strb_w(17,16,0xFC),                      # armed = 1
         LDP_1617, LDP_910,                                     # Lskip = first restore
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

def cave_ST(text, base, strict_gate=True):  # entry hook: reset flags@state0; result 1->3 @state5 on VERIFIED KO (one-shot)
    # strict_gate (Finding B, DEFAULT since v0.6.2): before the rewrite, additionally require the
    # captured opponent to be the wild slot (slot==12) with a real max HP (>0), rejecting an unusual
    # extra participant that overwrote the HP capture. Promoted to default after live-accept across
    # Weedle/Pidgey/Rattata/Oddish (all slot==12 & maxhp>0; docs/LIVE_TESTING.md). `--hp-gate slot6`
    # restores the older v0.6 gate (have && wild_HP==0 only).
    A = lambda i: base+i*4
    extra = 5 if strict_gate else 0
    Lnot0, Lchain, Ldone = A(8), A(15), A(48 + extra)
    strict_block = ([ldrb_w(9,16,0xD4), cmp_i(9,12), bcond(NE,A(42),Ldone),   # 40-42 slot == 12
                     ldr_w(9,16,0xD0), cbz_w(9,A(44),Ldone)]                   # 43,44 max HP > 0
                    if strict_gate else [])
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
         ldrb_w(9,16,0xF8), cbz_w(9,A(37),Ldone),                   # 36,37 pwb_encounter still set
         ldr_w(9,16,0xCC), cbz_w(9,A(39),Ldone),                    # 38,39 species != 0 (valid capture)
         ] + strict_block + [
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

def cave_R(text, base):  # reflect capture (v0.5): record wild opponent identity, PWB encounter only
    # Only capture during an active PWB encounter (+0xF8). For the wild slot (>=6) record the
    # actual slot id (+0xD4), current HP (+0xC8), species (+0xCC) and max HP (+0xD0), and set
    # have (+0xFE). The extra fields let A3 sanity-check the capture and let live testing verify
    # the wild slot/species across multiple encounters before any slot tightening.
    A = lambda i: base+i*4
    LO = 3
    Lskip = A(17)
    w = [STP_1617, ADRP_SCRATCH, ADD_F00,
         ldrb_w(17,16,0xF8), cbz_w(17,A(4),Lskip),              # 3,4  pwb_encounter? else skip
         ldrb_w(17,0,0x87), cmp_i(17,6), bcond(LO,A(7),Lskip),  # 5-7  wild slot (>=6)?
         strb_w(17,16,0xD4),                                    # 8    record actual slot id
         ldrh_w(17,0,0x7e), str_w(17,16,0xC8),                  # 9,10  current HP -> +0xC8
         ldrh_w(17,0,0x78), str_w(17,16,0xCC),                  # 11,12 species   -> +0xCC
         ldrh_w(17,0,0x7c), str_w(17,16,0xD0),                  # 13,14 max HP     -> +0xD0
         movz_w(17,1), strb_w(17,16,0xFE),                      # 15,16 have = 1
         LDP_1617, disp(text,HOOK_R)]                           # 17 = Lskip
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

# ===== module registry =====================================================================
# One entry per hook (a hook site + its code cave), in cave-layout order. Bases are assigned
# consecutively from CAVE_BASE in THIS order for ALL modules regardless of variant, so a
# variant's caves keep stable addresses (byte-for-byte reproducible). Each module declares the
# variants that include it and a human note on the scratch slots it touches (the scratch page
# is a shared blackboard, not per-module private, so this is documentation for the manifest).
def module_table(profile, hp_gate='strict'):
    timer = (profile != 'timed')   # 'classic' (default) removes the 300s wild-battle timer
    strict_gate = (hp_gate == 'strict')   # 'strict' (default since v0.6.2); 'slot6' = older v0.6 gate
    return [
        dict(key='A',  hook=HOOK_A,  build=lambda t,b: cave_A(t,b,timer=timer),
             variants={'addon','main','catch'}, scratch='clear_cnt +0x34, armed +0xFC; (v0.6) timer evt+0x562'),
        dict(key='C',  hook=HOOK_C,  build=cave_C,  variants={'addon','main','catch'},
             scratch='c_entry +0xB0, guard_hit +0xD8; gated on pwb_encounter +0xF8'),
        dict(key='ST', hook=HOOK_ST, build=lambda t,b: cave_ST(t,b,strict_gate=strict_gate), variants={'addon','main'},
             scratch='state +0x40, mask +0x44, result +0x58, rewrite +0xE0, armed/done/have/evolve +0xFC..FF'),
        dict(key='R',  hook=HOOK_R,  build=cave_R,  variants={'addon','main'},
             scratch='wild_hp +0xC8, species +0xCC, maxhp +0xD0, slot +0xD4, have +0xFE; gated on +0xF8'),
        dict(key='E',  hook=HOOK_E,  build=cave_E,  variants={'addon','main','catch'},
             scratch='evolve_pending +0xFF; clears pwb_encounter +0xF8'),
        dict(key='P',  hook=HOOK_P,  build=cave_P,  variants={'addon','main','catch'},
             scratch='a2_cnt +0xE4; gated on pwb_encounter +0xF8'),
        dict(key='M',  hook=HOOK_M,  build=cave_M,  variants={'addon','main','catch'},
             scratch='sets pwb_encounter +0xF8'),
    ]

# Per-variant record order, preserved byte-for-byte from the pre-registry builder: the non-M
# hook redirects, then the cave bodies, then the M redirect LAST (it overlaps PWB's record, so
# it must be applied after PWB's own bytes).
VARIANT_ORDER = {
    'addon': dict(redir=['A','C','ST','P','R','E'], body=['A','C','ST','R','E','P','M']),
    'main':  dict(redir=['A','C','ST','P','R','E'], body=['A','C','ST','R','E','P','M']),
    'catch': dict(redir=['A','C','P','E'],          body=['A','C','P','E','M']),
}

def lay_out(text, profile, hp_gate='slot6'):
    """Assign every module a cave base consecutively; build and return {key: info}."""
    caves, base = {}, CAVE_BASE
    for m in module_table(profile, hp_gate):
        w = m['build'](text, base)
        caves[m['key']] = dict(m, base=base, words=w)
        base += len(w) * 4
    assert base <= 0xD33000, "caves overflow .text padding (0xD33000)"
    return caves

def verify_caves(text, caves):
    """capstone self-checks per cave: it returns to hook+4, preserves the displaced original,
    and is stack-balanced on every path (dataflow depth); plus a build-id sanity on P/R/E."""
    def dis(words, base): return list(MD.disasm(b''.join(struct.pack('<I', x) for x in words), base))
    for key, c in caves.items():
        w, base, ret = c['words'], c['base'], c['hook'] + 4
        ins = dis(w, base)
        assert ins[-1].mnemonic == 'b' and int(ins[-1].op_str[1:], 16) == ret, (key, 'ret', ins[-1].op_str)
        assert struct.pack('<I', w[-2]) == struct.pack('<I', disp(text, c['hook'])), (key, 'displaced')
        idx = {i.address: k for k, i in enumerate(ins)}
        def delta(i):
            if i.mnemonic == 'stp' and '#-' in i.op_str and i.op_str.endswith('!'): return 1
            if i.mnemonic == 'ldp' and '], #' in i.op_str: return -1
            return 0
        depth = {ins[0].address: 0}; work = [ins[0].address]
        lo, hi = base, base + len(w) * 4
        while work:
            addr = work.pop(); i = ins[idx[addr]]
            d_out = depth[addr] + delta(i); succs = []
            is_uncond_b = (i.mnemonic == 'b')
            is_branch = i.mnemonic in ('cbz', 'cbnz') or i.mnemonic.startswith('b.') or is_uncond_b
            if i.mnemonic == 'ret':
                assert depth[addr] == 0, (key, 'ret unbalanced', hex(addr), depth[addr]); continue
            if is_branch:
                tgt = int(i.op_str.split('#')[-1], 16)
                if lo <= tgt < hi: succs.append(tgt)
                else: assert d_out == 0, (key, 'cave exit unbalanced', hex(addr), d_out)
            if not is_uncond_b and idx[addr] + 1 < len(ins): succs.append(ins[idx[addr] + 1].address)
            for t in succs:
                if t in depth: assert depth[t] == d_out, (key, 'depth conflict', hex(t), depth[t], d_out)
                else: depth[t] = d_out; work.append(t)

def verify_preimages(text):
    """Every hook site in text.bin holds the exact instruction we expect to displace."""
    for mem, expect in PREIMAGE.items():
        got = struct.unpack_from('<I', text, mem)[0]
        assert got == expect, ("preimage mismatch (wrong NSO build?)", hex(mem),
                               "got 0x%08X want 0x%08X" % (got, expect))

def verify_cave_padding(text, caves):
    """The portion of the cave region present in text.bin is zero padding (no live code).
    (Bytes past len(text) are loader-provided zero page padding, not carved into the file.)"""
    cave_end = max(c['base'] + len(c['words']) * 4 for c in caves.values())
    assert cave_end <= CAVE_END_PAGE, ("caves overflow .text padding", hex(cave_end))
    assert len(text) >= CAVE_BASE, ("text.bin shorter than cave base", hex(len(text)))
    seg = text[CAVE_BASE:min(cave_end, len(text))]
    nz = next((CAVE_BASE + i for i, v in enumerate(seg) if v), None)
    assert nz is None, ("cave region is not zero padding at", hex(nz) if nz else None)

def verify_pwb_marker(merged):
    """The intentional overlap is only safe if PWB's own record writes the marker store at
    HOOK_M. Find the base-PWB record covering HOOK_M (not our 4-byte redirect) and assert it."""
    for mem, data in merged:
        if mem != HOOK_M and mem <= HOOK_M < mem + len(data):
            off = HOOK_M - mem
            if off + 4 <= len(data):
                word = struct.unpack_from('<I', data, off)[0]
                assert word == PWB_MARKER_WORD, (
                    "PWB record does not write the marker at HOOK_M", "0x%08X" % word)
                return
    raise SystemExit("PWB marker record not found covering HOOK_M (wrong base Wild Battles mod?)")

def variant_records(variant, caves):
    """(mem, bytes) records for a variant, in the exact order the pre-registry builder used."""
    order = VARIANT_ORDER[variant]
    recs = [(caves[k]['hook'], struct.pack('<I', b(caves[k]['hook'], caves[k]['base']))) for k in order['redir']]
    recs += [(caves[k]['base'], b''.join(struct.pack('<I', x) for x in caves[k]['words'])) for k in order['body']]
    m = caves['M']
    recs.append((m['hook'], struct.pack('<I', b(m['hook'], m['base']))))  # M redirect applied last
    return recs

def load_pwb(path):
    out = []
    for ln in Path(path).read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith('@') and not ln.startswith('//'):
            addr, hx = ln.split(None, 1)
            out.append((int(addr, 16) - PCHTXT_OFF, bytes.fromhex(hx.strip())))  # store as mem offset
    return out

def overlap_check(label, merged):
    """Pairwise record overlap (in pchtxt space). The one intentional overlap is HOOK_M's
    redirect sitting inside PWB's 32-byte 0x305AB0 record; everything else must be disjoint."""
    rngs = [(m + PCHTXT_OFF, m + PCHTXT_OFF + len(d)) for m, d in merged]
    INTENTIONAL = {HOOK_M + PCHTXT_OFF}
    for i in range(len(rngs)):
        for j in range(i + 1, len(rngs)):
            if rngs[i][0] < rngs[j][1] and rngs[j][0] < rngs[i][1]:
                if max(rngs[i][0], rngs[j][0]) in INTENTIONAL: continue
                raise SystemExit("OVERLAP (%s) records %d/%d" % (label, i, j))

def emit(records, path, header_comment):
    lines = [f"@nsobid-{NSOBID}", ""] + header_comment + ["@enabled"]
    for mem, data in records:
        lines.append("%08X %s" % (mem + PCHTXT_OFF, data.hex().upper()))
    lines.append("@stop")
    Path(path).write_text("\n".join(lines) + "\n")

def write_manifest(path, profile, caves, outputs, hp_gate='slot6'):
    import json, hashlib
    man = dict(
        nsobid=NSOBID, profile=profile, hp_gate=hp_gate, cave_base=hex(CAVE_BASE),
        cave_end=hex(max(c['base'] + len(c['words']) * 4 for c in caves.values())),
        modules={k: dict(hook=hex(c['hook']), cave=hex(c['base']), words=len(c['words']),
                         variants=sorted(c['variants']), scratch=c['scratch'])
                 for k, c in caves.items()},
        outputs={})
    for name, (p, recs) in outputs.items():
        man['outputs'][name] = dict(path=p, records=len(recs),
                                    sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest())
    Path(path).write_text(json.dumps(man, indent=2) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    ap.add_argument('--pwb', help='base Wild Battles pwb1.pchtxt (for --out-unified/--out-catch-unified)')
    ap.add_argument('--out-addon', required=True)
    ap.add_argument('--out-unified')
    ap.add_argument('--out-catch-unified', help='unified CATCH variant: XP but keep the post-KO catch screen (no A3)')
    ap.add_argument('--profile', default='classic', choices=['classic', 'timed'],
                    help="classic (default): remove the 300s wild-battle timer; timed: keep it")
    ap.add_argument('--hp-gate', default='strict', choices=['slot6', 'strict'],
                    help="strict (default, v0.6.2+): A3 KO gate also requires slot==12 and max_hp>0 "
                         "(Finding B; promoted after live-accept across Weedle/Pidgey/Rattata/Oddish, "
                         "all slot==12 & maxhp>0). slot6: the older v0.6 gate (have && wild_HP==0 only)")
    ap.add_argument('--manifest', help='also write a build manifest (JSON) to this path')
    ap.add_argument('--verify-manifest', metavar='PATH',
                    help='after building, assert each output sha256 matches this committed manifest')
    a = ap.parse_args()
    text = Path(a.text).read_bytes()

    verify_preimages(text)
    caves = lay_out(text, a.profile, a.hp_gate)
    verify_caves(text, caves)
    verify_cave_padding(text, caves)
    outputs = {}

    addon = variant_records('addon', caves)
    emit(addon, a.out_addon,
         ["// Wild Battles EXP - ADD-ON (requires base Wild Battles mod also enabled).",
          "// pchtxt addr = memory offset + 0x100."])
    print("wrote", a.out_addon)
    outputs['addon'] = (a.out_addon, addon)

    if a.out_unified:
        assert a.pwb, "--pwb required for --out-unified"
        merged = load_pwb(a.pwb) + variant_records('main', caves)
        verify_pwb_marker(merged)
        overlap_check('unified', merged)
        emit(merged, a.out_unified,
             ["// Wild Battles EXP (UNIFIED) - base Wild Battles + native wild-KO EXP in ONE mod.",
              "// Load this alone; do NOT also enable the separate 'Wild Battles' mod.",
              "// pchtxt addr = memory offset + 0x100."])
        print("wrote", a.out_unified, "(%d records, overlap-checked)" % len(merged))
        outputs['unified'] = (a.out_unified, merged)

    if a.out_catch_unified:
        assert a.pwb, "--pwb required for --out-catch-unified"
        # Catch variant: faint + crash-guard + native XP, but NO result rewrite -> the vanilla
        # post-KO catch screen stays. It includes hook E purely to clear pwb_encounter after each
        # battle (cave_E's A4 redirect stays inert: evolve_pending is only set by cave_ST, omitted here).
        merged2 = load_pwb(a.pwb) + variant_records('catch', caves)
        verify_pwb_marker(merged2)
        overlap_check('catch', merged2)
        emit(merged2, a.out_catch_unified,
             ["// Wild Battles EXP - CATCH VARIANT (unified). Battle -> KO -> native EXP ->",
              "// the normal catch screen (you can still catch what you battled).",
              "// Mutually exclusive with the main unified mod: enable only ONE of them.",
              "// pchtxt addr = memory offset + 0x100."])
        print("wrote", a.out_catch_unified, "(%d records, overlap-checked)" % len(merged2))
        outputs['catch'] = (a.out_catch_unified, merged2)

    if a.manifest:
        write_manifest(a.manifest, a.profile, caves, outputs, a.hp_gate)
        print("wrote", a.manifest)

    if a.verify_manifest:
        import json, hashlib
        ref = json.loads(Path(a.verify_manifest).read_text())
        refout = ref.get('outputs', {})
        for name, (p, _recs) in outputs.items():
            want = refout.get(name, {}).get('sha256')
            got = hashlib.sha256(Path(p).read_bytes()).hexdigest()
            assert want is not None, ("no committed hash for output", name, a.verify_manifest)
            assert got == want, ("artifact drift vs committed manifest", name, got, want)
        print("verified %d artifact hash(es) against %s" % (len(outputs), a.verify_manifest))

if __name__ == '__main__':
    main()
