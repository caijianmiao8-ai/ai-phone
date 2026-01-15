"""行动执行器 - 将 Action 转换为设备操作"""

import time
from typing import Optional, Tuple

from ...adb_helper import ADBHelper
from ..types import Action, ActionType, Observation, UIElement


class ActionExecutor:
    """行动执行器"""

    def __init__(self, adb_helper: Optional[ADBHelper] = None):
        self.adb = adb_helper or ADBHelper()
        self._screen_width = 1080
        self._screen_height = 1920

    def execute(self, action: Action, observation: Observation) -> bool:
        """
        执行行动

        Args:
            action: 要执行的行动
            observation: 当前观察（用于解析元素索引）

        Returns:
            是否执行成功
        """
        self._screen_width = observation.screen_width
        self._screen_height = observation.screen_height

        action_type = action.action_type

        if action_type == ActionType.TAP:
            return self._execute_tap(action, observation)

        elif action_type == ActionType.LONG_PRESS:
            return self._execute_long_press(action, observation)

        elif action_type == ActionType.SWIPE:
            return self._execute_swipe(action)

        elif action_type == ActionType.TYPE:
            return self._execute_type(action)

        elif action_type == ActionType.BACK:
            return self._execute_back()

        elif action_type == ActionType.HOME:
            return self._execute_home()

        elif action_type == ActionType.WAIT:
            return self._execute_wait(action)

        elif action_type == ActionType.FINISH:
            return True

        return False

    def _execute_tap(self, action: Action, observation: Observation) -> bool:
        """执行点击操作"""
        x, y = self._resolve_coordinates(action, observation)
        if x is None or y is None:
            return False

        success, _ = self.adb.run_command([
            "shell", "input", "tap", str(x), str(y)
        ])
        return success

    def _execute_long_press(self, action: Action, observation: Observation) -> bool:
        """执行长按操作"""
        x, y = self._resolve_coordinates(action, observation)
        if x is None or y is None:
            return False

        # 长按通过 swipe 实现：同一位置滑动 800ms
        duration = action.duration_ms if action.duration_ms > 0 else 800
        success, _ = self.adb.run_command([
            "shell", "input", "swipe",
            str(x), str(y), str(x), str(y), str(duration)
        ])
        return success

    def _execute_swipe(self, action: Action) -> bool:
        """执行滑动操作"""
        direction = action.direction or "up"
        distance = action.distance if action.distance > 0 else 0.3

        # 计算起点（屏幕中心）
        start_x = self._screen_width // 2
        start_y = self._screen_height // 2

        # 计算终点
        if direction == "up":
            offset = int(self._screen_height * distance)
            end_x, end_y = start_x, start_y - offset
        elif direction == "down":
            offset = int(self._screen_height * distance)
            end_x, end_y = start_x, start_y + offset
        elif direction == "left":
            offset = int(self._screen_width * distance)
            end_x, end_y = start_x - offset, start_y
        elif direction == "right":
            offset = int(self._screen_width * distance)
            end_x, end_y = start_x + offset, start_y
        else:
            return False

        # 确保终点在屏幕内
        end_x = max(0, min(end_x, self._screen_width))
        end_y = max(0, min(end_y, self._screen_height))

        duration = action.duration_ms if action.duration_ms > 0 else 300

        success, _ = self.adb.run_command([
            "shell", "input", "swipe",
            str(start_x), str(start_y),
            str(end_x), str(end_y),
            str(duration)
        ])
        return success

    def _execute_type(self, action: Action) -> bool:
        """执行输入文本操作"""
        text = action.text or ""
        if not text:
            return True

        # 对特殊字符转义
        # ADB input text 需要转义空格和特殊字符
        escaped = text.replace(" ", "%s")
        escaped = escaped.replace("&", "\\&")
        escaped = escaped.replace("<", "\\<")
        escaped = escaped.replace(">", "\\>")
        escaped = escaped.replace("(", "\\(")
        escaped = escaped.replace(")", "\\)")
        escaped = escaped.replace("|", "\\|")
        escaped = escaped.replace(";", "\\;")
        escaped = escaped.replace("*", "\\*")
        escaped = escaped.replace("\\", "\\\\")
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace('"', '\\"')

        success, _ = self.adb.run_command([
            "shell", "input", "text", escaped
        ])
        return success

    def _execute_back(self) -> bool:
        """执行返回操作"""
        success, _ = self.adb.run_command([
            "shell", "input", "keyevent", "4"  # KEYCODE_BACK
        ])
        return success

    def _execute_home(self) -> bool:
        """执行回到主屏幕操作"""
        success, _ = self.adb.run_command([
            "shell", "input", "keyevent", "3"  # KEYCODE_HOME
        ])
        return success

    def _execute_wait(self, action: Action) -> bool:
        """执行等待操作"""
        duration_s = action.duration_ms / 1000.0
        time.sleep(duration_s)
        return True

    def _resolve_coordinates(
        self, action: Action, observation: Observation
    ) -> Tuple[Optional[int], Optional[int]]:
        """解析行动的目标坐标"""
        # 优先使用元素索引
        if action.element_index is not None:
            element = observation.find_element_by_index(action.element_index)
            if element:
                return element.center
            # 元素索引无效，降级到坐标
            if action.x is not None and action.y is not None:
                return action.x, action.y
            return None, None

        # 使用直接坐标
        if action.x is not None and action.y is not None:
            return action.x, action.y

        return None, None

    def launch_app(self, package: str) -> bool:
        """启动应用"""
        # 先尝试通过 monkey 启动
        success, _ = self.adb.run_command([
            "shell", "monkey",
            "-p", package,
            "-c", "android.intent.category.LAUNCHER",
            "1"
        ])
        return success

    def open_settings(self) -> bool:
        """打开系统设置"""
        success, _ = self.adb.run_command([
            "shell", "am", "start",
            "-a", "android.settings.SETTINGS"
        ])
        return success
