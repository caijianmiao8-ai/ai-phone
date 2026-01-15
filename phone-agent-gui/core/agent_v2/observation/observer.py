"""统一观察器 - 获取设备完整状态"""

import base64
import hashlib
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

from ...adb_helper import ADBHelper
from ..types import Observation, UIElement


class Observer:
    """设备观察器 - 获取屏幕、UI 树、设备状态"""

    def __init__(self, adb_helper: Optional[ADBHelper] = None, output_dir: Optional[Path] = None):
        self.adb = adb_helper or ADBHelper()
        self.output_dir = output_dir
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        self._frame_counter = 0

    def observe(self, save_screenshot: bool = True) -> Observation:
        """获取当前设备状态的完整观察"""
        timestamp = time.time()
        self._frame_counter += 1

        # 1. 获取截图
        screenshot_base64, screenshot_path, screen_size = self._capture_screen(save_screenshot)

        # 2. 计算屏幕哈希（用于变化检测）
        screen_hash = self._compute_screen_hash(screenshot_base64)

        # 3. 获取设备状态
        package, activity = self._get_current_app()
        is_keyboard_shown = self._is_keyboard_shown()

        # 4. 获取 UI 树
        ui_elements, ui_xml_path = self._dump_ui_tree()

        return Observation(
            timestamp=timestamp,
            screenshot_base64=screenshot_base64,
            screenshot_path=screenshot_path,
            package=package,
            activity=activity,
            is_keyboard_shown=is_keyboard_shown,
            screen_width=screen_size[0],
            screen_height=screen_size[1],
            ui_elements=ui_elements,
            ui_xml_path=ui_xml_path,
            screen_hash=screen_hash,
        )

    def wait_for_change(
        self,
        previous: Observation,
        timeout: float = 5.0,
        poll_interval: float = 0.3,
    ) -> Observation:
        """等待屏幕变化，返回新的观察"""
        start = time.time()

        while True:
            obs = self.observe(save_screenshot=True)

            # 检测变化
            if self._has_changed(previous, obs):
                return obs

            # 超时检查
            if time.time() - start >= timeout:
                return obs

            time.sleep(poll_interval)

    def _has_changed(self, prev: Observation, curr: Observation) -> bool:
        """检测两次观察之间是否有变化"""
        # 屏幕内容变化
        if prev.screen_hash != curr.screen_hash:
            return True
        # Activity 变化
        if prev.activity != curr.activity:
            return True
        # 键盘状态变化
        if prev.is_keyboard_shown != curr.is_keyboard_shown:
            return True
        return False

    def _capture_screen(self, save: bool = True) -> Tuple[str, Optional[str], Tuple[int, int]]:
        """截取屏幕，返回 (base64, 保存路径, (宽, 高))"""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # 截图到设备
            success, _ = self.adb.run_command(["shell", "screencap", "-p", "/sdcard/screen.png"])
            if not success:
                raise RuntimeError("截图失败")

            # 拉取到本地
            success, _ = self.adb.run_command(["pull", "/sdcard/screen.png", tmp_path])
            if not success:
                raise RuntimeError("拉取截图失败")

            # 读取图片
            with open(tmp_path, "rb") as f:
                image_data = f.read()

            # 获取尺寸
            img = Image.open(tmp_path)
            width, height = img.size

            # Base64 编码
            screenshot_base64 = base64.b64encode(image_data).decode("utf-8")

            # 保存到输出目录
            saved_path = None
            if save and self.output_dir:
                saved_path = str(self.output_dir / f"frame_{self._frame_counter}.png")
                img.save(saved_path)

            return screenshot_base64, saved_path, (width, height)

        finally:
            # 清理临时文件
            Path(tmp_path).unlink(missing_ok=True)

    def _compute_screen_hash(self, base64_data: str) -> str:
        """计算屏幕哈希，用于快速变化检测"""
        # 使用感知哈希：缩小到 8x8 灰度图，计算平均值哈希
        try:
            image_data = base64.b64decode(base64_data)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_data)
                tmp_path = tmp.name

            img = Image.open(tmp_path)
            Path(tmp_path).unlink(missing_ok=True)

            # 缩小并转灰度
            small = img.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
            pixels = list(small.getdata())

            # 计算平均值
            avg = sum(pixels) / len(pixels)

            # 生成哈希
            bits = "".join("1" if px >= avg else "0" for px in pixels)
            return hashlib.md5(bits.encode()).hexdigest()[:16]

        except Exception:
            # 降级到普通哈希
            return hashlib.md5(base64_data.encode()).hexdigest()[:16]

    def _get_current_app(self) -> Tuple[str, str]:
        """获取当前前台应用的 package 和 activity"""
        success, output = self.adb.run_command([
            "shell", "dumpsys", "activity", "activities",
        ], timeout=5)

        if not success:
            return "", ""

        # 解析 mResumedActivity 或 ResumedActivity
        # 格式: mResumedActivity: ActivityRecord{xxx u0 com.example/.MainActivity t123}
        patterns = [
            r"mResumedActivity:\s*ActivityRecord\{[^\}]*\s+([^\s/]+)/([^\s\}]+)",
            r"ResumedActivity:\s*ActivityRecord\{[^\}]*\s+([^\s/]+)/([^\s\}]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                package = match.group(1)
                activity = match.group(2)
                # activity 可能是 .MainActivity 或完整路径
                if activity.startswith("."):
                    activity = package + activity
                return package, activity

        return "", ""

    def _is_keyboard_shown(self) -> bool:
        """检测软键盘是否显示"""
        success, output = self.adb.run_command([
            "shell", "dumpsys", "input_method",
        ], timeout=5)

        if not success:
            return False

        return "mInputShown=true" in output

    def _dump_ui_tree(self) -> Tuple[List[UIElement], Optional[str]]:
        """获取 UI 树并解析为元素列表"""
        device_xml = "/sdcard/ui_dump.xml"

        # 执行 UI dump
        success, _ = self.adb.run_command([
            "shell", "uiautomator", "dump", device_xml,
        ], timeout=10)

        if not success:
            return [], None

        # 拉取到本地
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            local_xml = tmp.name

        success, _ = self.adb.run_command(["pull", device_xml, local_xml])
        if not success:
            Path(local_xml).unlink(missing_ok=True)
            return [], None

        try:
            # 解析 XML
            elements = self._parse_ui_xml(local_xml)

            # 保存到输出目录
            saved_path = None
            if self.output_dir:
                saved_path = str(self.output_dir / f"ui_{self._frame_counter}.xml")
                Path(local_xml).replace(saved_path)
            else:
                Path(local_xml).unlink(missing_ok=True)

            return elements, saved_path

        except Exception:
            Path(local_xml).unlink(missing_ok=True)
            return [], None

    def _parse_ui_xml(self, xml_path: str) -> List[UIElement]:
        """解析 UI XML 文件为元素列表"""
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except ET.ParseError:
            return []

        elements = []
        index = 0

        def traverse(node):
            nonlocal index

            # 解析 bounds 属性: [left,top][right,bottom]
            bounds_str = node.get("bounds", "")
            bounds = self._parse_bounds(bounds_str)

            if bounds:
                elem = UIElement(
                    index=index,
                    text=node.get("text", ""),
                    resource_id=node.get("resource-id", ""),
                    class_name=node.get("class", ""),
                    content_desc=node.get("content-desc", ""),
                    clickable=node.get("clickable", "false").lower() == "true",
                    scrollable=node.get("scrollable", "false").lower() == "true",
                    enabled=node.get("enabled", "true").lower() == "true",
                    bounds=bounds,
                )
                elements.append(elem)
                index += 1

            # 递归处理子节点
            for child in node:
                traverse(child)

        traverse(root)
        return elements

    def _parse_bounds(self, bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
        """解析 bounds 字符串: [left,top][right,bottom]"""
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
        if match:
            return (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
            )
        return None
