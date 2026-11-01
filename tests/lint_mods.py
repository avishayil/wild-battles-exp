#!/usr/bin/env python3
"""Lint the committed mods/ against the committed build-manifest.json — no game files needed.

Catches the two drifts CI can see without rebuilding from the private NSO:
  * a committed .pchtxt whose bytes no longer match the manifest's recorded sha256
    (a stale `mods/` vs a regenerated manifest, or a hand-edit), and
  * a malformed patch file (bad header/footer, bad record line, out-of-window address).

Run: python3 -I tests/lint_mods.py   (exit 0 = clean, 1 = problems printed)
"""
import sys, re, json, hashlib, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODS = ROOT / 'mods'
MANIFEST = ROOT / 'build-manifest.json'

ADDR_LO, ADDR_HI = 0x100, 0xD33100          # .text + code-cave window (pchtxt space)
HDR = re.compile(r'^@nsobid-[0-9A-Fa-f]{64}$')
REC = re.compile(r'^[0-9A-F]{8} (?:[0-9A-F]{2})+$')

fails = []
def fail(m): fails.append(m)


def lint_pchtxt(path):
    lines = [l.rstrip('\n') for l in path.read_text().splitlines()]
    nonempty = [l for l in lines if l.strip()]
    if not nonempty or not HDR.match(nonempty[0]):
        fail(f"{path.name}: first line is not @nsobid-<64hex>")
    if '@enabled' not in nonempty:
        fail(f"{path.name}: missing @enabled")
    if not nonempty or nonempty[-1] != '@stop':
        fail(f"{path.name}: does not end with @stop")
    n_rec = 0
    for l in nonempty:
        if l.startswith('@') or l.startswith('//'):
            continue
        if not REC.match(l):
            fail(f"{path.name}: malformed record line: {l!r}"); continue
        n_rec += 1
        addr = int(l[:8], 16)
        if not (ADDR_LO <= addr < ADDR_HI):
            fail(f"{path.name}: record address 0x{addr:08X} outside .text+cave window")
    return n_rec


def main():
    man = json.loads(MANIFEST.read_text())

    # every committed .pchtxt lints clean
    counts = {}
    for p in sorted(MODS.rglob('*.pchtxt')):
        counts[str(p.relative_to(ROOT))] = lint_pchtxt(p)

    # manifest integrity: each output's bytes + record count match what is committed
    for name, o in man.get('outputs', {}).items():
        p = ROOT / o['path']
        if not p.exists():
            fail(f"manifest output {name}: missing file {o['path']}"); continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != o['sha256']:
            fail(f"manifest output {name}: sha256 drift\n    file {got}\n    man  {o['sha256']}")
        rel = str(p.relative_to(ROOT))
        if rel in counts and counts[rel] != o['records']:
            fail(f"manifest output {name}: record count {counts[rel]} != manifest {o['records']}")

    if fails:
        print(f"FAIL — {len(fails)} issue(s):")
        for f in fails:
            print("  ✗", f)
        sys.exit(1)
    print(f"ok — {len(counts)} pchtxt file(s) lint clean, "
          f"{len(man.get('outputs', {}))} manifest hash(es) match")


if __name__ == '__main__':
    main()
