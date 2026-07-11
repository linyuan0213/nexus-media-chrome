"""浏览器管理和自动化功能 — subprocess 启 Chrome + DrissionPage 连接。"""

import asyncio
import os
import socket
import subprocess
import threading
import time as _time
from typing import IO, List, Optional

from DrissionPage import Chromium, ChromiumOptions
from loguru import logger

from src.config.settings import (
    BROWSER_MONITOR_INTERVAL,
    CHROME_PATH,
    DEFAULT_FINGERPRINT_PROFILE,
    HEADLESS_MODE,
    REMOTE_CHROME_ADDRESS,
    USER_DATA_PATH,
)
from src.core.fingerprint import FingerprintManager

XVFB_DISPLAY = ":99"
DEBUG_PORT = 9222


def _build_chrome_args(profile_name: Optional[str] = None) -> List[str]:
    """根据指纹 profile 构建 Chrome 启动参数。"""
    os.makedirs(USER_DATA_PATH, exist_ok=True)
    fp = FingerprintManager(profile_name)
    args: List[str] = []
    if HEADLESS_MODE:
        args.append(HEADLESS_MODE)
    args.extend([
        f"--user-data-dir={USER_DATA_PATH}",
        "--no-sandbox",
        "--no-zygote",
        "--disable-dev-shm-usage",
        "--disable-setuid-sandbox",
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--use-angle=swiftshader-webgl",
        "--use-gl=swiftshader-webgl",
        "--no-first-run",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--metrics-recording-only",
        "--password-store=basic",
        "--disable-component-extensions-with-background-pages",
        "--lang=zh-CN",
        "--accept-lang=zh-CN,zh,en-US,en",
    ])
    args.extend(fp.get_browser_args())
    disable_features = fp.get_disable_features()
    if disable_features:
        args.append(f"--disable-features={','.join(disable_features)}")
    return args


def _wait_for_port(port: int, timeout: int = 10) -> bool:
    """等待 Chrome 端口可用。"""
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            _time.sleep(0.5)
    return False


def _wait_for_xvfb_socket(timeout: int = 10) -> bool:
    """等待 Xvfb 的 Unix socket 就绪。"""
    socket_path = f"/tmp/.X11-unix/X{int(XVFB_DISPLAY.lstrip(':'))}"
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if os.path.exists(socket_path):
            return True
        _time.sleep(0.5)
    return False


class BrowserManager:
    def __init__(self):
        self._browser: Optional[Chromium] = None
        self._chrome_proc: Optional[subprocess.Popen[bytes]] = None
        self._chrome_stderr: Optional[IO[str]] = None
        self._xvfb_proc: Optional[subprocess.Popen[bytes]] = None
        self._init_lock = threading.Lock()
        self._monitor_task: Optional[asyncio.Task[None]] = None
        self._is_remote = bool(REMOTE_CHROME_ADDRESS)

    def _start_xvfb(self) -> None:
        if "DISPLAY" in os.environ:
            # Xvfb 已在外部启动，等待 socket 就绪
            _wait_for_xvfb_socket(timeout=10)
            return
        try:
            result = subprocess.run(["pgrep", "-f", f"Xvfb {XVFB_DISPLAY}"], capture_output=True)
            if result.returncode == 0:
                os.environ["DISPLAY"] = XVFB_DISPLAY
                _wait_for_xvfb_socket(timeout=10)
                return
        except Exception:
            logger.debug("Xvfb 进程检测失败，准备启动新实例")
        self._xvfb_proc = subprocess.Popen(
            ["Xvfb", XVFB_DISPLAY, "-screen", "0", "1920x1080x24", "-ac"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = XVFB_DISPLAY
        _wait_for_xvfb_socket(timeout=10)

    def _stop_xvfb(self) -> None:
        if self._xvfb_proc:
            self._xvfb_proc.terminate()
            self._xvfb_proc = None

    @property
    def browser(self) -> Chromium:
        if self._browser is None or not self._browser.states.is_alive:
            self._ensure_browser()
        assert self._browser is not None
        return self._browser

    def _ensure_browser(self) -> None:
        with self._init_lock:
            if self._browser is not None and self._browser.states.is_alive:
                return
            if self._is_remote:
                co = ChromiumOptions()
                co.set_address(REMOTE_CHROME_ADDRESS)
                self._browser = Chromium(co)
            else:
                self._start_chrome()
                co = ChromiumOptions()
                co.set_local_port(DEBUG_PORT)
                self._browser = Chromium(co)
            logger.info(f"Chrome {self._browser.version}")

    def _start_chrome(self) -> None:
        if self._chrome_proc and self._chrome_proc.poll() is None:
            return
        # 清理可能残留的 Chrome 进程
        if self._chrome_proc is not None:
            try:
                self._chrome_proc.terminate()
                self._chrome_proc.wait(timeout=3)
            except Exception:
                logger.debug("终止残留 Chrome 进程失败，继续启动新实例")
            self._chrome_proc = None
        self._start_xvfb()
        chrome = CHROME_PATH or "/opt/google/chrome/google-chrome"
        env = os.environ.copy()
        env["TZ"] = "Asia/Shanghai"
        args = [chrome, *_build_chrome_args(DEFAULT_FINGERPRINT_PROFILE), "about:blank"]
        logger.debug(f"启动 Chrome 参数: {args}")
        # 将 Chrome stderr 写入日志文件，便于诊断崩溃原因
        chrome_stderr_path = "/var/log/chrome_stderr.log"
        os.makedirs(os.path.dirname(chrome_stderr_path), exist_ok=True)
        self._chrome_stderr = open(chrome_stderr_path, "w")
        self._chrome_proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=self._chrome_stderr,
            env=env,
        )
        if not _wait_for_port(DEBUG_PORT, timeout=30):
            logger.warning("Chrome 调试端口未在 30 秒内就绪")
        _time.sleep(1)

    @property
    def is_alive(self) -> bool:
        try:
            if self._browser is None:
                return False
            return bool(self._browser.states.is_alive)
        except Exception:
            return False

    async def monitor_browser(self):
        while True:
            await asyncio.sleep(BROWSER_MONITOR_INTERVAL)
            if self._browser and not self._browser.states.is_alive:
                logger.warning("浏览器异常重启")
                with self._init_lock:
                    try:
                        self._browser.quit()
                    except Exception:
                        logger.debug("关闭异常浏览器实例时出错，忽略并重建")
                    self._browser = None

    async def start_monitoring(self):
        self._monitor_task = asyncio.create_task(self.monitor_browser())

    async def stop_monitoring(self):
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def cleanup(self):
        await self.stop_monitoring()
        try:
            if self._browser:
                self._browser.quit()
        except Exception:
            logger.debug("清理浏览器实例时出错，继续释放资源")
        if self._chrome_proc:
            self._chrome_proc.terminate()
            self._chrome_proc = None
        chrome_stderr = getattr(self, "_chrome_stderr", None)
        if chrome_stderr and not chrome_stderr.closed:
            chrome_stderr.close()
        self._stop_xvfb()


browser_manager = BrowserManager()
