import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"worker"))
from state import Ledger,ORDER,read_json
from policy import validate_job
from emulator import parse_info,force_close
from win32 import Mutex,mutex_name

ROOT=Path(__file__).resolve().parents[1]

def job():
    return {"schema":1,"id":"00000000-0000-0000-0000-000000000000","nonce":"offline",
            "origin":{"userId":"test","chatId":"private:test","messageId":"1"},"createdAt":0,
            "preset":read_json(ROOT/"presets/daily.json"),"config":read_json(ROOT/"controller.example.json")}

class WorkerTests(unittest.TestCase):
    def test_completion_requires_every_chain_and_idle(self):
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(job(),d)
            l.event(3,{})
            self.assertFalse(l.finish(False))
            l.finish(True)
            self.assertEqual(l.value["status"],"unknown")
            self.assertFalse(l.value["safeToRelease"])

    def test_error_is_not_erased_by_completed_or_all_completed(self):
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(job(),d)
            for chain in ORDER: l.event(10002,{"taskchain":chain})
            l.event(10000,{"taskchain":"Fight"})
            l.event(10002,{"taskchain":"Fight"})
            l.event(3,{})
            l.finish(True)
            self.assertEqual(l.value["status"],"partial")

    def test_stopped_callback_does_not_prove_owner_cancelled(self):
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(job(),d)
            l.event(10004,{"taskchain":"Fight"})
            l.finish(True)
            self.assertEqual(l.value["status"],"unknown")
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(job(),d)
            l.stop_requested()
            self.assertFalse(l.finish(False))
            l.finish(True)
            self.assertEqual(l.value["status"],"cancelled")

    def test_drop_snapshots_and_duplicate_callbacks(self):
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(job(),d)
            for n in (6,12,12):
                l.event(20003,{"what":"StageDrops","details":{"cur_times":6,"stats":[{"itemId":"rock","itemName":"rock","quantity":n}]}})
            self.assertEqual(l.value["stats"]["drops"]["rock"]["quantity"],12)
            self.assertEqual(l.value["stats"]["battles"],12)
            self.assertTrue(l.value["stats"]["incomplete"])

    def test_recruit_prediction_is_never_obtained_operator(self):
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(job(),d)
            l.event(20003,{"what":"RecruitResult","details":{"result":[{"opers":["example"]}]}})
            self.assertNotIn("operators",l.value["stats"])

    def test_native_gate_rejects_before_hardware_import(self):
        j=job();j["config"]["mode"]="real";j["config"]["realEnabled"]=False
        with self.assertRaisesRegex(ValueError,"尚未启用"): validate_job(j)

    def test_independent_policy_rejects_all_sensitive_entrances(self):
        validate_job(job())
        for index,key,value in [(3,"stone",1),(3,"medicine",1),(3,"stone",False),(5,"recruit",True),(1,"expedite",True),(1,"confirm",[6]),(3,"report_to_penguin",True)]:
            j=job();j["preset"]["tasks"][index]["params"][key]=value
            with self.assertRaises(ValueError): validate_job(j)

    def test_unaudited_versions_are_rejected_before_native_operations(self):
        for version in ("6.21.1","6.21.4"):
            j=job();j["preset"]["maaVersion"]=version
            with self.assertRaisesRegex(ValueError,"未核验版本"): validate_job(j)

    def test_instance_binding_refuses_other_port_and_ambiguous_info(self):
        c=job()["config"]["emulator"]
        self.assertEqual(parse_info('{"index":"0","adb_host_ip":"127.0.0.1","adb_port":16384}',c)["index"],"0")
        with self.assertRaises(RuntimeError): parse_info('{"index":"0","adb_host_ip":"127.0.0.1","adb_port":16385}',c)
        with self.assertRaises(RuntimeError): parse_info('[{"index":0},{"index":0}]',c)
        with patch("emulator.info",return_value={"index":"0","is_process_started":True,"adb_port":16384,"headless_pid":999}),patch("emulator.identity",return_value={"pid":999,"created":"1","path":"shared-service.exe"}),patch("emulator.terminate_exact") as kill:
            with self.assertRaises(RuntimeError): force_close(c)
            kill.assert_not_called()

    @unittest.skipUnless(os.name=="nt","Windows mutex")
    def test_mutex_contention_uses_synthetic_test_name(self):
        name="AurabotOfflineTest_"+str(os.getpid())
        code="import sys; sys.path.insert(0,sys.argv[1]); from win32 import Mutex; Mutex(sys.argv[2])"
        with Mutex(name):
            p=subprocess.run([sys.executable,"-c",code,str(ROOT/"worker"),name],capture_output=True)
            self.assertNotEqual(p.returncode,0)
        with Mutex(name): pass

    def test_gui_mutex_name_matches_audited_dotnet_algorithm(self):
        expected="MAA_"+hashlib.sha256("E:\\MAA".encode()).hexdigest().upper()
        self.assertEqual(mutex_name("e:\\maa\\"),expected)

