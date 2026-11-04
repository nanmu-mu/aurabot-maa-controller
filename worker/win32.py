"""Small Win32 process/mutex surface. No shell, taskkill, or name-wide termination."""
import ctypes
from ctypes import wintypes as w
import hashlib
import ntpath
import os

def kernel():
    if os.name != "nt":
        raise RuntimeError("Real execution requires Windows")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, restype, args in [
        ("CreateMutexW", w.HANDLE, [w.LPVOID, w.BOOL, w.LPCWSTR]),
        ("WaitForSingleObject", w.DWORD, [w.HANDLE, w.DWORD]),
        ("ReleaseMutex", w.BOOL, [w.HANDLE]),
        ("CloseHandle", w.BOOL, [w.HANDLE]),
        ("OpenProcess", w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
        ("QueryFullProcessImageNameW", w.BOOL, [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]),
        ("GetProcessTimes", w.BOOL, [w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)]),
        ("TerminateProcess", w.BOOL, [w.HANDLE, w.UINT]),
        ("CreateToolhelp32Snapshot", w.HANDLE, [w.DWORD, w.DWORD]),
    ]:
        fn = getattr(k, name)
        fn.restype, fn.argtypes = restype, args
    return k

def mutex_name(maa_dir):
    normalized = ntpath.abspath(maa_dir).rstrip("\\/").upper()
    # Current audited installation is ASCII. Avoid unverified .NET Unicode casing differences.
    normalized.encode("ascii")
    return "MAA_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest().upper()

class Mutex:
    def __init__(self, name):
        self.k = kernel()
        self.handle = self.k.CreateMutexW(None, False, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = self.k.WaitForSingleObject(self.handle, 0)
        if result not in (0, 0x80):
            self.k.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError("互斥锁被占用，未启动任务")
    def close(self):
        if self.handle:
            self.k.ReleaseMutex(self.handle)
            self.k.CloseHandle(self.handle)
            self.handle = None
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

def _identity(k, handle, pid):
    size = w.DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    times = [w.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return {"pid": int(pid), "created": str(created), "path": ntpath.normcase(buf.value)}

def identity(pid):
    k = kernel()
    handle = k.OpenProcess(0x1000, False, int(pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try: return _identity(k, handle, pid)
    finally: k.CloseHandle(handle)

def terminate_exact(expected, allowed_executable):
    """Validate on the SAME handle used for termination; never chase reused PIDs."""
    k = kernel()
    handle = k.OpenProcess(0x1000 | 0x0001 | 0x00100000, False, int(expected["pid"]))
    if not handle:
        raise RuntimeError("目标进程不可核实，未执行终止")
    try:
        actual = _identity(k, handle, expected["pid"])
        if actual != expected or actual["path"] != ntpath.normcase(ntpath.abspath(allowed_executable)):
            raise RuntimeError("目标进程身份变化，未执行终止")
        if not k.TerminateProcess(handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        if k.WaitForSingleObject(handle, 5000) != 0:
            raise RuntimeError("未确认目标进程已退出")
        return True
    finally:
        k.CloseHandle(handle)

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize",w.DWORD),("cntUsage",w.DWORD),("th32ProcessID",w.DWORD),("th32DefaultHeapID",ctypes.c_size_t),
                ("th32ModuleID",w.DWORD),("cntThreads",w.DWORD),("th32ParentProcessID",w.DWORD),("pcPriClassBase",w.LONG),
                ("dwFlags",w.DWORD),("szExeFile",w.WCHAR * 260)]

def find_gui(maa_dir):
    k = kernel()
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    for n in ("Process32FirstW","Process32NextW"):
        getattr(k,n).argtypes = [w.HANDLE,ctypes.POINTER(PROCESSENTRY32W)]
        getattr(k,n).restype = w.BOOL
    found = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k.Process32FirstW(snapshot,ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == "maa.exe":
                actual = identity(entry.th32ProcessID)  # If inaccessible, fail closed.
                if actual["path"] == ntpath.normcase(ntpath.join(ntpath.abspath(maa_dir),"MAA.exe")):
                    found.append(actual)
            ok = k.Process32NextW(snapshot,ctypes.byref(entry))
    finally: k.CloseHandle(snapshot)
    if len(found) > 1: raise RuntimeError("存在多个同路径 GUI，无法唯一绑定关闭许可")
    return found[0] if found else None


def tcp_listener_pids(port):
    """IPv4 listener owners, read from the OS without probing or starting ADB."""
    import socket
    api=ctypes.WinDLL("iphlpapi",use_last_error=True)
    fn=api.GetExtendedTcpTable
    fn.argtypes=[w.LPVOID,ctypes.POINTER(w.DWORD),w.BOOL,w.ULONG,ctypes.c_int,w.ULONG]
    fn.restype=w.DWORD
    class Row(ctypes.Structure):
        _fields_=[("state",w.DWORD),("local_address",w.DWORD),("local_port",w.DWORD),
                  ("remote_address",w.DWORD),("remote_port",w.DWORD),("pid",w.DWORD)]
    size=w.DWORD(0)
    result=fn(None,ctypes.byref(size),False,2,3,0)  # AF_INET, TCP_TABLE_OWNER_PID_LISTENER
    if result not in (0,122): raise RuntimeError("无法读取 TCP 监听状态")
    for _ in range(3):
        buf=ctypes.create_string_buffer(size.value)
        result=fn(buf,ctypes.byref(size),False,2,3,0)
        if result==122: continue
        if result: raise RuntimeError("TCP 监听状态查询失败")
        count=w.DWORD.from_buffer(buf).value
        rows=(Row*count).from_buffer(buf,ctypes.sizeof(w.DWORD))
        return sorted({int(r.pid) for r in rows if socket.ntohs(r.local_port & 0xFFFF)==port})
    raise RuntimeError("TCP 监听状态持续变化，拒绝连接")

def in_job(pid=None):
    k=kernel()
    k.IsProcessInJob.argtypes=[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)]
    k.IsProcessInJob.restype=w.BOOL
    handle=k.OpenProcess(0x400,False,int(pid or os.getpid()))
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        value=w.BOOL()
        if not k.IsProcessInJob(handle,None,ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(value.value)
    finally: k.CloseHandle(handle)



def job_limits():
    member=in_job()
    if not member: return {"inJob":False,"killOnClose":False,"flags":0}
    class Basic(ctypes.Structure):
        _fields_=[("process_time",ctypes.c_int64),("job_time",ctypes.c_int64),("flags",w.DWORD),
                  ("min_working_set",ctypes.c_size_t),("max_working_set",ctypes.c_size_t),
                  ("active_processes",w.DWORD),("affinity",ctypes.c_size_t),("priority",w.DWORD),("scheduling",w.DWORD)]
    class Io(ctypes.Structure):
        _fields_=[(name,ctypes.c_uint64) for name in ("read_ops","write_ops","other_ops","read_bytes","write_bytes","other_bytes")]
    class Extended(ctypes.Structure):
        _fields_=[("basic",Basic),("io",Io),("process_memory",ctypes.c_size_t),("job_memory",ctypes.c_size_t),
                  ("peak_process_memory",ctypes.c_size_t),("peak_job_memory",ctypes.c_size_t)]
    k=kernel()
    k.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)]
    k.QueryInformationJobObject.restype=w.BOOL
    value=Extended()
    if not k.QueryInformationJobObject(None,9,ctypes.byref(value),ctypes.sizeof(value),None):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"inJob":True,"killOnClose":bool(value.basic.flags & 0x2000),"flags":int(value.basic.flags)}
