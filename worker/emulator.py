"""Only the fixed configured MuMu instance. No shared services or adb server commands."""
import json
import ntpath
import socket
import subprocess
import time
from win32 import identity, terminate_exact

def manager_call(config, *args):
    result = subprocess.run([config["manager"],*args],capture_output=True,timeout=8,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),check=True)
    return result.stdout.decode("utf-8-sig",errors="strict").strip()

def parse_info(text, config):
    obj = json.loads(text)
    if isinstance(obj,list):
        rows = obj
    elif isinstance(obj,dict) and "index" in obj:
        rows = [obj]
    elif isinstance(obj,dict):
        rows = list(obj.values())
    else:
        raise RuntimeError("MuMu 信息格式未核实")
    match = [x for x in rows if isinstance(x,dict) and str(x.get("index"))==str(config["index"])]
    if len(match)!=1:
        raise RuntimeError("不能唯一识别绑定 MuMu 实例")
    info = match[0]
    if info.get("error_code",0)!=0:
        raise RuntimeError("MuMu 实例查询失败")
    if "adb_port" in info and (int(info["adb_port"])!=16384 or info.get("adb_host_ip")!="127.0.0.1"):
        raise RuntimeError("MuMu 端点变化，拒绝操作")
    return info

def info(config): return parse_info(manager_call(config,"info","-v",str(config["index"])),config)

def ensure_started(config, cancelled, timeout):
    current = info(config)
    if not current.get("is_process_started"):
        manager_call(config,"control","-v",str(config["index"]),"launch")
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        if cancelled.is_set(): return False
        current = info(config)
        if current.get("is_android_started") and int(current.get("adb_port",0))==16384:
            with socket.socket() as s:
                s.settimeout(.5)
                if s.connect_ex(("127.0.0.1",16384))==0: return True
        time.sleep(.5)
    raise TimeoutError("绑定模拟器未在期限内就绪；不切换实例或重启")

def force_target(config):
    current = info(config)
    if not current.get("is_process_started"):
        return None
    if int(current.get("adb_port",0))!=16384:
        raise RuntimeError("没有运行态端点证据，拒绝强杀")
    pid = current.get("headless_pid")
    if not isinstance(pid,int) or pid<=0: raise RuntimeError("未获得实例专属 headless PID")
    target = identity(pid)
    if target["path"] != ntpath.normcase(ntpath.abspath(config["headlessExecutable"])):
        raise RuntimeError("虚拟机进程路径未核实，拒绝扩大终止范围")
    confirmed = info(config)
    if not confirmed.get("is_process_started") or confirmed.get("headless_pid")!=pid or int(confirmed.get("adb_port",0))!=16384:
        raise RuntimeError("实例映射在核验期间变化，拒绝终止")
    return target

def force_close(config):
    target=force_target(config)
    if target is None: return True
    terminate_exact(target,config["headlessExecutable"])
    # The bound device window can retain stale running state after its VM exits.
    manager_call(config,"control","-v",str(config["index"]),"shutdown")
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        if not info(config).get("is_process_started"): return True
        time.sleep(.25)
    raise RuntimeError("未确认指定模拟器关闭，不报告强制终止完全成功")
