"""Audited C API surface; loaded ONLY after the explicit real-execution gate."""
import ctypes
import hashlib
import json
import os
import threading
from pathlib import Path

def tree_digest(root, dlls_only=False):
    root = Path(root)
    candidates = list(root.iterdir()) if dlls_only else list(root.glob("*.json")) + list((root/"tasks").rglob("*.json"))
    if any(p.is_symlink() for p in candidates):
        raise RuntimeError("版本资源不得包含符号链接")
    files = [p for p in candidates if p.is_file() and (not dlls_only or p.suffix.lower()==".dll")]
    files.sort(key=lambda p:p.relative_to(root).as_posix().encode("utf-8"))
    h = hashlib.sha256()
    for p in files:
        h.update((p.relative_to(root).as_posix()+"\0"+hashlib.sha256(p.read_bytes()).hexdigest()+"\n").encode())
    return h.hexdigest()

class Core:
    def __init__(self, job, user_dir, events):
        self.lifecycle_lock = threading.Lock()
        cfg, preset = job["config"], job["preset"]
        user_dir = Path(user_dir)
        user_dir.mkdir(parents=True,exist_ok=True)
        directory = Path(cfg["maaDir"]).resolve()
        actual = {"core-dlls":tree_digest(directory,True),"resource-definitions":tree_digest(directory/"resource")}
        if actual != preset["sourceHashes"]:
            raise RuntimeError("MAA 或资源已变化，请重新核验并同步预设")
        self.dll_directory = os.add_dll_directory(str(directory))
        self.lib = ctypes.WinDLL(str(directory/"MaaCore.dll"))
        P, S, B, I = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool, ctypes.c_int
        self.callback_type = ctypes.CFUNCTYPE(None,I,S,P)
        for name, result, args in [
            ("AsstSetUserDir",B,[S]),("AsstLoadResource",B,[S]),("AsstGetVersion",S,[]),
            ("AsstCreateEx",P,[self.callback_type,P]),("AsstDestroy",None,[P]),
            ("AsstSetInstanceOption",B,[P,I,S]),("AsstConnect",B,[P,S,S,S]),
            ("AsstAppendTask",I,[P,S,S]),("AsstStart",B,[P]),("AsstStop",B,[P]),("AsstRunning",B,[P])
        ]:
            fn = getattr(self.lib,name)
            fn.restype, fn.argtypes = result,args
        def callback(code, payload, _):
            try: events.put(("callback",code,json.loads(payload or b"{}")))
            except Exception: events.put(("callback",0,{}))
        self.callback = self.callback_type(callback)
        self.handle = None
        if not self.lib.AsstSetUserDir(str(user_dir).encode()) or not self.lib.AsstLoadResource(str(directory).encode()):
            raise RuntimeError("Core 资源或独立日志目录加载失败")
        version = self.lib.AsstGetVersion().decode()
        if version.lstrip("v").split("+")[0] != "6.21.3": raise RuntimeError("Core 版本不匹配")
        self.handle = self.lib.AsstCreateEx(self.callback,None)
        if not self.handle: raise RuntimeError("Core 实例创建失败")
        # KillAdbOnExit=0; do not import the GUI's restart/hard-restart policies.
        options = [(2,preset["connection"]["touchType"].encode()),(4,b"0"),(5,b"0")]
        if not all(self.lib.AsstSetInstanceOption(self.handle,k,v) for k,v in options):
            raise RuntimeError("不能关闭退出时的 ADB 清理，拒绝启动")
    def connect(self, config):
        return self.lib.AsstConnect(self.handle,config["adb"].encode(),config["address"].encode(),b"MuMuEmulator12")
    def append(self, type_name, params):
        return self.lib.AsstAppendTask(self.handle,type_name.encode(),json.dumps(params,ensure_ascii=False).encode())
    def start(self): return self.lib.AsstStart(self.handle)
    def stop(self):
        with self.lifecycle_lock:
            return self.lib.AsstStop(self.handle) if self.handle else False
    def running(self): return self.lib.AsstRunning(self.handle)
    def close(self):
        with self.lifecycle_lock:
            if self.handle:
                self.lib.AsstDestroy(self.handle)
                self.handle = None
