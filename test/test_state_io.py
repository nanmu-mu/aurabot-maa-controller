import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from state import write_json


class StateSharingTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows file sharing")
    def test_reader_without_delete_sharing_does_not_abort_state_update(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                      ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "state.json"
            write_json(file, {"status": "running", "battles": 6})
            handle = kernel.CreateFileW(str(file), 0x80000000, 3, None, 3, 0, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            timer = threading.Timer(1.0, lambda: kernel.CloseHandle(handle))
            timer.start()
            try:
                write_json(file, {"status": "running", "battles": 12})
            finally:
                timer.join()
            self.assertEqual(json.loads(file.read_text()), {"status": "running", "battles": 12})

    def test_persistent_denial_remains_an_error_and_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "state.json"
            write_json(file, {"status": "running"})
            with patch("state.os.replace", side_effect=PermissionError("locked")) as replace, patch("state.time.sleep"):
                with self.assertRaises(PermissionError):
                    write_json(file, {"status": "success"})
                self.assertEqual(replace.call_count, 51)
            self.assertEqual(json.loads(file.read_text()), {"status": "running"})
