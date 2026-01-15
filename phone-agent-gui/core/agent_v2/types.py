"""Agent V2 核心类型定义"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ActionType(str, Enum):
    """支持的行动类型"""
    TAP = "tap"
    LONG_PRESS = "long_press"
    SWIPE = "swipe"
    TYPE = "type"
    BACK = "back"
    HOME = "home"
    WAIT = "wait"
    FINISH = "finish"


@dataclass
class UIElement:
    """UI 元素，从 UI 树解析"""
    index: int
    text: str
    resource_id: str
    class_name: str
    content_desc: str
    clickable: bool
    scrollable: bool
    enabled: bool
    bounds: Tuple[int, int, int, int]  # left, top, right, bottom

    @property
    def center(self) -> Tuple[int, int]:
        """元素中心坐标"""
        l, t, r, b = self.bounds
        return (l + r) // 2, (t + b) // 2

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    def to_description(self) -> str:
        """生成元素描述，用于 LLM 理解"""
        parts = [f"[{self.index}]"]
        if self.text:
            parts.append(f'"{self.text}"')
        if self.content_desc and self.content_desc != self.text:
            parts.append(f'(desc:{self.content_desc})')
        if self.resource_id:
            # 只保留 id 的最后部分
            short_id = self.resource_id.split("/")[-1] if "/" in self.resource_id else self.resource_id
            parts.append(f'id:{short_id}')

        attrs = []
        if self.clickable:
            attrs.append("clickable")
        if self.scrollable:
            attrs.append("scrollable")
        if attrs:
            parts.append(f"[{','.join(attrs)}]")

        return " ".join(parts)


@dataclass
class Observation:
    """观察结果 - 设备当前状态的完整快照"""
    # 基础信息
    timestamp: float
    screenshot_base64: str
    screenshot_path: Optional[str] = None

    # 设备状态
    package: str = ""
    activity: str = ""
    is_keyboard_shown: bool = False
    screen_width: int = 1080
    screen_height: int = 1920

    # UI 树
    ui_elements: List[UIElement] = field(default_factory=list)
    ui_xml_path: Optional[str] = None

    # 用于变化检测的哈希
    screen_hash: str = ""

    def get_ui_description(self, max_elements: int = 50) -> str:
        """生成 UI 描述文本，用于 LLM 理解当前界面"""
        if not self.ui_elements:
            return "(无法获取 UI 元素)"

        # 过滤有意义的元素
        meaningful = [
            e for e in self.ui_elements
            if e.text or e.content_desc or e.clickable or e.scrollable
        ]

        if not meaningful:
            return "(界面无可交互元素)"

        # 限制数量
        elements = meaningful[:max_elements]

        lines = []
        for elem in elements:
            lines.append(elem.to_description())

        if len(meaningful) > max_elements:
            lines.append(f"... 还有 {len(meaningful) - max_elements} 个元素")

        return "\n".join(lines)

    def find_element_by_index(self, index: int) -> Optional[UIElement]:
        """根据索引查找元素"""
        for elem in self.ui_elements:
            if elem.index == index:
                return elem
        return None

    def find_elements_by_text(self, text: str, exact: bool = False) -> List[UIElement]:
        """根据文本查找元素"""
        results = []
        for elem in self.ui_elements:
            if exact:
                if elem.text == text or elem.content_desc == text:
                    results.append(elem)
            else:
                if text.lower() in elem.text.lower() or text.lower() in elem.content_desc.lower():
                    results.append(elem)
        return results


@dataclass
class Action:
    """LLM 决定的行动"""
    action_type: ActionType

    # tap/long_press 参数 - 支持元素索引或坐标
    element_index: Optional[int] = None  # 优先使用元素索引
    x: Optional[int] = None
    y: Optional[int] = None

    # swipe 参数
    direction: Optional[str] = None  # up, down, left, right
    distance: float = 0.3  # 滑动距离比例

    # type 参数
    text: Optional[str] = None

    # wait 参数
    duration_ms: int = 500

    # finish 参数
    message: Optional[str] = None

    # LLM 的思考过程
    thinking: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action_type.value,
            "element_index": self.element_index,
            "x": self.x,
            "y": self.y,
            "direction": self.direction,
            "distance": self.distance,
            "text": self.text,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "thinking": self.thinking,
        }


@dataclass
class VerifyResult:
    """行动验证结果"""
    changed: bool  # 屏幕是否发生变化
    change_type: str  # 变化类型: none, screen_changed, activity_changed, keyboard_shown, keyboard_hidden
    details: str  # 变化详情描述

    # 用于反馈给 LLM
    def to_feedback(self) -> str:
        if self.changed:
            return f"[行动生效] {self.change_type}: {self.details}"
        else:
            return f"[行动未生效] 屏幕无变化，可能需要等待或尝试其他操作"


@dataclass
class StepResult:
    """单步执行结果"""
    step_id: int
    action: Action
    observation_before: Observation
    observation_after: Observation
    verify_result: VerifyResult
    success: bool
    error: Optional[str] = None


@dataclass
class TaskResult:
    """任务执行结果"""
    task: str
    success: bool
    message: str
    steps: List[StepResult] = field(default_factory=list)
    total_steps: int = 0
    elapsed_seconds: float = 0.0
