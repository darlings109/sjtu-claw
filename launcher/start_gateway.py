r"""SJTUClaw 启动器

双击入口：拉起 Gateway，就绪后自动打开浏览器。

项目位于 WSL，而 WSL 与 Windows 的 loopback 相互隔离 —— 在 WSL 内启动的
服务，Windows 浏览器无法访问。因此必须由 Windows 侧的解释器加载本项目
（\\wsl.localhost\... 路径可直接读取），端口才会落在 Windows 的 localhost 上。
"""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PORT = 5000
READY_TIMEOUT = 40


def _gateway_python() -> str:
    """挑选运行 Gateway 的解释器

    优先项目 venv（依赖齐全）。但若本脚本是被本机解释器拉起的，则沿用它——
    从 \\wsl.localhost 启动 exe 会触发 Windows 网络区域的"打开文件-安全警告"
    弹窗，脚本模式下该弹窗不可见，进程会一直挂住。
    """
    if sys.executable and not sys.executable.startswith("\\\\"):
        return sys.executable

    venv = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if os.name == "nt" and os.path.exists(venv):
        return venv
    return sys.executable


def _health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/health"


def is_running(port: int) -> bool:
    """端口上是否已有健康的 Gateway"""
    try:
        with urllib.request.urlopen(_health_url(port), timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def port_taken(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pick_port(preferred: int) -> int:
    """首选端口被非 Gateway 程序占用时，顺延寻找可用端口"""
    if not port_taken(preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 20):
        if not port_taken(candidate):
            return candidate
    raise RuntimeError(f"{preferred}-{preferred + 19} 端口均不可用")


def spawn_gateway(port: int) -> subprocess.Popen:
    """在后台启动 Gateway，日志写入 logs/gateway.log"""
    log_dir = os.path.join(ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "gateway.log"), "a", encoding="utf-8")
    log_file.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 (port={port}) =====\n")
    log_file.flush()

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    return subprocess.Popen(
        [_gateway_python(), "-m", "src.main", "gateway", "--port", str(port)],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def wait_ready(port: int, proc: subprocess.Popen) -> bool:
    """轮询健康检查直到就绪；进程中途退出则立即失败"""
    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        if is_running(port):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.4)
    return False


def fail(message: str) -> None:
    print(f"\n[启动失败] {message}")
    print(f"详细日志：{os.path.join(ROOT, 'logs', 'gateway.log')}")
    if os.name == "nt":
        os.system("pause")
    sys.exit(1)


def parse_args(argv):
    port = DEFAULT_PORT
    open_browser = True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.isdigit():
            port = int(a)
        elif a in ("--port", "-p") and i + 1 < len(argv):
            i += 1
            port = int(argv[i])
        elif a == "--no-browser":
            open_browser = False
        i += 1
    return port, open_browser


def main() -> None:
    port, open_browser = parse_args(sys.argv[1:])

    print("SJTUClaw 启动器")
    print(f"项目目录：{ROOT}\n")

    if is_running(port):
        print(f"Gateway 已在运行（端口 {port}），直接打开界面。")
        if open_browser:
            webbrowser.open(f"http://localhost:{port}")
        return

    try:
        actual_port = pick_port(port)
    except RuntimeError as e:
        fail(str(e))

    if actual_port != port:
        print(f"端口 {port} 已被占用，改用 {actual_port}")
    port = actual_port

    print(f"正在启动 Gateway（端口 {port}）…")
    proc = spawn_gateway(port)

    if not wait_ready(port, proc):
        if proc.poll() is not None:
            fail("Gateway 进程已退出，通常是 .env 配置缺失或依赖未安装。")
        fail(f"等待 {READY_TIMEOUT} 秒仍未就绪。")

    url = f"http://localhost:{port}"
    print(f"启动成功：{url}")
    if open_browser:
        webbrowser.open(url)
        print("界面已在浏览器打开。关闭本窗口不会停止服务。")
    else:
        print("关闭本窗口不会停止服务。")


if __name__ == "__main__":
    main()
