#!/usr/bin/env python3
"""Read the EXP-amount probe slots over the Eden gdbstub (memory reads only; never breakpoints).

Pairs with tools/probe_exp.py. Resumes the guest on connect, then polls the scratch page and
prints the per-call-site amount + hit count whenever they change. Resolve the module base the
same way scratchread.py does.

  python3 -I tools/probe_exp_read.py
"""
import socket, binascii, struct, time

def cs(p): return b'%02x' % (sum(p) % 256)

class R:
    def __init__(s, port): s.s = socket.create_connection(('127.0.0.1', port), timeout=6); s.buf = b''
    def _rd(s, to=6):
        s.s.settimeout(to)
        while True:
            i = s.buf.find(b'$')
            if i >= 0:
                j = s.buf.find(b'#', i)
                if j >= 0 and len(s.buf) >= j + 3:
                    p = s.buf[i+1:j]; s.buf = s.buf[j+3:]; s.s.sendall(b'+'); return p
            d = s.s.recv(8192)
            if not d: raise ConnectionError
            s.buf += d
    def cmd(s, p, to=6):
        s.s.sendall(b'$' + p.encode() + b'#' + cs(p.encode()))
        while True:
            pk = s._rd(to)
            if pk[:1] == b'O' and len(pk) > 1: continue
            return pk.decode(errors='replace')
    def rcmd(s, t):
        r = s.cmd('qRcmd,' + t.encode().hex())
        try: return binascii.unhexlify(r).decode(errors='replace')
        except: return r
    def rd(s, a, n):
        r = s.cmd('m %x,%x' % (a, n))
        return None if (not r or r.startswith('E')) else binascii.unhexlify(r)

SITES = [('pred 9F28E8 eligible', 0x10), ('pred 9F619C eligible', 0x18), ('a089e0 reward', 0x20)]

def out(m): print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)

def session():
    r = R(6543); r.cmd('qSupported:hwbreak+'); r.cmd('?')
    base = None
    for ln in r.rcmd('get info').splitlines():
        p = ln.split()
        if len(p) >= 4 and p[1] == '-' and (p[3] == 'main' or int(p[2],16)-int(p[0],16)+1 == 0x1EE1000):
            base = int(p[0], 16)
    out(f'connected base=0x{base:x}')
    r.s.sendall(b'$c#63'); out('resumed; KO a wild Pokemon and watch the amount')
    SB = base + 0x1EE0F00; prev = None
    while True:
        time.sleep(1.0)
        d = r.rd(SB, 0x100)
        if not d or len(d) < 0x28: continue
        cur = []
        for name, slot in SITES:
            amt, = struct.unpack_from('<I', d, slot)
            cnt, = struct.unpack_from('<I', d, slot + 4)
            cur.append((amt, cnt))
        if cur != prev:
            prev = cur
            out(' | '.join(f'{name}: amount={a} n={c}' for (name, _), (a, c) in zip(SITES, cur)))

out('waiting for gdbstub…')
while True:
    try: session()
    except (OSError, ConnectionError): time.sleep(2)
