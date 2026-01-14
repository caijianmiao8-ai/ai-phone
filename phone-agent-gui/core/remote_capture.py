"""
远程屏幕捕获模块
专为云手机/远程 ADB 场景优化

特点：
1. 并行预取：2个工作线程轮流截图，提高帧率
2. 始终刷新：Timer 持续读取最新帧显示
3. 稳定可靠：每帧独立请求，失败可重试
4. PNG 格式：设备端压缩，减少传输量
"""

import io
import os
import sys
import subprocess
import threading
import time
import platform
import shutil
from typing import Optional, Tuple, List
from PIL import Image
from dataclasses import dataclass
from collections import deque


@dataclass
class CaptureStats:
    """捕获统计信息"""
    fps: float = 0.0
    total_frames: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    last_capture_time: float = 0.0


class FPSCounter:
    """帧率计算器"""

    def __init__(self, window_size: int = 30):
        self._timestamps: deque = deque(maxlen=window_size)
        self._lock = threading.Lock()

    def tick(self):
        """记录一帧"""
        with self._lock:
            self._timestamps.append(time.time())

    def get_fps(self) -> float:
        """计算当前帧率"""
        with self._lock:
            if len(self._timestamps) < 2:
                return 0.0

            # 计算时间窗口内的平均帧率
            time_span = self._timestamps[-1] - self._timestamps[0]
            if time_span <= 0:
                return 0.0

            return (len(self._timestamps) - 1) / time_span

    def reset(self):
        """重置"""
        with self._lock:
            self._timestamps.clear()


