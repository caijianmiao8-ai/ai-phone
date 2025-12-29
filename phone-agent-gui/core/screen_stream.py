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
import struct
from typing import Optional, Tuple
from PIL import Image


class ScreenStreamer:
    """
    屏幕流管理器

    支持两种模式：
    1. scrcpy 模式：使用 scrcpy 视频流，帧率高、延迟低
    2. 截图模式：使用 adb screencap，兼容性好
    """

    def __init__(self, scrcpy_path: str = None, adb_path: str = None):
        self.scrcpy_path = scrcpy_path
        self.adb_path = adb_path
        self._scrcpy_process: Optional[subprocess.Popen] = None
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._device_id: Optional[str] = None
        self._error_message: Optional[str] = None
        self._mode: str = "screenshot"  # "scrcpy" or "screenshot"

        # 帧率控制
        self._target_fps = 15  # 目标帧率
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

    def _find_ffmpeg(self) -> Optional[str]:
        """查找 ffmpeg 路径"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 检查内置路径
        if platform.system() == "Windows":
            bundled = os.path.join(base_dir, "ffmpeg", "ffmpeg.exe")
        else:
            bundled = os.path.join(base_dir, "ffmpeg", "ffmpeg")

        if os.path.exists(bundled):
            return bundled

        # 检查 scrcpy 目录中的 ffmpeg (scrcpy 自带)
        scrcpy_ffmpeg = os.path.join(base_dir, "scrcpy", "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
        if os.path.exists(scrcpy_ffmpeg):
            return scrcpy_ffmpeg

        import shutil
        return shutil.which("ffmpeg")

    def _capture_loop_scrcpy(self):
        """
        使用 scrcpy + ffmpeg 获取实时视频流
        帧率高，延迟低
        """
        scrcpy = self._find_scrcpy()
        ffmpeg = self._find_ffmpeg()

        if not scrcpy:
            self._error_message = "scrcpy 不可用，切换到截图模式"
            self._mode = "screenshot"
            self._capture_loop_screenshot()
            return

        if not ffmpeg:
            self._error_message = "ffmpeg 不可用，切换到截图模式"
            self._mode = "screenshot"
            self._capture_loop_screenshot()
            return

        try:
            # 启动 scrcpy，输出 H.264 到管道
            scrcpy_cmd = [scrcpy, "--no-window", "--no-audio", "--max-fps=30"]
            if self._device_id:
                scrcpy_cmd.extend(["-s", self._device_id])
            # 录制到 stdout (scrcpy 2.0+)
            scrcpy_cmd.extend(["--record=-", "--record-format=h264"])

            # 启动 ffmpeg 解码 H.264 并输出 MJPEG
            ffmpeg_cmd = [
                ffmpeg,
                "-f", "h264",
                "-i", "pipe:0",
                "-f", "image2pipe",
                "-c:v", "mjpeg",
                "-q:v", "5",
                "-r", str(self._target_fps),
                "pipe:1"
            ]

            # 创建进程管道
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.DEVNULL,
            }
            if platform.system() == "Windows":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self._scrcpy_process = subprocess.Popen(scrcpy_cmd, **popen_kwargs)

            ffmpeg_kwargs = {
                "stdin": self._scrcpy_process.stdout,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.DEVNULL,
            }
            if platform.system() == "Windows":
                ffmpeg_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self._ffmpeg_process = subprocess.Popen(ffmpeg_cmd, **ffmpeg_kwargs)

            # 读取 JPEG 帧
            jpeg_buffer = b""
            while self._running:
                chunk = self._ffmpeg_process.stdout.read(4096)
                if not chunk:
                    break

                jpeg_buffer += chunk

                # 查找 JPEG 帧边界 (FFD8 开始, FFD9 结束)
                while True:
                    start = jpeg_buffer.find(b"\xff\xd8")
                    if start == -1:
                        jpeg_buffer = b""
                        break

                    end = jpeg_buffer.find(b"\xff\xd9", start)
                    if end == -1:
                        # 保留从 start 开始的数据
                        jpeg_buffer = jpeg_buffer[start:]
                        break

                    # 提取完整的 JPEG 帧
                    frame = jpeg_buffer[start:end + 2]
                    jpeg_buffer = jpeg_buffer[end + 2:]

                    with self._frame_lock:
                        self._latest_frame = frame

        except Exception as e:
            self._error_message = f"scrcpy 流错误: {e}，切换到截图模式"
            self._mode = "screenshot"
            self._stop_processes()
            if self._running:
                self._capture_loop_screenshot()

    def _stop_processes(self):
        """停止 scrcpy 和 ffmpeg 进程"""
        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=2)
            except Exception:
                try:
                    self._ffmpeg_process.kill()
                except Exception:
                    pass
            self._ffmpeg_process = None

        if self._scrcpy_process:
            try:
                self._scrcpy_process.terminate()
                self._scrcpy_process.wait(timeout=2)
            except Exception:
                try:
                    self._scrcpy_process.kill()
                except Exception:
                    pass
            self._scrcpy_process = None

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

    def start(self, device_id: str = None, fps: int = 15, use_scrcpy: bool = True) -> Tuple[bool, str]:
        """
        启动屏幕流

        Args:
            device_id: 设备ID
            fps: 目标帧率 (1-30)
            use_scrcpy: 是否优先使用 scrcpy 模式

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

        # 选择捕获方法
        if use_scrcpy and self._find_scrcpy() and self._find_ffmpeg():
            self._mode = "scrcpy"
            capture_func = self._capture_loop_scrcpy
            mode_desc = "scrcpy 视频流"
        else:
            self._mode = "screenshot"
            capture_func = self._capture_loop_screenshot
            mode_desc = "截图模式"

        # 启动捕获线程
        self._capture_thread = threading.Thread(
            target=capture_func,
            daemon=True
        )
        self._capture_thread.start()

        return True, f"实时流已启动 ({mode_desc}, {self._target_fps} FPS)"

    def stop(self) -> Tuple[bool, str]:
        """停止屏幕流"""
        if not self._running:
            return False, "流未运行"

        self._running = False

        # 停止进程
        self._stop_processes()

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
            mode_name = "scrcpy" if self._mode == "scrcpy" else "截图"
            if self._error_message:
                return f"运行中 [{mode_name}] (有错误: {self._error_message})"
            return f"运行中 [{mode_name}] ({self._target_fps} FPS)"
        return "已停止"

    def get_mode(self) -> str:
        """获取当前模式"""
        return self._mode


# 全局实例
_screen_streamer: Optional[ScreenStreamer] = None


def get_screen_streamer() -> ScreenStreamer:
    """获取全局屏幕流实例"""
    global _screen_streamer
    if _screen_streamer is None:
        _screen_streamer = ScreenStreamer()
    return _screen_streamer
