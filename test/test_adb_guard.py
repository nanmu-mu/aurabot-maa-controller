import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"worker"))
import adb_guard

class AdbGuardTests(unittest.TestCase):
    def test_no_listener_does_not_send_any_socket_request(self):
        with patch("adb_guard.tcp_listener_pids",return_value=[]),patch("adb_guard.socket.create_connection") as connect:
            self.assertIsNone(adb_guard.server_version())
            connect.assert_not_called()

    def test_mismatch_refuses_without_any_repair(self):
        with patch.dict(os.environ,{},clear=True),patch("adb_guard.client_version",return_value=41),patch("adb_guard.server_version",return_value=40):
            with self.assertRaisesRegex(RuntimeError,"拒绝"): adb_guard.check_shared_server({"adb":"unused"})

    def test_custom_server_environment_is_not_silently_ignored(self):
        with patch.dict(os.environ,{"ADB_SERVER_SOCKET":"tcp:somewhere:5038"},clear=True),patch("adb_guard.client_version") as version:
            with self.assertRaisesRegex(RuntimeError,"自定义"): adb_guard.check_shared_server({"adb":"unused"})
            version.assert_not_called()

    def test_wire_version_partial_reads_and_only_read_command(self):
        class Sock:
            def __init__(self): self.data=bytearray(b"OKAY00040029");self.sent=[]
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def sendall(self,data): self.sent.append(data)
            def recv(self,n):
                chunk=bytes(self.data[:min(2,n)]);del self.data[:len(chunk)];return chunk
        sock=Sock()
        with patch("adb_guard.tcp_listener_pids",return_value=[123]),patch("adb_guard.socket.create_connection",return_value=sock):
            self.assertEqual(adb_guard.server_version(),41)
            self.assertEqual(sock.sent,[b"000chost:version"])
