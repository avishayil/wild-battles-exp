#!/usr/bin/env python3
"""Regression tests for tools/trace_assert.py — pure, no game files, CI-safe.

Pins the expected verdict of every committed trace fixture in both permissive and strict mode:
the real capture must PASS both; each synthetic negative must FAIL as designed. Run directly:

    python3 -I tests/test_trace_assert.py

Exit 0 = all expectations held; 1 = at least one fixture behaved unexpectedly.
"""
import sys, pathlib, contextlib, io

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import trace_assert as ta  # noqa: E402

FIX = ROOT / 'tools' / 'fixtures'
NEG = FIX / 'negative'

# (path, permissive_should_fail, strict_should_fail, why)
CASES = [
    (FIX / 'trace-v0.5-20261031.log',   False, False, "real v0.5 capture — clean in both modes"),
    (NEG / 'neg-double-rewrite.log',    True,  True,  "double result rewrite in one episode (E2)"),
    (NEG / 'neg-wrong-slot.log',        True,  True,  "KO captured at wrong slot (E2 SLOT!=12)"),
    (NEG / 'neg-stale-marker.log',      False, True,  "marker leaks past a KO (strict S1 only)"),
    (NEG / 'neg-missing-termination.log', False, True, "episode never terminates (strict S1 only)"),
]


def run_one(path, strict):
    """Return True if check() reported at least one failure (suppressing its prints)."""
    with contextlib.redirect_stdout(io.StringIO()):
        fails = ta.check(str(path), strict=strict)
    return bool(fails)


def main():
    bad = 0
    for path, perm_fail, strict_fail, why in CASES:
        if not path.exists():
            print(f"MISSING  {path}"); bad += 1; continue
        got_perm = run_one(path, strict=False)
        got_strict = run_one(path, strict=True)
        ok = (got_perm == perm_fail) and (got_strict == strict_fail)
        tag = "ok  " if ok else "FAIL"
        print(f"[{tag}] {path.name:32s} permissive={'fail' if got_perm else 'pass'} "
              f"strict={'fail' if got_strict else 'pass'}  — {why}")
        if not ok:
            print(f"        expected permissive={'fail' if perm_fail else 'pass'}, "
                  f"strict={'fail' if strict_fail else 'pass'}")
            bad += 1
    print(f"\n{len(CASES)-bad}/{len(CASES)} fixtures behaved as expected")
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