if __name__=="__main__": unittest.main()

class AdditionalSafetyTests(unittest.TestCase):
    def test_vm_mapping_changed_before_kill_is_refused(self):
        c=job()["config"]["emulator"]
        first={"index":"0","is_process_started":True,"adb_port":16384,"headless_pid":999}
        second={**first,"headless_pid":1000}
        import ntpath
        with patch("emulator.info",side_effect=[first,second]),patch("emulator.identity",return_value={"pid":999,"created":"1","path":ntpath.normcase(c["headlessExecutable"])}),patch("emulator.terminate_exact") as kill:
            with self.assertRaisesRegex(RuntimeError,"映射"): force_close(c)
            kill.assert_not_called()

    def test_real_device_lock_is_independent_of_data_and_maa_directory(self):
        from worker import device_mutex_name
        a=job();a["config"]["mode"]="real"
        b=copy.deepcopy(a);b["config"]["maaDir"]="D:\\another-maa"
        self.assertEqual(device_mutex_name(a,Path("first")),device_mutex_name(b,Path("second")))

class ForceCloseRegressionTests(unittest.TestCase):
    def test_force_closes_bound_device_window_after_vm_kill(self):
        c=job()["config"]["emulator"]
        target={"pid":999,"created":"1","path":c["headlessExecutable"]}
        closed=False
        def shutdown(config,*args):
            nonlocal closed
            self.assertEqual(args,("control","-v","0","shutdown"))
            closed=True
            return '{"errcode":0}'
        with patch("emulator.force_target",return_value=target),patch("emulator.terminate_exact") as kill,patch("emulator.manager_call",side_effect=shutdown) as command,patch("emulator.info",side_effect=lambda _: {"is_process_started":not closed}),patch("emulator.time.monotonic",side_effect=[0,1,6]),patch("emulator.time.sleep"):
            self.assertTrue(force_close(c))
            kill.assert_called_once_with(target,c["headlessExecutable"])
            command.assert_called_once()


