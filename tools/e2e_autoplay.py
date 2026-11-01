#!/usr/bin/env python3
"""e2e_autoplay.py — drive Wild Battles EXP wild battles for automated regression.

SAFETY MODEL (hard rules, do not relax):
  * The gdbstub is READ-ONLY. This harness only ever sends `$c` (continue, once) and `m addr,len`
    (memory reads). It NEVER writes memory/registers and NEVER sets breakpoints (breakpoints
    deadlock Eden's JIT). All "playing" is done with OS keystrokes to the Eden window, exactly
    like a human at the keyboard — never by poking game state.
  * It is the SINGLE gdbstub client (stop any standalone scratchread first).
  * It quits Eden only via a graceful AppleScript quit, and only at the OVERWORLD
    (pwb_encounter==0, settled) — never mid-battle/mid-save — and only with --quit-when-done.

Input layer: macOS `osascript` System Events. Eden player-0 keymap (from qt-config.ini):
    A=C  B=X  X=V  Y=Z  +=M  -=N   move(lstick)=W/A/S/D
Keystrokes require macOS Accessibility permission for the sending process; without it they
silently no-op. Eden must be frontmost (the harness re-focuses it each cycle).

Usage:
    python3 -I tools/e2e_autoplay.py --species 5 --max-seconds 900 [--dry-run] [--quit-when-done]

--dry-run reads + prints state and plans actions but sends NO keystrokes (safe to run anytime).
"""
import argparse, socket, struct, subprocess, sys, time

# ---- Eden keymap (osascript keystroke chars) ----
A_BTN, B_BTN, X_BTN, Y_BTN = 'c', 'x', 'v', 'z'
UP, DOWN, LEFT, RIGHT = 'w', 's', 'a', 'd'
APP = 'eden'          # process/app name for focus + quit
STUB_PORT = 6543
SCRATCH_OFF = 0x1EE0F00

# ---------- read-only gdbstub client ----------
def _csum(p): return b'%02x' % (sum(p) % 256)

class Stub:
    def __init__(s, port=STUB_PORT):
        s.s = socket.create_connection(('127.0.0.1', port), timeout=6); s.buf = b''
    def _rd(s, to=6):
        s.s.settimeout(to)
        while b'#' not in s.buf or len(s.buf.split(b'#', 1)[1]) < 2:
            s.buf += s.s.recv(4096)
        if s.buf[:1] == b'+': s.buf = s.buf[1:]
        pkt, _, rest = s.buf.partition(b'#'); s.buf = rest[2:]
        s.s.sendall(b'+'); return pkt[1:] if pkt[:1] == b'$' else pkt
    def cmd(s, p, to=6):
        pb = p.encode(); s.s.sendall(b'$' + pb + b'#' + _csum(pb)); return s._rd(to)
    def rcmd(s, t):
        hx = t.encode().hex(); out = s.cmd('qRcmd,' + hx)
        acc = b''
        while out not in (b'OK', b'') and out[:1] == b'O':
            acc += bytes.fromhex(out[1:].decode()); out = s._rd()
        return acc.decode(errors='replace')
    def resume(s): s.s.sendall(b'$c#63')          # continue; game runs, we poll m-reads
    def rd(s, a, n):
        r = s.cmd('m%x,%x' % (a, n))
        try: return bytes.fromhex(r.decode())
        except Exception: return b''
    def xfer(s, obj):
        data = b''; off = 0
        for _ in range(64):
            r = s.cmd('qXfer:%s:read::%x,%x' % (obj, off, 0xffc))
            if not r: break
            data += r[1:]
            if r[:1] == b'l': break
            off = len(data)
        return data

def resolve_base(st):
    # This Eden build's `monitor get info` is empty, but it advertises qXfer:libraries:read,
    # which works WHILE RUNNING (no halt needed — halting at boot crashes MoltenVK's present).
    # The main NSO ("beluga.nss") spans exactly 0x1EE1000 to the next module (== scratch page end).
    import re
    lib = st.xfer('libraries').decode(errors='replace')
    segs = sorted(int(a, 16) for a in re.findall(r'address="0x([0-9A-Fa-f]+)"', lib))
    for i in range(len(segs) - 1):
        if segs[i + 1] - segs[i] == 0x1EE1000:
            return segs[i]
    return None