class RemoteScreenCapture:
    """
    远程 ADB 屏幕捕获器

    专为云手机场景优化：
    - 并行预取提高帧率
    - PNG 格式减少传输量
    - 稳定的错误处理和重试机制
    """

    def __init__(self, adb_path: Optional[str] = None):
        """
        初始化捕获器

        Args:
            adb_path: ADB 可执行文件路径，None 则自动查找
        """
        self._adb_path = adb_path or self._find_adb()

        # 状态
        self._running = False
        self._paused = False
        self._device_id: Optional[str] = None

        # 帧缓存
        self._latest_frame: Optional[bytes] = None
        self._latest_image: Optional[Image.Image] = None
        self._frame_lock = threading.Lock()
        self._frame_id = 0
        self._last_read_id = 0

        # 工作线程
        self._workers: List[threading.Thread] = []
        self._num_workers = 2  # 双线程并行预取
        self._semaphore = threading.Semaphore(2)  # 限制并发

        # 配置
        self._timeout = 5.0  # 远程场景需要更长超时
        self._error_backoff = 0.5  # 错误后等待时间
        self._max_consecutive_errors = 5

        # 统计
        self._fps_counter = FPSCounter()
        self._stats = CaptureStats()
        self._consecutive_errors = 0

    def _find_adb(self) -> Optional[str]:
        """查找 ADB 路径"""
        # 检查内置路径
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        exe_name = "adb.exe" if platform.system() == "Windows" else "adb"
        bundled = os.path.join(base_dir, "adb", exe_name)
        if os.path.exists(bundled):
            return bundled

        # 检查系统 PATH
        return shutil.which("adb")

    def _verify_device(self) -> Tuple[bool, str]:
        """验证设备连接"""
        if not self._adb_path:
            return False, "ADB 不可用"

        if not self._device_id:
            return False, "未指定设备"

        try:
            cmd = [self._adb_path, "-s", self._device_id, "get-state"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0 and "device" in result.stdout:
                return True, "设备已连接"
            return False, f"设备状态异常: {result.stdout.strip()}"
        except subprocess.TimeoutExpired:
            return False, "设备连接超时"
        except Exception as e:
            return False, f"设备验证失败: {e}"

    def _capture_one_frame(self) -> Optional[bytes]:
        """
        捕获一帧截图

        使用 PNG 格式：设备端压缩，减少传输量
        对于远程 ADB，这比原始格式更快

        Returns:
            PNG 图像字节，失败返回 None
        """
        if not self._adb_path or not self._device_id:
            return None

        cmd = [
            self._adb_path,
            "-s", self._device_id,
            "exec-out", "screencap", "-p"
        ]

        try:
            # Windows 下隐藏命令窗口
            kwargs = {}
            if platform.system() == "Windows":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self._timeout,
                **kwargs
            )

            if result.returncode == 0 and result.stdout:
                # 验证是有效的 PNG (头部: 89 50 4E 47 0D 0A 1A 0A)
                png_header = b'\x89PNG\r\n\x1a\n'
                if result.stdout[:8] == png_header:
                    return result.stdout

                # 某些环境可能破坏二进制数据，尝试检测并跳过
                # 如果不是有效 PNG 但有数据，记录错误
                if len(result.stdout) > 100:
                    self._stats.last_error = "截图数据格式异常"

            return None

        except subprocess.TimeoutExpired:
            self._stats.last_error = "截图超时"
            return None
        except Exception as e:
            self._stats.last_error = str(e)
            return None

    def _process_frame(self, png_data: bytes) -> Tuple[Optional[bytes], Optional[Image.Image]]:
        """
        处理帧数据：解析 PNG，转换为 JPEG（减少内存占用）

        Args:
            png_data: PNG 图像字节

        Returns:
            (JPEG 字节, PIL Image)
        """
        try:
            img = Image.open(io.BytesIO(png_data))

            # 转换为 RGB（去掉 alpha 通道）
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # 转为 JPEG 用于缓存（更小的内存占用）
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=75)
            jpeg_data = buffer.getvalue()

            return jpeg_data, img

        except Exception as e:
            self._stats.last_error = f"图像处理失败: {e}"
            return None, None

    def _worker_loop(self, worker_id: int):
        """
        工作线程循环

        Args:
            worker_id: 线程编号（用于调试）
        """
        print(f"[DEBUG] Worker {worker_id} started")
        frame_count = 0

        while self._running:
            # 暂停状态：空转
            if self._paused:
                time.sleep(0.1)
                continue

            # 获取信号量，限制并发
            self._semaphore.acquire()

            try:
                if not self._running:
                    break

                # 捕获一帧
                start_time = time.time()
                png_data = self._capture_one_frame()

                if png_data:
                    # 处理帧
                    jpeg_data, img = self._process_frame(png_data)

                    if img:
                        # 更新最新帧
                        with self._frame_lock:
                            self._latest_frame = jpeg_data
                            self._latest_image = img
                            self._frame_id += 1

                        # 更新统计
                        self._fps_counter.tick()
                        self._stats.total_frames += 1
                        self._stats.last_capture_time = time.time() - start_time
                        self._consecutive_errors = 0

                        frame_count += 1
                        # 每 10 帧打印一次
                        if frame_count % 10 == 0:
                            print(f"[DEBUG] Worker {worker_id} captured {frame_count} frames, frame_id={self._frame_id}")
                else:
                    # 失败处理
                    self._consecutive_errors += 1
                    self._stats.error_count += 1

                    if self._consecutive_errors <= 3:  # 前几次失败打印日志
                        print(f"[DEBUG] Worker {worker_id} capture failed, consecutive_errors={self._consecutive_errors}")

                    if self._consecutive_errors >= self._max_consecutive_errors:
                        self._stats.last_error = "连续截图失败，请检查设备连接"
                        print(f"[DEBUG] Worker {worker_id} reached max consecutive errors")
                        time.sleep(self._error_backoff)

            finally:
                self._semaphore.release()

        print(f"[DEBUG] Worker {worker_id} stopped, total frames={frame_count}")

    def start(self, device_id: str) -> Tuple[bool, str, Optional[Image.Image]]:
        """
        启动捕获

        Args:
            device_id: 设备 ID

        Returns:
            (成功, 消息, 首帧图片)
        """
        print(f"[DEBUG] RemoteCapture.start called for device {device_id}")

        if self._running:
            print(f"[DEBUG] RemoteCapture already running, stopping first")
            self.stop()

        self._device_id = device_id

        # 验证设备
        ok, msg = self._verify_device()
        print(f"[DEBUG] RemoteCapture device verification: ok={ok}, msg={msg}")
        if not ok:
            return False, msg, None

        # 获取首帧（同步，确保有画面）
        print(f"[DEBUG] RemoteCapture capturing first frame...")
        first_frame = None
        png_data = self._capture_one_frame()
        if png_data:
            print(f"[DEBUG] RemoteCapture got PNG data, size={len(png_data)} bytes")
            jpeg_data, img = self._process_frame(png_data)
            if img:
                with self._frame_lock:
                    self._latest_frame = jpeg_data
                    self._latest_image = img
                    self._frame_id += 1
                first_frame = img
                print(f"[DEBUG] RemoteCapture first frame processed, size={img.size}")
        else:
            print(f"[DEBUG] RemoteCapture failed to get first frame PNG data")

        if not first_frame:
            return False, "无法获取首帧截图", None

        # 重置状态
        self._running = True
        self._paused = False
        self._consecutive_errors = 0
        self._fps_counter.reset()
        self._stats = CaptureStats()

        # 启动工作线程
        self._workers = []
        for i in range(self._num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                daemon=True,
                name=f"ScreenCapture-Worker-{i}"
            )
            worker.start()
            self._workers.append(worker)

        print(f"[DEBUG] RemoteCapture started with {self._num_workers} workers")
        return True, "捕获已启动", first_frame

    def stop(self) -> Tuple[bool, str]:
        """停止捕获"""
        if not self._running:
            return False, "未在运行"

        self._running = False

        # 等待线程结束
        for worker in self._workers:
            if worker.is_alive():
                worker.join(timeout=2)

        self._workers = []

        return True, "捕获已停止"

    def pause(self):
        """暂停捕获（线程不停，只是不截图）"""
        self._paused = True

    def resume(self):
        """恢复捕获"""
        self._paused = False

    def is_running(self) -> bool:
        """是否运行中"""
        return self._running

    def is_paused(self) -> bool:
        """是否暂停"""
        return self._paused

    def get_frame(self) -> Optional[Image.Image]:
        """
        获取最新帧（供 Timer 调用）

        Returns:
            PIL Image 或 None
        """
        with self._frame_lock:
            return self._latest_image

    def get_frame_if_new(self) -> Optional[Image.Image]:
        """
        只在有新帧时返回（避免重复更新）

        Returns:
            PIL Image 或 None
        """
        with self._frame_lock:
            if self._frame_id > self._last_read_id:
                self._last_read_id = self._frame_id
                return self._latest_image
        return None

    def get_stats(self) -> CaptureStats:
        """获取统计信息"""
        self._stats.fps = self._fps_counter.get_fps()
        return self._stats

    def get_status_text(self) -> str:
        """获取状态文本（用于 UI 显示）"""
        if not self._running:
            return "已停止"

        if self._paused:
            return "已暂停"

        fps = self._fps_counter.get_fps()

        if self._stats.last_error and self._consecutive_errors > 0:
            return f"运行中 ({fps:.1f} FPS) ⚠️ {self._stats.last_error}"

        return f"运行中 ({fps:.1f} FPS)"


# 全局实例
_remote_capture: Optional[RemoteScreenCapture] = None


def get_remote_capture() -> RemoteScreenCapture:
    """获取全局远程捕获实例"""
    global _remote_capture
    if _remote_capture is None:
        _remote_capture = RemoteScreenCapture()
    return _remote_capture
