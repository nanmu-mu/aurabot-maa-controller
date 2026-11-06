import json
import os
import time
import uuid
from pathlib import Path
from diagnostics import priority_sold_out_evidence

ORDER = ["StartUp","Recruit","Infrast","Fight","Mall","Award"]
TERMINAL = {"success","partial","failed","cancelled","unknown"}
TASK_NAMES = dict(zip(ORDER,["唤醒","公招","基建","作战","信用","领奖"]))
# Audited MaaCore 6.21.3 uses these ProcessTask results as conditional probes.
CONDITION_CHECKS = {
    ("Infrast","ShamareThumbnail"):"巫恋加速条件",
    ("Infrast","UnlockClues"):"线索交流开启条件",
    ("Infrast","EndOfClueExchange"):"线索交流结束弹窗",
    ("Infrast","InfrastClueSelfFull"):"线索已满提示",
    ("Mall","CreditShop-NoMoney"):"信用不足提示",
}

def read_json(file, default=None):
    try: return json.loads(Path(file).read_text(encoding="utf-8-sig"))
    except FileNotFoundError: return default

def write_json(file, value):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + "." + str(uuid.uuid4()) + ".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    # Windows readers/scanners can deny replacement briefly; retry state I/O, never game actions.
    for attempt in range(51):
        try:
            os.replace(tmp,file)
            return
        except PermissionError:
            if attempt == 50: raise
            time.sleep(.1)

def milliseconds(): return int(time.time()*1000)

def subtask_warning(record):
    kind=record.get("kind")
    if kind not in ("error","stopped"): return None
    first=record.get("first",[])
    node=", ".join(str(x) for x in first) if isinstance(first,list) and first else str(record.get("subtask") or "未知节点")
    what=" / "+str(record["what"]) if record.get("what") else ""
    chain=record.get("taskchain")
    return TASK_NAMES.get(chain,chain or "未知任务")+"子步骤报告"+("错误" if kind=="error" else "停止")+"："+node+what

