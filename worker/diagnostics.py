"""Conservative interpretation of completed MaaCore 6.21.3 shopping diagnostics."""
import json
from pathlib import Path
import re

CALLBACK = re.compile(r"^\[[^\]]+\]\[INF\]\[P[^\]]+\]\[T[^\]]+\] Assistant::append_callback \| (\w+) (\{.*\})$")
MODE = re.compile(r"CreditShopping: m_is_white_list:\s*(\d)\s+m_force_shopping_if_credit_full:\s*(\d)")
SOLD_OUT = re.compile(r"match_templ \| SoldOut\.png \[opencv\] score: ([0-9.]+) rect: \[[^\]]+\] roi: \[([^\]]+)\]")

def credit_task(data):
    return (data.get("taskchain")=="Mall" and data.get("class")=="asst::CreditShoppingTask"
            and data.get("subtask")=="CreditShoppingTask")

def empty_priority_pass(lines, priorities):
    modes=[(i,MODE.search(line)) for i,line in enumerate(lines) if MODE.search(line)]
    if not modes or any(match.groups()!=("1","0") for _,match in modes): return None
    whole="\n".join(lines)
    if any(marker in whole for marker in ("[ERR]","CreditShop-BuyIt","Click with scaled coordinates","minitouch click")):
        return None
    if whole.count("append_callback | SubTaskError ")!=1: return None
    body=lines[modes[-1][0]:]
    text="\n".join(body)
    configured=re.findall(r"set_white_list \[([^\]]*)\]$",text,re.MULTILINE)
    if configured!=[", ".join(priorities)]: return None
    items=re.findall(r"need to buy (.+)$",text,re.MULTILINE)
    sold=[SOLD_OUT.search(line) for line in body if "match_templ | SoldOut.png " in line]
    if not items or len(items)>10 or any(item not in priorities for item in items): return None
    if len(sold)!=len(items) or not all(sold): return None
    scores=[float(match.group(1)) for match in sold]
    rois=[tuple(int(value.strip()) for value in match.group(2).split(",")) for match in sold]
    # Require strong, distinct sold-out matches; uncertain recognition remains an error.
    if not all(0.95<=score<=1 for score in scores) or any(len(roi)!=4 for roi in rois) or len(set(rois))!=len(items): return None
    return {"items":items,"minimumScore":min(scores)}

def priority_sold_out_evidence(job, directory, diagnostic):
    if (job.get("preset",{}).get("maaVersion")!="6.21.3" or diagnostic.get("kind")!="error"
            or diagnostic.get("code")!=20000 or not credit_task(diagnostic)
            or diagnostic.get("first") or diagnostic.get("what") or diagnostic.get("details")!={}):
        return None
    mall=next((task for task in job["preset"].get("tasks",[]) if task.get("type")=="Mall"),{})
    priorities=mall.get("params",{}).get("buy_first",[])
    if not priorities or not all(isinstance(item,str) and item for item in priorities): return None
    try:
        file=Path(directory)/"native"/"debug"/"asst.log"
        with file.open("rb") as stream:
            size=stream.seek(0,2)
            offset=max(0,size-2*1024*1024)
            stream.seek(offset)
            if offset: stream.readline()  # Discard a partial first record.
            lines=stream.read(2*1024*1024).decode("utf-8-sig").splitlines()
        active=None
        failures=[]
        taskids=[]
        completed=set()
        for line in lines:
            match=CALLBACK.match(line)
            if match:
                name,data=match.group(1),json.loads(match.group(2))
                if name=="AllTasksCompleted":
                    completed=set(data.get("finished_tasks",[]))
                if name=="SubTaskStart" and credit_task(data):
                    active={"taskid":data.get("taskid"),"lines":[line]}
                    continue
            if active: active["lines"].append(line)
            if not match: continue
            if name=="SubTaskError" and credit_task(data):
                valid=(active and active["taskid"]==data.get("taskid") and data.get("details")=={}
                       and not data.get("first") and not data.get("what"))
                failures.append(empty_priority_pass(active["lines"],priorities) if valid else None)
                taskids.append(data.get("taskid"))
                active=None
            elif name=="SubTaskCompleted" and credit_task(data):
                active=None
            elif name in ("TaskChainStart","TaskChainError","TaskChainStopped","SubTaskStopped","InternalError"):
                active=None
        if len(completed)!=6 or not all(taskid in completed for taskid in taskids): return None
        if len(failures)!=diagnostic.get("count") or not failures or not all(failures): return None
        return {"source":"native/debug/asst.log","matchedErrors":len(failures),
                "items":[item for evidence in failures for item in evidence["items"]],
                "minimumScore":min(evidence["minimumScore"] for evidence in failures)}
    except (OSError,UnicodeError,ValueError,TypeError):
        return None