"""Serial public CLI pairs, with external Lua process overlap recorded."""
from pathlib import Path
from datetime import datetime, timezone
import ctypes, ctypes.wintypes as w, json, struct, subprocess, sys, time
from compare import compare

HERE=Path(__file__).resolve().parent
class Entry(ctypes.Structure):
    _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),
        ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),
        ('flags',w.DWORD),('exe',w.WCHAR*260)]
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
k.CloseHandle.argtypes=[w.HANDLE]
def processes():
    handle=k.CreateToolhelp32Snapshot(2,0)
    assert handle != ctypes.c_void_p(-1).value
    result={};entry=Entry();entry.size=ctypes.sizeof(entry)
    try:
        ok=k.Process32FirstW(handle,ctypes.byref(entry))
        while ok:
            result[entry.pid]=(entry.parent,entry.exe)
            ok=k.Process32NextW(handle,ctypes.byref(entry))
    finally:k.CloseHandle(handle)
    return result
def foreign_lua(owner=None):
    snapshot=processes();owned={owner} if owner else set()
    for _ in range(12):
        previous=len(owned)
        owned.update(pid for pid,(parent,_) in snapshot.items() if parent in owned)
        if len(owned)==previous:break
    return [dict(pid=pid,parent=parent,exe=exe) for pid,(parent,exe) in snapshot.items()
        if exe.lower().startswith('lua') and exe.lower().endswith('.exe') and pid not in owned]
def now():return datetime.now(timezone.utc).isoformat()
pin='--pin-performance-cores' in sys.argv
if pin:
    query=k.GetSystemCpuSetInformation
    query.argtypes=[w.LPVOID,w.ULONG,ctypes.POINTER(w.ULONG),w.HANDLE,w.ULONG]
    length=w.ULONG();query(None,0,ctypes.byref(length),None,0)
    buffer=ctypes.create_string_buffer(length.value)
    assert query(buffer,length,ctypes.byref(length),None,0)
    offset=0;topology=[]
    while offset<length.value:
        size,kind=struct.unpack_from('II',buffer.raw,offset)
        if kind==0:
            topology.append(dict(group=struct.unpack_from('H',buffer.raw,offset+12)[0],
                logical=buffer.raw[offset+14],core=buffer.raw[offset+15],efficiency=buffer.raw[offset+18]))
        offset+=size
    assert {row['group'] for row in topology}=={0}
    best=max(row['efficiency'] for row in topology)
    mask=sum(1<<row['logical'] for row in topology if row['efficiency']==best)
    k.GetCurrentProcess.restype=w.HANDLE
    k.SetProcessAffinityMask.argtypes=[w.HANDLE,ctypes.c_size_t]
    assert k.SetProcessAffinityMask(k.GetCurrentProcess(),mask)
    (HERE/'cpu-condition.json').write_text(json.dumps(dict(at=now(),topology=topology,affinity_mask=mask),indent=2))
    print('PERFORMANCE CORE AFFINITY '+str(mask),flush=True)
prefix='pinned-' if pin else ''
order=[];comparisons=[]
for tag,scenario,variants in [
    ('screen','day_1_growth',['baseline','candidate']),
    ('final1','week_1_growth',['baseline','candidate']),
    ('final2','week_1_growth',['candidate','baseline']),
    ('final3','week_1_growth',['baseline','candidate']),
    ('short','day_1_growth',['baseline','candidate']),
]:
    tag=prefix+tag
    for variant in variants:
        while foreign_lua():
            print('WAIT external Lua before '+tag+' '+variant,flush=True)
            time.sleep(15)
        record=dict(tag=tag,scenario=scenario,variant=variant,started=now(),foreign_lua=[])
        print('START '+tag+' '+variant+' '+scenario,flush=True)
        child=subprocess.Popen([sys.executable,str(HERE/'bench.py'),variant,scenario,tag])
        while child.poll() is None:
            other=foreign_lua(child.pid)
            if other:record['foreign_lua'].append(dict(at=now(),processes=other))
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
        record.update(finished=now(),returncode=child.returncode)
        order.append(record)
        (HERE/(prefix+'final-order.json')).write_text(json.dumps(order,indent=2),encoding='utf-8')
        assert child.returncode==0,record
        assert not record['foreign_lua'],'External Lua overlap: retain receipt but exclude from formal timing'
    comparisons.append(compare(HERE/f'{tag}-baseline-{scenario}.json',HERE/f'{tag}-candidate-{scenario}.json'))
    (HERE/(prefix+'final-comparisons.json')).write_text(json.dumps(comparisons,indent=2),encoding='utf-8')
    print('MATCH '+tag,flush=True)