class Ledger:
    def __init__(self, job, directory):
        self.job, self.directory = job, Path(directory)
        self.value = {"id":job["id"],"mode":job["config"]["mode"],"origin":job["origin"],
                      "createdAt":job["createdAt"],"status":"connecting","safeToRelease":False,
                      "tasks":dict.fromkeys(ORDER,"pending"),"stats":{"drops":{},"battles":0},
                      "warnings":[]}
        self.all_completed = False
        self.task_ids = {}
        self.requested_stop = False
        self.drop_events = set()
        self.persist()
    def persist(self):
        self.value["heartbeatAt"] = milliseconds()
        write_json(self.directory/"state.json",self.value)
    def warning(self, text):
        if text not in self.value["warnings"]:
            self.value["warnings"] = (self.value["warnings"]+[text])[-10:]
    def subtask_event(self, code, chain, details):
        first = details.get("first",[])
        label = CONDITION_CHECKS.get((chain,first[0])) if isinstance(first,list) and len(first)==1 and isinstance(first[0],str) else None
        condition = (code==20000 and label and details.get("class")=="asst::ProcessTask"
                     and details.get("subtask")=="ProcessTask" and not details.get("what")
                     and details.get("details")=={} and not details.get("pre_task"))
        kind = "condition" if condition else ("requested-stop" if code==20004 and self.requested_stop else ("stopped" if code==20004 else "error"))
        record = {"code":code,"kind":kind,"taskchain":chain,"class":details.get("class"),
                  "subtask":details.get("subtask"),"first":first,"what":details.get("what"),
                  "details":details.get("details",{}),"label":label if condition else None}
        records = self.value.setdefault("subtaskDiagnostics",[])
        previous = next((item for item in records if all(item.get(k)==v for k,v in record.items())),None)
        now = milliseconds()
        if previous:
            previous.update(count=previous["count"]+1,lastAt=now)
        else:
            records.append({**record,"count":1,"firstAt":now,"lastAt":now})
            del records[:-50]
        warning=subtask_warning(record)
        if warning: self.warning(warning)
    def reconcile_subtask_diagnostics(self):
        records=self.value.get("subtaskDiagnostics",[])
        if len(records)>=50: return  # A truncated history cannot prove all causes of a warning.
        for record in records:
            evidence=priority_sold_out_evidence(self.job,self.directory,record)
            if not evidence: continue
            warning=subtask_warning(record)
            items="、".join(dict.fromkeys(evidence["items"]))
            record.update(kind="skipped",label="优先购买商品已售罄（"+items+"）",evidence=evidence)
            if not any(subtask_warning(other)==warning for other in records):
                self.value["warnings"]=[text for text in self.value["warnings"] if text!=warning]
    def event(self, code, details):
        chain = self.task_ids.get(details.get("taskid")) or details.get("taskchain")
        if code in (0,1):
            self.warning("Core 初始化或内部错误")
            self.value["fatal"] = True
        elif code == 3:
            self.all_completed = True
        elif code == 10001 and chain in ORDER:
            self.value["startedAt"] = self.value.get("startedAt",milliseconds())
            self.value["status"] = "stopping" if self.requested_stop else "running"
            self.value["currentTask"] = chain
            if self.value["tasks"][chain] != "error":
                self.value["tasks"][chain] = "running"
        elif code in (10000,10002,10004) and chain in ORDER:
            if code==10000:
                self.value["attentionKey"]="task-error"
                self.value["attention"]="预设步骤执行失败（"+chain+"），MAA 尚未完成；请查询实际状态，不自动重跑"
            previous = self.value["tasks"][chain]
            # A completed callback cannot erase an earlier unresolved chain error.
            if previous != "error":
                self.value["tasks"][chain] = {10000:"error",10002:"completed",10004:"stopped"}[code]
        elif code in (20000,20004):
            self.subtask_event(code,chain,details)
        if details.get("what") == "StageDrops":
            data = details.get("details",{})
            key = json.dumps(data,sort_keys=True,ensure_ascii=False)
            if key in self.drop_events:
                self.value["stats"]["incomplete"] = True
                self.warning("重复结算回调已去重；次数统计可能不完整")
                self.persist()
                return
            self.drop_events.add(key)
            stats = data.get("stats")
            if isinstance(stats,list):
                snapshot = {}
                for item in stats:
                    item_id, quantity = item.get("itemId"), item.get("quantity")
                    if isinstance(item_id,str) and isinstance(quantity,(int,float)) and quantity >= 0:
                        snapshot[item_id] = {"name":str(item.get("itemName") or item_id)[:80],"quantity":quantity}
                self.value["stats"]["drops"] = snapshot  # Already cumulative; NEVER sum these snapshots.
            else:
                self.value["stats"]["incomplete"] = True
            count = data.get("cur_times")
            if isinstance(count,int) and 0 < count <= 6:
                self.value["stats"]["battles"] += count
            else:
                self.value["stats"]["incomplete"] = True
            stage = data.get("stage",{}).get("stageCode")
            if isinstance(stage,str): self.value["stats"]["stage"] = stage[:40]
        if details.get("what") == "RecruitTagsRefreshed":
            stats = self.value["stats"]
            stats["recruitRefreshes"] = stats.get("recruitRefreshes",0)+1
        # RecruitResult is a prediction; deliberately not counted as obtained operators.
        self.persist()
    def stop_requested(self):
        self.requested_stop = True
        self.value["status"] = "stopping"
        self.persist()
    def finish(self, idle):
        if not idle: return False
        tasks = self.value["tasks"].values()
        if self.requested_stop:
            status = "cancelled"
        elif self.value.get("fatal"):
            status = "partial" if "completed" in tasks else "failed"
        elif "error" in tasks:
            status = "partial" if "completed" in tasks else "failed"
        elif self.all_completed and all(t=="completed" for t in tasks):
            status = "success"
        else:
            status = "unknown"
        if status=="success": self.reconcile_subtask_diagnostics()
        self.value.update(status=status,finishedAt=milliseconds(),safeToRelease=(status!="unknown"))
        if status == "unknown":
            self.value["reason"] = "缺少完整终态证据，保留任务锁，禁止自动重跑"
            self.value["stats"]["incomplete"] = True
        self.persist()
        return True
    def fail(self, reason, safe=True):
        self.value.update(status="failed" if safe else "unknown",reason=reason,finishedAt=milliseconds(),safeToRelease=safe)
        self.persist()
