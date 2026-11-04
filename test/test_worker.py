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
