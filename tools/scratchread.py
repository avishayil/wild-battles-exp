import socket,binascii,struct,time
def cs(p): return b'%02x'%(sum(p)%256)
class R:
    def __init__(s,port): s.s=socket.create_connection(('127.0.0.1',port),timeout=6); s.buf=b''
    def _rd(s,to=6):
        s.s.settimeout(to)
        while True:
            i=s.buf.find(b'$')
            if i>=0:
                j=s.buf.find(b'#',i)
                if j>=0 and len(s.buf)>=j+3:
                    p=s.buf[i+1:j]; s.buf=s.buf[j+3:]; s.s.sendall(b'+'); return p
            d=s.s.recv(8192)
            if not d: raise ConnectionError
            s.buf+=d
    def cmd(s,p,to=6):
        s.s.sendall(b'$'+p.encode()+b'#'+cs(p.encode()))
        while True:
            pk=s._rd(to)
            if pk[:1]==b'O' and len(pk)>1: continue
            return pk.decode(errors='replace')
    def rcmd(s,t):
        r=s.cmd('qRcmd,'+t.encode().hex())
        try: return binascii.unhexlify(r).decode(errors='replace')
        except: return r
    def rd(s,a,n):
        r=s.cmd('m %x,%x'%(a,n))
        if not r or r.startswith('E'): return None
        try: return binascii.unhexlify(r)
        except: return None
log=open('scratchread.log','a',buffering=1)
def out(m): l=f'[{time.strftime("%H:%M:%S")}] {m}'; print(l,flush=True); log.write(l+'\n')
def session():
    r=R(6543)
    r.cmd('qSupported:hwbreak+'); r.cmd('?')
    base=None
    for ln in r.rcmd('get info').splitlines():
        p=ln.split()
        if len(p)>=4 and p[1]=='-' and (p[3]=='main' or int(p[2],16)-int(p[0],16)+1==0x1EE1000): base=int(p[0],16)
    out(f'connected base=0x{base:x}')
    r.s.sendall(b'$c#63'); out('resumed; play into a wild battle, sit at menu')
    SB=base+0x1EE0F00; prev=None  # safe .bss tail
    while True:
        time.sleep(1.0)
        d=r.rd(SB,0x100)
        if not d or len(d)<0xFF: continue
        # hardened build: +0x34 clear | +0x40 state +0x44 mask +0x58 result +0xC8 wild_hp
        # +0xD8 guard +0xE0 rewrite_cnt +0xFC armed +0xFD done +0xFE have
        clr,=struct.unpack_from('<I',d,0x34)
        state,seen=struct.unpack_from('<II',d,0x40)
        result,=struct.unpack_from('<I',d,0x58)
        pe,=struct.unpack_from('<I',d,0xF8)   # v0.4 pwb_encounter (set by HOOK_M, cleared after battle)
        wild_hp,=struct.unpack_from('<I',d,0xC8)
        species,=struct.unpack_from('<I',d,0xCC)  # v0.5 cave_R: wild species (u16, zero-ext)
        maxhp,=struct.unpack_from('<I',d,0xD0)    # v0.5 cave_R: wild max HP
        slot=d[0xD4]                              # v0.5 cave_R: actual battle-slot id captured
        guard,=struct.unpack_from('<I',d,0xD8)
        rw,=struct.unpack_from('<I',d,0xE0)
        a2,=struct.unpack_from('<I',d,0xE4)
        armed,done,have=d[0xFC],d[0xFD],d[0xFE]
        cur=(clr,state,seen,result,pe,wild_hp,species,maxhp,slot,guard,rw,a2,armed,done,have)
        if cur!=prev:
            prev=cur
            states=' '.join(str(i) for i in range(16) if seen&(1<<i))
            out(f'states=[{states}] result={result} | PWB_ENC={pe} clear={clr} guard={guard} A2_PWB={a2} '
                f'armed={armed} have={have} WILD_HP={wild_hp} SPECIES={species} MAXHP={maxhp} SLOT={slot} '
                f'done={done} REWRITE_CNT={rw}')
out('waiting for gdbstub…')
while True:
    try: session()
    except (OSError,ConnectionError): time.sleep(2)
