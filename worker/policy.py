"""Defense in depth: reject unsupported tasks before ANY native or emulator operation."""
import math
import os
import ntpath
import re
from state import ORDER

FIELDS = {
"StartUp":{"client_type","start_game_enabled","account_name"},
"Recruit":{"refresh","select","confirm","times","set_time","expedite","recruitment_time","report_to_penguin","report_to_yituliu","extra_tags_mode","first_tags","preserve_tags","force_refresh","level3_recruitment_permit_reserve"},
"Infrast":{"mode","facility","drones","threshold","replenish","dorm_notstationed_enabled","dorm_trust_enabled","reception_message_board","reception_clue_exchange","reception_send_clue","continue_training","fiammetta_recovery_enabled","use_pinus_sylvestris","use_perception_information","use_worldly_plight","use_abyssal_hunter"},
"Fight":{"stage","times","series","medicine","medicine_expire_days","stone","DrGrandet","report_to_penguin","report_to_yituliu","client_type"},
"Mall":{"shopping","visit_friends","credit_fight","buy_first","blacklist","force_shopping_if_credit_full","only_buy_discount","reserve_max_credit","formation_index"},
"Award":{"award","mail","recruit","orundum","mining","specialaccess","signinevent"}
}
HASH_FILES = {"core-dlls","resource-definitions"}

def require(condition, message):
    if not condition: raise ValueError(message)

def validate_job(job):
    c, p = job["config"],job["preset"]
    require(job.get("schema")==1 and re.fullmatch(r"[a-f0-9-]{36}",job["id"]) and isinstance(job.get("nonce"),str),"无效任务")
    require(c.get("mode") in ("mock","real"),"无效模式")
    require(c["mode"]!="real" or c.get("realEnabled") is True,"真实执行尚未启用，需要阶段三确认")
    require(p.get("schema")==1 and p.get("maaVersion")=="6.21.3","未核验版本")
    require(p.get("connection")=={"profile":"MuMuEmulator12","touchType":"minitouch","adbLiteEnabled":False},"连接参数未经核验")
    require([t["type"] for t in p["tasks"]]==ORDER,"不允许动态任务")
    for t in p["tasks"]:
        kind, a = t["type"],t["params"]
        require(set(a)==FIELDS[kind],"参数必须来自已核查的完整白名单")
        require(all(a[x] is False for x in ("report_to_penguin","report_to_yituliu") if x in a),"禁止外传")
        if kind=="StartUp":
            require(a["client_type"]=="Official" and a["start_game_enabled"] is True and a["account_name"]=="","禁止切换账号")
        elif kind=="Fight":
            require(a["stage"]=="1-7" and all(type(a[x]) is int and a[x]==0 for x in ("medicine","stone","medicine_expire_days")),"禁止敏感消耗")
            require(a["DrGrandet"] is False and a["client_type"]=="Official" and type(a["times"]) is int and 1<=a["times"]<=999,"作战策略不符")
            require(a["series"] in (1,2,3,4,5,6),"无效连战次数")
        elif kind=="Recruit":
            require(a["expedite"] is False and a["set_time"] is True and set(a["confirm"])<={3,4} and set(a["select"])<={4},"公招策略不符")
            require(type(a["times"]) is int and 0<=a["times"]<=4,"公招次数异常")
            require(a["recruitment_time"]=={"3":540,"4":540,"5":540,"6":540},"首版保留九小时公招")
        elif kind=="Infrast":
            require(a["mode"]==20000 and isinstance(a["facility"],list) and set(a["facility"])<={"Mfg","Trade","Control","Power","Reception","Office","Dorm","Processing","Training"},"基建模式不符")
            require(all(a[x] is False for x in ("continue_training","fiammetta_recovery_enabled","use_pinus_sylvestris","use_perception_information","use_worldly_plight","use_abyssal_hunter")),"不启用额外基建策略")
        elif kind=="Mall":
            require(a["credit_fight"] is False and {"讯使","嘉维尔","坚雷"}<=set(a["blacklist"]),"信用策略不符")
        elif kind=="Award":
            require(a["award"] is True and all(v is False for k,v in a.items() if k!="award"),"禁止领取入口扩展")
    if c["mode"]=="real":
        e = c["emulator"]
        require(e["index"]==0 and e["address"]=="127.0.0.1:16384","只允许绑定实例")
        require(ntpath.isabs(c["maaDir"]) and ntpath.basename(e["manager"]).lower()=="mumumanager.exe","无效安装路径")
        base = ntpath.dirname(ntpath.dirname(e["manager"]))
        for filename in (e["adb"],):
            require(ntpath.commonpath([base,filename]).lower()==base.lower(),"模拟器路径越界")
        expected_headless=ntpath.join(os.environ.get("ProgramW6432",os.environ.get("ProgramFiles","C:\\Program Files")),"MuMuVMMVbox","Hypervisor","MuMuVMMHeadless.exe")
        require(ntpath.normcase(ntpath.abspath(e["headlessExecutable"]))==ntpath.normcase(expected_headless),"未核验的虚拟机进程路径")
        require(set(p.get("sourceHashes",{}))==HASH_FILES and all(re.fullmatch("[a-f0-9]{64}",x) for x in p["sourceHashes"].values()),"缺少资源版本指纹")
    for name in ("connectionTimeoutSeconds","stopTimeoutSeconds"):
        value = c.get(name)
        require(isinstance(value,(int,float)) and math.isfinite(value) and 1<=value<=600,"无效超时")
    return job
