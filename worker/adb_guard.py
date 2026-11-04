"""Check ADB's wire version BEFORE any command that could auto-restart its server."""
import re
import os
from win32 import tcp_listener_pids
import socket
import subprocess

def client_version(config):
    result=subprocess.run([config["adb"],"version"],capture_output=True,check=True,timeout=5,
                          creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    match=re.search(rb"Android Debug Bridge version 1\.0\.(\d+)",result.stdout)
    if not match: raise RuntimeError("不能核实 ADB 客户端协议版本，拒绝连接")
    return int(match.group(1))

def receive(sock,n):
    data=b""
    while len(data)<n:
        part=sock.recv(n-len(data))
        if not part: raise RuntimeError("共享 ADB 版本响应不完整")
        data+=part
    return data

def server_version():
    if not tcp_listener_pids(5037): return None
    try:
        sock=socket.create_connection(("127.0.0.1",5037),timeout=2)
    except ConnectionRefusedError:
        return None
    with sock:
        sock.sendall(b"000chost:version")
        if receive(sock,4)!=b"OKAY": raise RuntimeError("共享 ADB 不接受只读版本查询，拒绝连接")
        size=int(receive(sock,4),16)
        if size<1 or size>16: raise RuntimeError("共享 ADB 版本响应异常")
        value=receive(sock,size)
        if not re.fullmatch(rb"[0-9a-fA-F]{1,8}",value): raise RuntimeError("共享 ADB 版本无法识别")
        return int(value,16)

def check_shared_server(config):
    if any(os.environ.get(k) for k in ('ADB_SERVER_SOCKET','ADB_SERVER_PORT','ANDROID_ADB_SERVER_PORT','ANDROID_ADB_SERVER_ADDRESS')):
        raise RuntimeError('检测到自定义 ADB 服务环境，尚未核验，拒绝连接')
    client=client_version(config)  # 'adb version' does not connect/start a server.
    server=server_version()
    if server is not None and server!=client:
        raise RuntimeError("共享 ADB 协议版本不匹配；为避免自动重启公共服务，已拒绝连接，请主人手动处理")
    return {"client":client,"server":server,"compatible":True}
