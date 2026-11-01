#!/bin/bash
# live_attach.sh — robust gdbstub attach for live Wild Battles EXP scratch observation.
#
# This Eden build (de7e6e01d4-master, macOS/MoltenVK) has a fragile single-connection gdbstub.
# This script encodes every hard-won rule so a live session "just works":
#   * The game halts at boot when gdbstub is on → a throwaway KICK client sends $c and
#     CLEANLY disconnects (the stub re-listens only on a clean close).
#   * The reader then attaches with --no-resume (NEVER sends $c; $c puts the stub in
#     await-stop and blocks reads).
#   * base is resolved via qXfer:libraries (this build's `monitor get info` is empty).
#
# PREREQUISITES (do these yourself — the harness can't):
#   1. Launch Eden from a terminal with the MoltenVK stability vars (a Finder double-click
#      does NOT apply them and the GPU present path can abort at boot):
#        MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=1 MVK_CONFIG_VK_SEMAPHORE_SUPPORT_STYLE=0 \
#          ~/Applications/eden.app/Contents/MacOS/eden
#   2. Enable the GDB stub in the GUI (Emulation → Configure → Debug → Enable GDB Stub, :6543).
#   3. Boot the Let's Go title. (Keep the shader cache — do NOT clear ~/.cache/eden/shader.)
#   WHEN DONE: disable the GDB stub again in the GUI, or your next casual launch hangs at boot.
#
# Usage: tools/live_attach.sh [extra args passed to e2e_autoplay.py, e.g. --species 5]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="$HERE/e2e_autoplay.py"
PORT=6543
listening(){ lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; }

echo "[live] waiting for the gdbstub to listen on :$PORT (enable it + boot the title)…"
for _ in $(seq 1 4000); do listening && break; sleep 0.3; done
listening || { echo "[live] stub never listened — is GDB Stub enabled and the title booting?"; exit 1; }

echo "[live] stub up — sending a clean boot kick (\$c, then clean close)…"
python3 -I - <<'PY'
import socket
csum=lambda p:b'%02x'%(sum(p)%256)
s=socket.create_connection(('127.0.0.1',6543),timeout=6); buf=b''
def rd():
    global buf
    while b'#' not in buf or len(buf.split(b'#',1)[1])<2: buf+=s.recv(4096)
    if buf[:1]==b'+': buf=buf[1:]
    pkt,_,rest=buf.partition(b'#'); buf=rest[2:]; s.sendall(b'+'); return pkt
cmd=lambda p:(s.sendall(b'$'+p.encode()+b'#'+csum(p.encode())), rd())[1]
cmd('qSupported:hwbreak+'); cmd('?')
s.sendall(b'$c#63')              # continue past the boot halt
import time; time.sleep(0.3)
s.close()                        # CLEAN close → stub re-listens
print("[kick] booted + detached cleanly")
PY

echo "[live] waiting for the stub to re-listen after the kick…"
for _ in $(seq 1 100); do listening && break; sleep 0.3; done
listening || { echo "[live] stub did not re-listen after kick"; exit 2; }

echo "[live] attaching read-only observer (no \$c; clean-exit safe)…"
exec python3 -I "$HARNESS" --no-resume --input none "$@"
