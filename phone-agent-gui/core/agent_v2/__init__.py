"""
Agent V2 - 闭环决策 Phone Agent

设计目标：
解决 AI Phone 控制模块在执行复杂多轮任务时精度下降的问题

核心改进：
1. 增强观察 - 不只依赖截图，还解析 UI 树获取精确元素信息
2. 验证反馈 - 每步执行后检测变化，将结果反馈给 LLM
3. LLM 自主恢复 - 失败时让 LLM 自己调整，而非固定规则
4. 上下文管理 - 定期压缩历史，防止长任务中信息丢失

架构：
- observation/ - 观察模块：获取屏幕、UI 树、设备状态
- action/      - 执行模块：统一行动执行
- verification/- 验证模块：检测行动效果
- memory/      - 记忆模块：上下文压缩与管理
- prompt/      - 提示词模块：构建增强提示
- agent.py     - 核心 Agent：LLM 驱动的闭环决策
"""

from .agent import AgentV2, AgentConfig
from .types import (
    Action,
    ActionType,
    Observation,
    UIElement,
    VerifyResult,
    StepResult,
    TaskResult,
)

__all__ = [
    "AgentV2",
    "AgentConfig",
    "Action",
    "ActionType",
    "Observation",
    "UIElement",
    "VerifyResult",
    "StepResult",
    "TaskResult",
]
