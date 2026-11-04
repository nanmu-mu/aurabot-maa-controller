"""Independent per-run worker. Stage two uses mock mode exclusively."""
import argparse
import hashlib
import json
import os
import ntpath
from pathlib import Path
import queue
import sys
import threading
import time
from policy import validate_job
from state import Ledger, ORDER, read_json, write_json, milliseconds
from win32 import Mutex, identity, terminate_exact, mutex_name, find_gui, in_job

def record_process(job, directory):
    value = identity(os.getpid())
    write_json(directory/"process.json",{**value,"runId":job["id"],"nonce":job["nonce"],"inWindowsJob":in_job()})

def mock_runner(job, events, cancelled, shared):
    cfg = job["config"].get("mock",{})
    scenario = cfg.get("scenario","success")
    step = max(.01,min(float(cfg.get("stepSeconds",.15)),10))
    if scenario=="connect_fail":
        events.put(("failure","模拟连接失败",True)); return
    if scenario=="crash": os._exit(9)
    events.put(("ids",{i+1:k for i,k in enumerate(ORDER)}))
    for n, chain in enumerate(ORDER):
        if cancelled.is_set():
            events.put(("idle",)); return
        events.put(("callback",10001,{"taskchain":chain,"taskid":n+1}))
        if scenario in ("hang","stop_delayed"):
            while not cancelled.is_set() or scenario=="stop_delayed":
                time.sleep(.05)
            events.put(("callback",10004,{"taskchain":chain,"taskid":n+1}))
            events.put(("idle",)); return
        if cancelled.wait(step):
            events.put(("idle",)); return
        if chain=="Fight":
            for amount in (6,12):
                events.put(("callback",20003,{"what":"StageDrops","details":{"stage":{"stageCode":"1-7"},"cur_times":6,"stats":[{"itemId":"30012","itemName":"固源岩","quantity":amount}]}}))
        if scenario=="unknown" and n>0: continue
        code = 10000 if (scenario=="partial" and chain=="Fight") or (scenario=="startup_fail" and chain=="StartUp") else 10002
        events.put(("callback",code,{"taskchain":chain,"taskid":n+1}))
    events.put(("callback",3,{}))
    events.put(("idle",))

def real_runner(job, directory, events, cancelled, shared):
    from emulator import ensure_started
    from adb_guard import check_shared_server
    from core import Core
    core = None
    try:
        cfg=job["config"]
        check_shared_server(cfg["emulator"])
        if not ensure_started(cfg["emulator"],cancelled,cfg["connectionTimeoutSeconds"]):
            events.put(("idle",)); return
        if cancelled.is_set(): events.put(("idle",)); return
        check_shared_server(cfg["emulator"])
        core = Core(job,directory/"native",events)
        shared["core"]=core
        if not core.connect(cfg["emulator"]):
            events.put(("failure","MAA 无法连接绑定实例，不自动恢复重跑",True)); return
        if cancelled.is_set(): events.put(("idle",)); return
        ids={}
        for t in job["preset"]["tasks"]:
            task_id=core.append(t["type"],t["params"])
            if task_id<=0: raise RuntimeError("Core 拒绝任务参数")
            ids[task_id]=t["type"]
        events.put(("ids",ids))
        if cancelled.is_set(): events.put(("idle",)); return
        if not core.start(): raise RuntimeError("Core 未接受启动")
        # A true start return is NOT the start notification; use task-chain callbacks.
        while core.running(): time.sleep(.05)
        events.put(("idle",))
    except Exception as error:
        events.put(("failure",str(error),not bool(core and core.running())))
    finally:
        if core and not core.running():
            core.close()

def device_mutex_name(job,directory):
    mode=job["config"]["mode"]
    if mode=="real":
        e=job["config"]["emulator"]
        scope=ntpath.normcase(ntpath.abspath(e["manager"]))+"|"+str(e["index"])+"|"+e["address"]
    else:
        scope=str(directory.parent.parent.resolve())
    return "AurabotMAA_"+mode+"_"+hashlib.sha256(scope.encode()).hexdigest()

