#!/usr/bin/env python3
"""Replay a scratchread trace and assert the Wild Battles EXP invariants.

Usage: python3 -I tools/trace_assert.py [--strict] <scratchread.log> [more.log ...]

The reader (tools/scratchread.py) logs one line per *change* of the scratch state, e.g.:

  [23:51:44] states=[0 1 2 3 4 5 6 7 8 9 10] result=3 | PWB_ENC=0 clear=1 guard=2 \
      A2_PWB=8 armed=1 have=1 WILD_HP=0 SPECIES=19 MAXHP=15 SLOT=12 done=1 REWRITE_CNT=1

Fields persist between logged lines (change-only log). Each reader (re)connect starts a new
*session* (scratch is .bss and zeroes on relaunch). An *episode* is one PWB encounter: it
begins when PWB_ENC goes 0->1 and ends when it returns to 0.

Invariants (permissive, always checked):
  G1  REWRITE_CNT is monotonic non-decreasing within a session.
  G2  `clear` (hook A) and `A2_PWB` (hook P) only increase while PWB_ENC==1 (no hook activity
      outside a PWB encounter — trainer/overworld stay vanilla).
  E1  Every *closed* episode that sets the marker also clears it (no leak into the next battle).
  E2  A KO episode (done reaches 1): on the rewrite row result==3, WILD_HP==0, SLOT==12,
      SPECIES!=0, and REWRITE_CNT increments by exactly 1 over the episode.
  E3  A non-KO episode (flee / timeout / blackout — done never 1) never increments
      REWRITE_CNT and never sets done.

Strict mode (`--strict`, for a *completed* regression trace rather than a truncated debug one)
adds — these are the checks that distinguish "a hook only fired inside an episode" from "the
episode was actually classified and resolved correctly":
  S1  No episode may still be open at session end (the marker MUST have cleared). A permissive
      run only *notes* an open episode; a strict run FAILs it (stale-marker / missing-termination).
  S2  The rewrite event is *located*: in a KO episode REWRITE_CNT increments on exactly the row
      where `done` first becomes 1 (rewrite coincides with the KO decision, not merely "sometime
      in the episode"), and that row additionally has MAXHP>0.
  S3  Identity is present on every KO row (SLOT/SPECIES/MAXHP recorded) — fail-closed if the
      reader did not capture opponent identity, so we never bless an un-classified rewrite.

Exit 0 = all invariants hold; 1 = at least one violation (printed) or an unparseable file.
"""
import sys, re

FIELD = re.compile(r'(\w+)=(-?\d+)')


def parse(path):
    sessions, cur = [], []
    for ln in open(path):
        ln = ln.strip()
        if 'connected base' in ln:
            if cur: sessions.append(cur)
            cur = []
            continue
        if not ln.startswith('[') or '|' not in ln:
            continue  # skip 'waiting'/'resumed' lines
        ts = ln[1:ln.index(']')]
        d = {k: int(v) for k, v in FIELD.findall(ln.split('|', 1)[1])}
        m = re.search(r'result=(-?\d+)', ln.split('|', 1)[0])  # result= is left of the '|'
        if m:
            d['result'] = int(m.group(1))
        d['ts'] = ts
        cur.append(d)
    if cur: sessions.append(cur)
    return sessions