class SubtaskDiagnosticsTests(unittest.TestCase):
    def probe(self, first, chain="Infrast"):
        return {"class":"asst::ProcessTask","subtask":"ProcessTask","taskchain":chain,
                "first":[first],"pre_task":"","details":{}}

    def test_recorded_condition_checks_do_not_become_generic_errors(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(job(),d)
            probes=[("ShamareThumbnail","Infrast",1),("UnlockClues","Infrast",2),
                    ("EndOfClueExchange","Infrast",2),("InfrastClueSelfFull","Infrast",1),
                    ("CreditShop-NoMoney","Mall",6)]
            for first,chain,count in probes:
                for _ in range(count): ledger.event(20000,self.probe(first,chain))
            for chain in ORDER: ledger.event(10002,{"taskchain":chain})
            ledger.event(3,{})
            ledger.finish(True)
            self.assertEqual(ledger.value["status"],"success")
            self.assertEqual(ledger.value["warnings"],[])
            diagnostics=ledger.value["subtaskDiagnostics"]
            self.assertEqual(len(diagnostics),5)
            self.assertEqual(sum(item["count"] for item in diagnostics),12)
            self.assertTrue(all(item["kind"]=="condition" for item in diagnostics))
            self.assertEqual(read_json(Path(d)/"state.json")["subtaskDiagnostics"],diagnostics)

    def test_unknown_or_context_changed_errors_remain_specific_warnings(self):
        for event in [self.probe("UnknownNode"),
                      self.probe("CreditShop-NoMoney","Fight"),
                      {**self.probe("UnlockClues"),"what":"UnknownTask","details":{"tasks":["MissingTask"]}},
                      {**self.probe("UnlockClues"),"class":"OtherTask"}]:
            with self.subTest(event=event),tempfile.TemporaryDirectory() as d:
                ledger=Ledger(job(),d)
                ledger.event(20000,event)
                self.assertEqual(ledger.value["subtaskDiagnostics"][0]["kind"],"error")
                self.assertIn(event["first"][0],ledger.value["warnings"][0])
                self.assertNotIn("详见本地诊断",ledger.value["warnings"][0])
                if event.get("what"): self.assertIn("UnknownTask",ledger.value["warnings"][0])
                self.assertEqual(ledger.value["subtaskDiagnostics"][0]["details"],event["details"])

    def test_requested_and_unrequested_subtask_stops_are_distinct(self):
        for requested in (False,True):
            with tempfile.TemporaryDirectory() as d:
                ledger=Ledger(job(),d)
                if requested: ledger.stop_requested()
                ledger.event(20004,self.probe("FightBegin","Fight"))
                self.assertEqual(ledger.value["subtaskDiagnostics"][0]["kind"],"requested-stop" if requested else "stopped")
                self.assertEqual(bool(ledger.value["warnings"]),not requested)

class FinishedCleanupTests(unittest.TestCase):
    def finished(self, status="success"):
        from state import write_json
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        j=job();j["config"]["mode"]="real"
        directory=Path(temporary.name)/"runtime"/"runs"/j["id"]
        state={"id":j["id"],"status":status,"safeToRelease":True,"finishedAt":123,
               "startedAt":1,"tasks":dict.fromkeys(ORDER,"completed"),"warnings":["原有记录"],
               "stats":{"battles":30,"drops":{"rock":{"name":"固源岩","quantity":40}}},
               "reason":"原任务说明"}
        write_json(directory/"state.json",state)
        write_json(directory/"process.json",{"runId":j["id"],"nonce":j["nonce"],"pid":999,
                                            "created":"old","path":"python.exe"})
        write_json(directory.parent.parent/"active.json",{"id":j["id"]})
        return j,directory,copy.deepcopy(state)

    def mocks(self):
        from contextlib import ExitStack,nullcontext
        stack=ExitStack()
        stack.enter_context(patch("worker.identity",side_effect=lambda pid: {"pid":pid,"created":"new","path":"python.exe"}))
        kill=stack.enter_context(patch("worker.terminate_exact"))
        close=stack.enter_context(patch("emulator.force_close",return_value=True))
        mutex=stack.enter_context(patch("worker.Mutex",side_effect=lambda _: nullcontext()))
        return stack,kill,close,mutex

    def test_cleanup_preserves_original_results_times_stats_and_warnings(self):
        from worker import force_owned
        for status in ("success","partial","failed","cancelled"):
            with self.subTest(status=status):
                j,directory,before=self.finished(status)
                stack,kill,close,_=self.mocks()
                with stack:
                    result=force_owned(j,directory)
                after=read_json(directory/"state.json")
                self.assertTrue(result["ok"])
                self.assertTrue(after["cleanup"]["ok"])
                self.assertTrue(after["emulatorClosed"])
                for key,value in before.items(): self.assertEqual(after[key],value,key)
                kill.assert_not_called()  # Reused PID is never terminated.
                close.assert_called_once_with(j["config"]["emulator"])

    def test_cleanup_failure_does_not_rewrite_the_original_result(self):
        from worker import force_owned
        j,directory,before=self.finished()
        stack,kill,close,_=self.mocks()
        with stack:
            close.side_effect=RuntimeError("关闭未确认")
            result=force_owned(j,directory)
        after=read_json(directory/"state.json")
        self.assertFalse(result["ok"])
        self.assertFalse(after["cleanup"]["ok"])
        self.assertIn("关闭未确认",after["cleanup"]["reason"])
        for key,value in before.items(): self.assertEqual(after[key],value,key)
        kill.assert_not_called()

    def test_busy_device_or_maa_never_closes_another_task(self):
        from contextlib import nullcontext
        from worker import force_owned
        for fail_at in (1,2):
            with self.subTest(fail_at=fail_at):
                j,directory,before=self.finished()
                stack,kill,close,mutex=self.mocks()
                def lock(name):
                    if mutex.call_count==fail_at: raise RuntimeError("资源被占用")
                    return nullcontext()
                with stack:
                    mutex.side_effect=lock
                    result=force_owned(j,directory)
                self.assertFalse(result["ok"])
                self.assertEqual(read_json(directory/"state.json")["status"],before["status"])
                close.assert_not_called()
                kill.assert_not_called()

    def test_superseded_job_cannot_close_the_current_instance(self):
        from state import write_json
        from worker import force_owned
        j,directory,_=self.finished()
        write_json(directory.parent.parent/"active.json",{"id":"newer-job"})
        stack,kill,close,_=self.mocks()
        with stack: result=force_owned(j,directory)
        self.assertFalse(result["ok"])
        close.assert_not_called()
        kill.assert_not_called()

    def test_missing_ownership_proof_is_still_rejected(self):
        from state import write_json
        from worker import force_owned
        j,directory,_=self.finished()
        proc=read_json(directory/"process.json");proc["nonce"]="wrong"
        write_json(directory/"process.json",proc)
        stack,kill,close,_=self.mocks()
        with stack:
            with self.assertRaisesRegex(RuntimeError,"归属"): force_owned(j,directory)
        close.assert_not_called()
        kill.assert_not_called()
