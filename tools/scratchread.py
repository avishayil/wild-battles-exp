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
        if not d or len(d)<0xFE: continue
        clr,=struct.unpack_from('<I',d,0x34)
        last_state,seen=struct.unpack_from('<II',d,0x40)
        result,entry_cnt=struct.unpack_from('<II',d,0x58)
        guard_hit,=struct.unpack_from('<I',d,0xD8)
        rewrite_cnt,=struct.unpack_from('<I',d,0xE0)
        armed,done=d[0xFC],d[0xFD]
        cur=(clr,last_state,seen,result,guard_hit,rewrite_cnt,armed,done)
        if cur!=prev:
            prev=cur
            states=' '.join(str(i) for i in range(16) if seen&(1<<i))
            s5='STATE5!' if seen&(1<<5) else ''
            out(f'states=[{states}]{s5} result={result} | clear={clr} guard={guard_hit} '
                f'armed={armed} done={done} REWRITE_CNT={rewrite_cnt}')
out('waiting for gdbstub…')
while True:
    try: session()
    except (OSError,ConnectionError): time.sleep(2)