def check(path, strict=False):
    sessions = parse(path)
    fails = []
    def fail(msg): fails.append(msg)
    if not sessions:
        print(f"{path}: no trace rows parsed"); return ["empty"]

    n_ep = n_ko = n_non = 0
    open_eps = 0
    for rows in sessions:
        # G1: REWRITE_CNT monotonic within the session
        prev_rw = None
        for r in rows:
            rw = r.get('REWRITE_CNT')
            if rw is not None and prev_rw is not None and rw < prev_rw:
                fail(f"[{r['ts']}] G1 REWRITE_CNT went backwards {prev_rw}->{rw}")
            if rw is not None:
                prev_rw = rw
        # G2: clear / A2_PWB only increase while PWB_ENC==1
        for a, b in zip(rows, rows[1:]):
            for fld in ('clear', 'A2_PWB'):
                if b.get(fld, 0) > a.get(fld, 0) and b.get('PWB_ENC', 0) != 1:
                    fail(f"[{b['ts']}] G2 {fld} rose while PWB_ENC={b.get('PWB_ENC')}")
        # episodes: PWB_ENC 0->1 ... ->0
        episodes, ep = [], None
        for r in rows:
            pe = r.get('PWB_ENC', 0)
            if pe == 1 and ep is None:
                ep = [r]
            elif ep is not None:
                ep.append(r)
                if pe == 0:
                    episodes.append(ep); ep = None
        if ep is not None:
            open_eps += 1  # still active at session end
            if strict:
                # S1: a completed regression trace must not end mid-episode (stale marker)
                fail(f"[{ep[0]['ts']}] S1 episode never cleared the marker (open at session end)")
        for e in episodes:
            n_ep += 1
            rw0, rw1 = e[0].get('REWRITE_CNT', 0), e[-1].get('REWRITE_CNT', 0)
            ko = any(r.get('done') == 1 for r in e)
            if not any(r.get('PWB_ENC') == 0 for r in e):
                fail(f"[{e[0]['ts']}] E1 episode never cleared the marker")
            if ko:
                n_ko += 1
                k = next(r for r in e if r.get('done') == 1)
                if k.get('result') != 3:  fail(f"[{k['ts']}] E2 KO result={k.get('result')} (want 3)")
                if k.get('WILD_HP') != 0:  fail(f"[{k['ts']}] E2 KO WILD_HP={k.get('WILD_HP')} (want 0)")
                if k.get('SLOT') != 12:    fail(f"[{k['ts']}] E2 KO SLOT={k.get('SLOT')} (want 12)")
                if k.get('SPECIES', 0) == 0: fail(f"[{k['ts']}] E2 KO SPECIES==0")
                if rw1 - rw0 != 1:         fail(f"[{e[0]['ts']}] E2 KO REWRITE_CNT delta {rw1-rw0} (want 1)")
                if strict:
                    # S3: identity must be recorded on the KO row (fail-closed on un-classified KO)
                    for fld in ('SLOT', 'SPECIES', 'MAXHP'):
                        if k.get(fld) is None:
                            fail(f"[{k['ts']}] S3 KO row missing identity field {fld}")
                    if k.get('MAXHP', 0) <= 0:
                        fail(f"[{k['ts']}] S3 KO MAXHP={k.get('MAXHP')} (want > 0)")
                    # S2: the rewrite increment must land on the done-transition row, not elsewhere
                    rw_rows = [i for i in range(1, len(e))
                               if e[i].get('REWRITE_CNT', 0) > e[i-1].get('REWRITE_CNT', 0)]
                    done_row = next(i for i, r in enumerate(e) if r.get('done') == 1)
                    if rw_rows and rw_rows != [done_row]:
                        fail(f"[{k['ts']}] S2 rewrite rows {rw_rows} != done row [{done_row}] "
                             "(rewrite not coincident with KO decision)")
            else:
                n_non += 1
                if rw1 != rw0:             fail(f"[{e[0]['ts']}] E3 non-KO changed REWRITE_CNT {rw0}->{rw1}")
                if any(r.get('done') == 1 for r in e): fail(f"[{e[0]['ts']}] E3 non-KO set done")

    status = "OK" if not fails else "FAIL"
    note = f", {open_eps} open at session end" if open_eps else ""
    mode = "strict" if strict else "permissive"
    print(f"{path}: {status} [{mode}] — {len(sessions)} session(s), {n_ep} episodes "
          f"({n_ko} KO, {n_non} non-KO){note}")
    for f in fails:
        print("  ✗", f)
    return fails


def main():
    args = sys.argv[1:]
    strict = False
    if '--strict' in args:
        strict = True
        args = [a for a in args if a != '--strict']
    if not args:
        print(__doc__); sys.exit(2)
    allf = []
    for p in args:
        allf += check(p, strict=strict)
    sys.exit(1 if allf else 0)


if __name__ == '__main__':
    main()