def serve(job, directory):
    ledger = Ledger(job,directory)
    record_process(job,directory)
    mode=job["config"]["mode"]
    locks=[]
    try:
        locks.append(Mutex(device_mutex_name(job,directory)))
        if mode=="real":
            locks.append(Mutex(mutex_name(job["config"]["maaDir"])))
        events, cancelled, shared = queue.Queue(),threading.Event(),{}
        runner = real_runner if mode=="real" else mock_runner
        args=(job,directory,events,cancelled,shared) if mode=="real" else (job,events,cancelled,shared)
        thread=threading.Thread(target=runner,args=args,daemon=True)
        thread.start()
        seen_control=None
        stop_at=None
        began=time.monotonic()
        stop_dispatched=False
        idle_at=None
        failure=None
        while True:
            control=read_json(directory/"control.json",{})
            if control.get("id")!=seen_control and control.get("kind")=="stop":
                seen_control=control["id"]
                cancelled.set()
                ledger.stop_requested()
                stop_at=time.monotonic()
            if not ledger.value.get("startedAt") and time.monotonic()-began>job["config"]["connectionTimeoutSeconds"] and stop_at is None:
                cancelled.set()
                stop_at=time.monotonic()
                failure=("连接或启动超时，不重启模拟器或重跑日常",True)
                ledger.value["status"]="stopping"
                ledger.value["reason"]=failure[0]
                ledger.persist()
            if cancelled.is_set() and shared.get("core") and not stop_dispatched:
                stop_dispatched=True
                # AsstStop may block: keep the main loop alive for force-stop/reconciliation.
                threading.Thread(target=shared["core"].stop,daemon=True).start()
            try:
                event=events.get(timeout=.1)
                if event[0]=="callback":
                    ledger.event(event[1],event[2])
                    if event[1]==10000 and event[2].get("taskchain")=="StartUp":
                        cancelled.set()
                        stop_at=stop_at or time.monotonic()
                        failure=("开始唤醒失败，已终止后续依赖步骤；请检查游戏登录或连接，不自动重跑",True)
                        ledger.value["reason"]=failure[0]
                        ledger.persist()
                elif event[0]=="ids": ledger.task_ids=event[1]
                elif event[0]=="idle": idle_at=time.monotonic()
                elif event[0]=="failure": failure=(event[1],event[2]); idle_at=time.monotonic() if event[2] else None
            except queue.Empty: pass
            if stop_at and time.monotonic()-stop_at>job["config"]["stopTimeoutSeconds"]:
                ledger.value["attentionKey"]="stop-timeout"
                ledger.value["attention"]="温和停止尚未确认，不自动升级强杀；可明确要求强制终止"
                ledger.warning(ledger.value["attention"])
            if idle_at and time.monotonic()-idle_at>.25 and events.empty() and not thread.is_alive():
                if failure and not ledger.requested_stop:
                    ledger.fail(failure[0],failure[1])
                else:
                    ledger.finish(True)
                return
            if not thread.is_alive() and idle_at is None and events.empty():
                ledger.fail("执行线程异常结束，最终状态未核实",False)
                return
            if not hasattr(ledger,'last_heartbeat') or time.monotonic()-ledger.last_heartbeat>=1:
                ledger.last_heartbeat=time.monotonic()
                ledger.persist()
    except Exception as error:
        ledger.fail(str(error),not ledger.value.get("startedAt"))
    finally:
        for lock in reversed(locks): lock.close()

def inspect(job):
    if job["config"]["mode"]=="mock":
        return {"gui":{"mock":True,"pid":0,"created":"mock","path":"mock"} if job["config"].get("mock",{}).get("guiBusy") else None}
    with Mutex(device_mutex_name(job,Path(job["config"]["maaDir"]))):
        return {"gui":find_gui(job["config"]["maaDir"])}

def kill_gui(job):
    target=job.get("target")
    if job["config"]["mode"]=="mock":
        if target!={"mock":True,"pid":0,"created":"mock","path":"mock"}: raise RuntimeError("模拟目标不匹配")
        return {"ok":True}
    expected=find_gui(job["config"]["maaDir"])
    if expected!=target: raise RuntimeError("GUI 进程身份变化，许可失效")
    terminate_exact(target,str(Path(job["config"]["maaDir"])/"MAA.exe"))
    if find_gui(job["config"]["maaDir"]): raise RuntimeError("原 GUI 未退出")
    return {"ok":True}

def force(job, directory):
    # Persist the helper identity so host reloads also recognize deliberate termination.
    with Mutex(device_mutex_name(job,directory)+"_force"):
        marker=directory/"force.json"
        write_json(marker,{**identity(os.getpid()),"runId":job["id"],"at":milliseconds()})
        try: return force_owned(job,directory)
        finally: marker.unlink(missing_ok=True)

def force_owned(job, directory):
    proc=read_json(directory/"process.json")
    if not proc or proc.get("runId")!=job["id"] or proc.get("nonce")!=job["nonce"]:
        raise RuntimeError("缺少执行器归属证据，拒绝强杀")
    expected={k:proc[k] for k in ("pid","created","path")}
    own=identity(os.getpid())
    if expected["pid"]==os.getpid() or expected["path"]!=own["path"]: raise RuntimeError("执行器路径不匹配")
    # PID reuse means the original is gone; never kill the replacement process.
    try:
        current=identity(expected["pid"])
        was_alive=(current==expected)
    except OSError as error:
        if getattr(error,"winerror",None) not in (87,1168): raise
        was_alive=False
    if was_alive:
        terminate_exact(expected,own["path"])
    s=read_json(directory/"state.json")
    if not was_alive:
        s.setdefault("warnings",[]).append("原执行器已不存在，未终止任何替代进程；原任务结果仍按已有证据记录")
    closed=False
    try:
        if job["config"]["mode"]=="mock": closed=True
        else:
            from emulator import force_close
            closed=force_close(job["config"]["emulator"])
    except Exception as error:
        s.setdefault("warnings",[]).append(str(error))
    s.update(status="cancelled" if was_alive else s.get("status","unknown"),finishedAt=milliseconds(),emulatorClosed=closed,safeToRelease=closed,
             reason="已按明确请求终止或清理本次执行；已下发的游戏操作不会回滚")
    s.setdefault("stats",{})["incomplete"]=True
    for task,status in s.get("tasks",{}).items():
        if status=="running": s["tasks"][task]="stopped"
    write_json(directory/"state.json",s)
    return {"ok":closed,"message":("本次执行器已终止；" if was_alive else "原执行器已不存在，未杀替代进程；原结果保持不变；")+("绑定模拟器已关闭" if closed else "模拟器关闭未确认，保留锁等待核对")}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["serve","inspect","kill-gui","force"])
    parser.add_argument("--job",required=True)
    args=parser.parse_args()
    file=Path(args.job).resolve()
    job=validate_job(read_json(file))
    if args.command=="serve": serve(job,file.parent); return
    result={"inspect":lambda:inspect(job),"kill-gui":lambda:kill_gui(job),"force":lambda:force(job,file.parent)}[args.command]()
    print(json.dumps(result,ensure_ascii=True))

if __name__=="__main__":
    try: main()
    except Exception as error:
        print(json.dumps({"ok":False,"message":str(error)},ensure_ascii=True))
        sys.exit(1)
