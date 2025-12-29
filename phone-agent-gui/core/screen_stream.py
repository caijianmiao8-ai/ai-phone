"""
屏幕流模块
使用 scrcpy 提供内嵌的实时画面流
"""
import os
import io
import subprocess
import threading
import time
import platform
from typing import Optional, Tuple
from PIL import Image


class ScreenStreamer:
    """
    屏幕流管理器

    使用 scrcpy 的视频输出功能，将实时画面嵌入到应用中
    """

    def __init__(self, scrcpy_path: str = None, adb_path: str = None):
        self.scrcpy_path = scrcpy_path
        self.adb_path = adb_path
        self._process: Optional[subprocess.Popen] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._device_id: Optional[str] = None
        self._error_message: Optional[str] = None

        # 帧率控制
        self._target_fps = 10  # 目标帧率
        self._frame_interval = 1.0 / self._target_fps

    def _find_scrcpy(self) -> Optional[str]:
        """查找 scrcpy 路径"""
        if self.scrcpy_path and os.path.exists(self.scrcpy_path):
            return self.scrcpy_path

        # 检查内置路径
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled = os.path.join(base_dir, "scrcpy", "scrcpy.exe" if platform.system() == "Windows" else "scrcpy")
        if os.path.exists(bundled):
            return bundled

        # 检查系统 PATH
        import shutil
        return shutil.which("scrcpy")

    def _find_adb(self) -> Optional[str]:
        """查找 adb 路径"""
        if self.adb_path and os.path.exists(self.adb_path):
            return self.adb_path

        # 检查内置路径
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled = os.path.join(base_dir, "adb", "adb.exe" if platform.system() == "Windows" else "adb")
        if os.path.exists(bundled):
            return bundled

        import shutil
        return shutil.which("adb")

    def _capture_loop_screenshot(self):
        """
        使用快速截图的方式获取画面
        这是最可靠的方式，兼容所有设备
        """
        adb = self._find_adb()
        if not adb:
            self._error_message = "ADB 不可用"
            self._running = False
            return

        while self._running:
            try:
                start_time = time.time()

                # 构建命令
                cmd = [adb]
                if self._device_id:
                    cmd.extend(["-s", self._device_id])
                cmd.extend(["exec-out", "screencap", "-p"])

                # 执行截图
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=3
                )

                if result.returncode == 0 and result.stdout:
                    with self._frame_lock:
                        self._latest_frame = result.stdout

                # 控制帧率
                elapsed = time.time() - start_time
                sleep_time = self._frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            except subprocess.TimeoutExpired:
                time.sleep(0.1)
            except Exception as e:
                self._error_message = str(e)
                time.sleep(0.5)

    def start(self, device_id: str = None, fps: int = 10) -> Tuple[bool, str]:
        """
        启动屏幕流

        Args:
            device_id: 设备ID
            fps: 目标帧率 (1-30)

        Returns:
            (success, message)
        """
        if self._running:
            return False, "流已在运行"

        self._device_id = device_id
        self._target_fps = max(1, min(30, fps))
        self._frame_interval = 1.0 / self._target_fps
        self._error_message = None
        self._running = True

        # 启动捕获线程
        self._capture_thread = threading.Thread(
            target=self._capture_loop_screenshot,
            daemon=True
        )
        self._capture_thread.start()

        return True, f"实时流已启动 (目标 {self._target_fps} FPS)"

    def stop(self) -> Tuple[bool, str]:
        """停止屏幕流"""
        if not self._running:
            return False, "流未运行"

        self._running = False

        # 等待线程结束
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2)

        self._capture_thread = None
        self._latest_frame = None

        return True, "实时流已停止"

    def get_frame(self) -> Optional[Image.Image]:
        """
        获取最新帧

        Returns:
            PIL Image 或 None
        """
        with self._frame_lock:
            if self._latest_frame:
                try:
                    return Image.open(io.BytesIO(self._latest_frame))
                except Exception:
                    return None
        return None

    def get_frame_bytes(self) -> Optional[bytes]:
        """获取最新帧的原始字节"""
        with self._frame_lock:
            return self._latest_frame

    def is_running(self) -> bool:
        """检查流是否正在运行"""
        return self._running

    def get_error(self) -> Optional[str]:
        """获取错误信息"""
        return self._error_message

    def get_status(self) -> str:
        """获取状态信息"""
        if self._running:
            if self._error_message:
                return f"运行中 (有错误: {self._error_message})"
            return f"运行中 ({self._target_fps} FPS)"
        return "已停止"


# 全局实例
_screen_streamer: Optional[ScreenStreamer] = None


def get_screen_streamer() -> ScreenStreamer:
    """获取全局屏幕流实例"""
    global _screen_streamer
    if _screen_streamer is None:
        _screen_streamer = ScreenStreamer()
    return _screen_streamer