def read_state(st, sb):
    d = st.rd(sb, 0x100)
    if not d or len(d) < 0xFF: return None
    u = lambda o: struct.unpack_from('<I', d, o)[0]
    return dict(clr=u(0x34), state=u(0x40), seen=u(0x44), result=u(0x58), wild_hp=u(0xC8),
                species=u(0xCC), maxhp=u(0xD0), slot=d[0xD4], guard=u(0xD8), rw=u(0xE0),
                a2=u(0xE4), pe=u(0xF8), armed=d[0xFC], done=d[0xFD], have=d[0xFE])

# ---------- OS keystroke layer (osascript) ----------
def _osa(script):
    return subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=8)

def accessibility_ok():
    """True if System Events can enumerate UI (proxy for Accessibility being granted)."""
    r = _osa('tell application "System Events" to count processes')
    return r.returncode == 0 and r.stdout.strip().isdigit()

def frontmost():
    r = _osa('tell application "System Events" to name of first process whose frontmost is true')
    return r.stdout.strip()

def focus_eden():
    _osa(f'tell application "System Events" to set frontmost of process "{APP}" to true')
    time.sleep(0.3)
    return frontmost().lower().startswith(APP)

def tap(dry, key, hold=0.0):
    if dry:
        print(f"    [dry] tap {key!r} hold={hold}"); return
    if hold > 0:
        _osa(f'tell application "System Events" to key down "{key}"'); time.sleep(hold)
        _osa(f'tell application "System Events" to key up "{key}"')
    else:
        _osa(f'tell application "System Events" to keystroke "{key}"')

def quit_eden(dry):
    if dry: print("    [dry] would quit eden"); return
    _osa(f'tell application "{APP}" to quit')

# ---------- harness loop ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--species', type=int, default=5, help='distinct KO species target')
    ap.add_argument('--max-seconds', type=int, default=900)
    ap.add_argument('--max-encounters', type=int, default=25)
    ap.add_argument('--input', choices=['none', 'keystroke'], default='none',
                    help="none (default): pure read-only observer — log per-species evidence while "
                         "battles are driven externally (you, or a looping TAS A-masher). keystroke: "
                         "the harness mashes A via osascript (needs Eden frontmost + Accessibility).")
    ap.add_argument('--dry-run', action='store_true', help='with --input keystroke, send NO keys; read+plan only')
    ap.add_argument('--walk-nudge', action='store_true',
                    help='occasionally tap a direction in the overworld; OFF by default because '
                         'Let\'s Go spawns roam and walk into a stationary player (encounter needs no input)')
    ap.add_argument('--quit-when-done', action='store_true')
    ap.add_argument('--no-resume', action='store_true',
                    help="attach to an ALREADY-RUNNING game: never send $c (which would put the "
                         "stub in await-stop mode and block reads). Use when the game is past boot.")
    a = ap.parse_args()

    try:
        st = Stub()
    except OSError as e:
        print("no gdbstub on :%d (launch Eden with use_gdbstub=true) — %s" % (STUB_PORT, e)); sys.exit(2)

    # Any signal → raise SystemExit so the `finally` below closes the socket CLEANLY. A --no-resume
    # reader never sent $c, so a clean FIN lets the single-connection stub re-listen (no wedge).
    import signal
    def _bye(*_): raise SystemExit(0)
    for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try: signal.signal(_sig, _bye)
        except Exception: pass
    try:
        _run(st, a)
    finally:
        try: st.s.close()
        except Exception: pass

