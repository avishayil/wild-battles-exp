#!/usr/bin/env python3
"""kick_boot.py - one-shot gdbstub boot kick for this fragile Eden build.

With the GDB stub enabled the title halts at boot until a client sends $c. This sends
exactly one $c and closes CLEANLY (the single-connection stub re-listens only on a clean
close). It NEVER sets breakpoints. Run it while the title is stuck at "launching...".

Usage: python3 -I tools/kick_boot.py
"""
import socket, time, sys

csum = lambda p: b'%02x' % (sum(p) % 256)
try:
    s = socket.create_connection(('127.0.0.1', 6543), timeout=6)
except Exception as e:
    print("connect failed (is the stub enabled + title booting?):", e); sys.exit(1)
buf = b''
def rd():
    global buf
    s.settimeout(6)
    while b'#' not in buf or len(buf.split(b'#', 1)[1]) < 2:
        buf += s.recv(4096)
    if buf[:1] == b'+': buf = buf[1:]
    pkt, _, rest = buf.partition(b'#'); buf = rest[2:]; s.sendall(b'+'); return pkt
cmd = lambda p: (s.sendall(b'$' + p.encode() + b'#' + csum(p.encode())), rd())[1]
print("qSupported:", cmd('qSupported:hwbreak+')[:90].decode(errors='replace'))
print("stop reason:", cmd('?').decode(errors='replace'))

pump = '--pump' in sys.argv
if not pump:
    s.sendall(b'$c#63'); time.sleep(0.4); s.close()
    print("sent $c, closed cleanly — the title should advance now")
    sys.exit(0)

# Bounded continue-pump: send $c, wait briefly for the next boot stop; repeat. When a $c
# yields no stop within the window, the guest is running free (boot cleared) -> done.
# Clean close afterward so the stub re-listens for the read-only poller.
import re
le_pc = lambda h: int.from_bytes(bytes.fromhex(h.decode()), 'little')
for i in range(60):
    s.sendall(b'$c#63')
    try:
        pkt = rd()  # blocks until the next stop (short timeout below treats "none" as running)
    except socket.timeout:
        print(f"[pump] no stop after $c #{i+1} -> guest running free (boot cleared)")
        break
    m = re.search(rb'1f:([0-9a-f]{16})', pkt)
    pc = le_pc(m.group(1)) if m else None
    print(f"[pump] stop #{i+1}: {pkt[:24].decode(errors='replace')}"
          + (f" pc~0x{pc:x}" if pc else ""))
    s.settimeout(1.5)  # after the first, treat a quiet window as "running"
else:
    print("[pump] still stopping after 60 kicks — early-boot stop storm; may need more")
s.close()
print("closed cleanly")
