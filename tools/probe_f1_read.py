#!/usr/bin/env python3
"""Read the F1 ring buffer (0xA6EF80 message numbers) over the Eden gdbstub. Reads only.

Scratch: +0x00 count(u32); ring at +0x60, 8 * {number u32 @+0, caller_x30lo u32 @+4}.
Prints the ring whenever it changes, newest entry marked, with caller shown as a module-relative
offset (caller - base) so it maps straight to a text.bin address.

  python3 -I tools/probe_f1_read.py
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

def out(m): print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)

def session():
    r = R(6543); r.cmd('qSupported:hwbreak+'); r.cmd('?')
    base = None
    for ln in r.rcmd('get info').splitlines():
        p = ln.split()
        if len(p) >= 4 and p[1] == '-' and (p[3] == 'main' or int(p[2],16)-int(p[0],16)+1 == 0x1EE1000):
            base = int(p[0], 16)
    out(f'connected base=0x{base:x}')
    r.s.sendall(b'$c#63'); out('resumed; do ONE wild KO, then I read the ring')
    SB = base + 0x1EE0F00; prev = None
    while True:
        time.sleep(1.0)
        d = r.rd(SB, 0x100)
        if not d or len(d) < 0xA0: continue
        count, = struct.unpack_from('<I', d, 0x00)
        entries = []
        for k in range(8):
            num, caller = struct.unpack_from('<II', d, 0x60 + k*8)
            off = caller - base
            entries.append((num, off if 0 <= off < 0x2000000 else caller))
        key = (count, tuple(entries))
        if key != prev:
            prev = key
            newest = (count - 1) & 7 if count else -1
            parts = []
            for k, (num, off) in enumerate(entries):
                mark = '*' if k == newest else ' '
                parts.append(f"{mark}[{k}] n={num} caller=0x{off:X}")
            out(f"count={count}\n    " + "\n    ".join(parts))

out('waiting for gdbstub…')
while True:
    try: session()
    except (OSError, ConnectionError): time.sleep(2)
