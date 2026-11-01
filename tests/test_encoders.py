#!/usr/bin/env python3
"""Unit tests for the AArch64 encoders in tools/build_patch.py — pure, no game files.

Checks each encoder round-trips through capstone to the expected instruction, and that the
branch-range/alignment guard (_chk_rel) rejects misaligned and out-of-range displacements.
Needs capstone (the generator imports it already). Run:

    python3 -I tests/test_encoders.py
"""
import sys, struct, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_patch as bp  # noqa: E402
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM  # noqa: E402

MD = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
fails = []


def dis(word, addr=0):
    i = next(MD.disasm(struct.pack('<I', word), addr))
    return f"{i.mnemonic} {i.op_str}".strip()


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: got {got!r} want {want!r}")


def raises(fn, label):
    try:
        fn()
    except AssertionError:
        return
    fails.append(f"{label}: expected AssertionError, none raised")


# --- data-processing / memory encoders vs capstone ---
eq(dis(bp.ldr_x(0, 1, 0x60)),    "ldr x0, [x1, #0x60]",   "ldr_x")
eq(dis(bp.str_x(9, 16, 0x48)),   "str x9, [x16, #0x48]",  "str_x")
eq(dis(bp.ldr_w(17, 19, 0x574)), "ldr w17, [x19, #0x574]","ldr_w")
eq(dis(bp.str_w(17, 16, 0x40)),  "str w17, [x16, #0x40]", "str_w")
eq(dis(bp.ldrb_w(17, 16, 0xF8)), "ldrb w17, [x16, #0xf8]","ldrb_w")
eq(dis(bp.strb_w(17, 16, 0xFC)), "strb w17, [x16, #0xfc]","strb_w")
eq(dis(bp.ldrh_w(17, 0, 0x7e)),  "ldrh w17, [x0, #0x7e]", "ldrh_w")
eq(dis(bp.strh_w(31, 19, 0x562)),"strh wzr, [x19, #0x562]","strh_w")
eq(dis(bp.movz_w(10, 0x80)),     "mov w10, #0x80",        "movz_w")
eq(dis(bp.cmp_i(17, 1)),         "cmp w17, #1",           "cmp_i")

# --- branches decode to the right target ---
eq(dis(bp.b(0x1000, 0x2000), 0x1000),        "b #0x2000",       "b fwd")
eq(dis(bp.cbz_w(17, 0x100, 0x200), 0x100),   "cbz w17, #0x200", "cbz_w")
eq(dis(bp.cbnz_x(9, 0x100, 0x80), 0x100),    "cbnz x9, #0x80",  "cbnz_x back")

# --- a long in-range redirect (hook site -> cave) must encode, like the real build ---
HOOK_A, CAVE = 0x28BF34, 0xD32BA8
eq(dis(bp.b(HOOK_A, CAVE), HOOK_A), f"b #{hex(CAVE)}", "b hook->cave")

# --- _chk_rel guard rejects bad displacements ---
raises(lambda: bp.b(0, 2),           "b misaligned")
raises(lambda: bp.b(0, 1 << 27),     "b out of range (+128MB)")
raises(lambda: bp.cbz_w(0, 0, 1 << 20), "cbz out of range (+1MB)")
bp.b(0, (1 << 27) - 4)                 # in range: must NOT raise
bp.cbz_w(0, 0, (1 << 20) - 4)          # in range: must NOT raise

if fails:
    print(f"FAIL — {len(fails)} encoder check(s):")
    for f in fails:
        print("  ✗", f)
    sys.exit(1)
print("ok — all encoder + branch-range checks passed")