def _run(st, a):
    st.cmd('qSupported:hwbreak+'); st.cmd('?')
    if not a.no_resume:
        st.resume()                   # unblock the boot halt FIRST so the game loads its modules
        print("resumed boot; waiting for the main module to map…", flush=True)
    else:
        print("attaching to a running game (no $c)…", flush=True)
    base = None
    for _ in range(120):              # 'main' appears a few seconds after boot (title/controller screen)
        base = resolve_base(st)
        if base is not None: break
        time.sleep(1.0)
    if base is None:
        print("could not resolve module base after 120s (is the title actually booting?)"); sys.exit(2)
    sb = base + SCRATCH_OFF
    drive = (a.input == 'keystroke')
    print(f"connected base=0x{base:x}; scratch=0x{sb:x}; input={a.input} dry_run={a.dry_run}")

    if drive and not a.dry_run:
        if not accessibility_ok():
            print("ACCESSIBILITY not granted — keystrokes will no-op. Grant it, then rerun."); sys.exit(3)
        print("focusing eden…", "ok" if focus_eden() else "WARN not frontmost")

    t0 = time.time()
    ko = {}            # species -> dict(slot,maxhp,rewrote)
    encounters = 0
    walk_cycle = [RIGHT, LEFT, UP, DOWN]
    last_pe = 0
    def elapsed(): return time.time() - t0

    while len(ko) < a.species and encounters < a.max_encounters and elapsed() < a.max_seconds:
        s = read_state(st, sb)
        if s is None:
            time.sleep(0.5); continue

        if s['pe'] == 1:                                   # --- in a PWB battle: attack ---
            if last_pe == 0:
                encounters += 1
                print(f"[{int(elapsed())}s] encounter #{encounters} (species={s['species']})")
            last_pe = 1
            if drive:
                if not a.dry_run and not frontmost().lower().startswith(APP): focus_eden()
                # mash A to pick Fight / first move / advance text; paced so we don't overrun menus
                for _ in range(6):
                    s = read_state(st, sb)
                    if not s or s['pe'] == 0: break
                    tap(a.dry_run, A_BTN); time.sleep(1.1)
            else:
                time.sleep(1.0)   # observer: battle is driven externally (you / TAS loop)
            continue

        # --- overworld ---
        if last_pe == 1:                                   # just ended a battle: record it
            end = read_state(st, sb) or s
            sp = end['species']
            if sp:
                rec = ko.setdefault(sp, dict(slot=end['slot'], maxhp=end['maxhp'],
                                             rewrote=end['rw'], result=end['result'], have=end['have']))
                print(f"[{int(elapsed())}s] battle end: species={sp} slot={end['slot']} "
                      f"maxhp={end['maxhp']} result={end['result']} rewrite_cnt={end['rw']} "
                      f"(distinct KO species: {len(ko)}/{a.species})")
            last_pe = 0
        # Let's Go: roaming spawns walk into a stationary player, so the overworld phase is just
        # WAIT (read-only) — no input needed. --walk-nudge optionally bumps a spawn to speed it up.
        if a.walk_nudge and drive:
            if not a.dry_run and not frontmost().lower().startswith(APP): focus_eden()
            tap(a.dry_run, walk_cycle[encounters % len(walk_cycle)], hold=0.45)
        time.sleep(1.0)

    # ---- summary ----
    print("\n==== autoplay summary ====")
    print(f"elapsed={int(elapsed())}s encounters={encounters} distinct_KO_species={len(ko)}")
    all12 = True
    for sp, r in sorted(ko.items()):
        ok = (r['slot'] == 12 and r['maxhp'] > 0 and sp != 0)
        all12 &= ok
        print(f"  species={sp:<4} slot={r['slot']:<3} maxhp={r['maxhp']:<4} result={r['result']} "
              f"rewrite_cnt_at_end={r['rewrote']}  {'OK' if ok else 'ANOMALY (slot!=12 or maxhp<=0)'}")
    print(f"strict-gate evidence: {'ALL species slot==12 & maxhp>0' if all12 and ko else 'INCOMPLETE/ANOMALOUS'}")

    if a.quit_when_done:
        s = read_state(st, sb)
        if s and s['pe'] == 0:
            print("overworld settled — quitting eden gracefully"); time.sleep(1.0); quit_eden(a.dry_run)
        else:
            print("NOT quitting: not safely at overworld")
    if not a.no_resume:
        st.resume()   # leave the game running/continued (never leave it halted)

if __name__ == '__main__':
    main()
