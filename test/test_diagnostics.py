import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"worker"))
from state import Ledger,ORDER

PREFIX="[2026-11-06 15:17:59.194][INF][Px100][Tx101] "
ERROR={"class":"asst::CreditShoppingTask","subtask":"CreditShoppingTask",
       "taskchain":"Mall","taskid":5,"details":{}}

def callback(kind, details):
    return PREFIX+"Assistant::append_callback | "+kind+" "+json.dumps(details,ensure_ascii=False)

def sold_out_block(mode=1, score="0.982115", second_roi="798, 418, 220, 220"):
    return [
        callback("SubTaskStart",ERROR),
        PREFIX+f"CreditShopping: m_is_white_list: {mode}  m_force_shopping_if_credit_full:  0",
        PREFIX+"asst::CreditShopImageAnalyzer::set_white_list [招聘许可]",
        PREFIX+"need to buy 招聘许可",
        PREFIX+"need to buy 招聘许可",
        PREFIX+f"match_templ | SoldOut.png [opencv] score: {score} rect: [ 712, 468, 26, 90 ] roi: [ 545, 418, 220, 220 ]",
        PREFIX+f"match_templ | SoldOut.png [opencv] score: {score} rect: [ 965, 468, 26, 90 ] roi: [ {second_roi} ]",
        callback("SubTaskError",ERROR),
    ]

class SoldOutDiagnosticsTests(unittest.TestCase):
    def make_ledger(self, lines=None, event=None, count=1):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory=Path(temporary.name)
        job={"id":"offline","origin":{},"createdAt":0,"config":{"mode":"mock"},
             "preset":{"maaVersion":"6.21.3","tasks":[{"type":"Mall","params":{"buy_first":["招聘许可"]}}]}}
        ledger=Ledger(job,directory)
        for _ in range(count): ledger.event(20000,event or copy.deepcopy(ERROR))
        for chain in ORDER: ledger.event(10002,{"taskchain":chain})
        ledger.event(3,{})
        if lines is not None:
            file=directory/"native"/"debug"/"asst.log"
            file.parent.mkdir(parents=True)
            footer=callback("AllTasksCompleted",{"taskchain":"Award","finished_tasks":[1,2,3,4,5,6]})
            file.write_text("\n".join([*lines,footer])+"\n",encoding="utf-8")
        return ledger

    def test_confirmed_sold_out_is_reported_as_skipped_with_raw_error_kept(self):
        ledger=self.make_ledger(sold_out_block())
        self.assertTrue(ledger.value["warnings"])  # Before final evidence reconciliation.
        ledger.finish(True)
        self.assertEqual(ledger.value["status"],"success")
        self.assertEqual(ledger.value["warnings"],[])
        diagnostic=ledger.value["subtaskDiagnostics"][0]
        self.assertEqual(diagnostic["code"],20000)
        self.assertEqual(diagnostic["kind"],"skipped")
        self.assertIn("售罄",diagnostic["label"])
        self.assertEqual(diagnostic["evidence"]["items"],["招聘许可","招聘许可"])
        self.assertEqual(diagnostic["evidence"]["matchedErrors"],1)

    def test_missing_log_and_unsupported_version_do_not_hide_errors(self):
        for lines,version in [(None,"6.21.3"),(sold_out_block(),"6.21.4")]:
            with self.subTest(version=version,missing=lines is None):
                ledger=self.make_ledger(lines)
                ledger.job["preset"]["maaVersion"]=version
                ledger.finish(True)
                self.assertEqual(ledger.value["subtaskDiagnostics"][0]["kind"],"error")
                self.assertTrue(ledger.value["warnings"])

    def test_blacklist_pass_or_low_score_or_duplicate_roi_remains_error(self):
        for lines in [sold_out_block(mode=0),sold_out_block(score="0.5"),
                      sold_out_block(second_roi="545, 418, 220, 220"),
                      [x for x in sold_out_block() if "798, 418" not in x]]:
            with self.subTest(lines=lines):
                ledger=self.make_ledger(lines)
                ledger.finish(True)
                self.assertTrue(ledger.value["warnings"])

    def test_purchase_attempt_or_internal_error_is_not_sold_out_skip(self):
        for extra in [PREFIX+"Click with scaled coordinates (100, 200) 1.25",
                      PREFIX+"CreditShop-BuyIt",PREFIX.replace("[INF]","[ERR]")+"recognition failed"]:
            ledger=self.make_ledger([*sold_out_block()[:-1],extra,sold_out_block()[-1]])
            ledger.finish(True)
            self.assertEqual(ledger.value["subtaskDiagnostics"][0]["kind"],"error")

    def test_missing_start_marker_or_count_mismatch_remains_error(self):
        for lines,count in [(sold_out_block()[1:],1),(sold_out_block(),2),
                            (sold_out_block()+sold_out_block(),1)]:
            ledger=self.make_ledger(lines,count=count)
            ledger.finish(True)
            self.assertTrue(ledger.value["warnings"])

    def test_mixed_sold_out_and_real_error_must_not_be_globally_suppressed(self):
        bad=sold_out_block(mode=0)
        ledger=self.make_ledger(sold_out_block()+bad,count=2)
        ledger.finish(True)
        self.assertEqual(ledger.value["subtaskDiagnostics"][0]["kind"],"error")
        self.assertTrue(ledger.value["warnings"])

    def test_specific_error_details_are_not_reclassified(self):
        event={**ERROR,"what":"UnknownTask","details":{"tasks":["MissingTask"]}}
        ledger=self.make_ledger(sold_out_block(),event=event)
        ledger.finish(True)
        self.assertTrue(ledger.value["warnings"])
        self.assertIn("UnknownTask",ledger.value["warnings"][0])

    def test_cancelled_or_chain_failed_run_is_not_relabelled_as_clean_success(self):
        ledger=self.make_ledger(sold_out_block())
        ledger.stop_requested()
        ledger.finish(True)
        self.assertEqual(ledger.value["status"],"cancelled")
        self.assertTrue(ledger.value["warnings"])
        ledger=self.make_ledger(sold_out_block())
        ledger.event(10000,{"taskchain":"Mall"})
        ledger.finish(True)
        self.assertEqual(ledger.value["status"],"partial")

    def test_unrelated_warning_with_same_text_is_preserved(self):
        ledger=self.make_ledger(sold_out_block())
        ledger.event(20000,{"taskchain":"Mall","subtask":"Other","class":"Other",
                            "first":["CreditShoppingTask"],"details":{}})
        ledger.finish(True)
        self.assertEqual(ledger.value["subtaskDiagnostics"][0]["kind"],"skipped")
        self.assertEqual(ledger.value["subtaskDiagnostics"][1]["kind"],"error")
        self.assertTrue(ledger.value["warnings"])


    def test_earlier_purchase_or_error_before_retry_remains_a_warning(self):
        for marker in (PREFIX+"CreditShop-BuyIt",PREFIX.replace("[INF]","[ERR]")+"earlier failure"):
            lines=sold_out_block()[:-1]+[marker]+sold_out_block()[1:]
            ledger=self.make_ledger(lines)
            ledger.finish(True)
            self.assertTrue(ledger.value["warnings"])

    def test_incomplete_or_malformed_native_log_keeps_the_error(self):
        for data in ("not a completed native log",b"\xff\xfe"):
            ledger=self.make_ledger(sold_out_block())
            file=ledger.directory/"native"/"debug"/"asst.log"
            if isinstance(data,bytes): file.write_bytes(data)
            else: file.write_text(data,encoding="utf-8")
            ledger.finish(True)
            self.assertEqual(ledger.value["subtaskDiagnostics"][0]["kind"],"error")