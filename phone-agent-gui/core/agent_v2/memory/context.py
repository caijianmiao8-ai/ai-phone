"""上下文管理器 - 管理对话历史并防止过长"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StepMemory:
    """单步记忆"""
    step_id: int
    action_summary: str  # 执行的行动摘要
    result_summary: str  # 结果摘要
    key_observation: str  # 关键观察（如页面标题、新出现的元素）
    success: bool


@dataclass
class TaskContext:
    """任务上下文"""
    task: str
    current_step: int = 0
    steps: List[StepMemory] = field(default_factory=list)
    key_facts: Dict[str, str] = field(default_factory=dict)  # 关键事实
    last_error: Optional[str] = None


class ContextManager:
    """
    上下文管理器

    核心职责：
    1. 维护任务执行的历史记录
    2. 定期压缩历史，防止上下文过长
    3. 提供结构化的上下文信息给 LLM
    """

    def __init__(self, max_detailed_steps: int = 5, max_summary_steps: int = 20):
        """
        Args:
            max_detailed_steps: 保留详细信息的最近步骤数
            max_summary_steps: 保留摘要的最大步骤数
        """
        self.max_detailed_steps = max_detailed_steps
        self.max_summary_steps = max_summary_steps
        self.context: Optional[TaskContext] = None

    def start_task(self, task: str) -> None:
        """开始新任务"""
        self.context = TaskContext(task=task)

    def add_step(
        self,
        action_summary: str,
        result_summary: str,
        key_observation: str,
        success: bool,
    ) -> None:
        """记录一步执行"""
        if not self.context:
            return

        self.context.current_step += 1

        step = StepMemory(
            step_id=self.context.current_step,
            action_summary=action_summary,
            result_summary=result_summary,
            key_observation=key_observation,
            success=success,
        )
        self.context.steps.append(step)

        # 压缩历史
        self._compress_if_needed()

    def set_fact(self, key: str, value: str) -> None:
        """记录关键事实（如已登录、已选择某选项等）"""
        if self.context:
            self.context.key_facts[key] = value

    def set_last_error(self, error: str) -> None:
        """记录最后的错误"""
        if self.context:
            self.context.last_error = error

    def clear_last_error(self) -> None:
        """清除最后的错误"""
        if self.context:
            self.context.last_error = None

    def get_context_for_llm(self) -> str:
        """生成供 LLM 使用的上下文摘要"""
        if not self.context:
            return ""

        parts = []

        # 1. 任务目标
        parts.append(f"【任务目标】{self.context.task}")

        # 2. 执行进度
        parts.append(f"【当前进度】第 {self.context.current_step} 步")

        # 3. 关键事实
        if self.context.key_facts:
            facts = [f"  - {k}: {v}" for k, v in self.context.key_facts.items()]
            parts.append("【已确认的事实】\n" + "\n".join(facts))

        # 4. 最近失败信息
        if self.context.last_error:
            parts.append(f"【上一步问题】{self.context.last_error}")

        # 5. 执行历史摘要
        if self.context.steps:
            parts.append("【执行历史】")
            parts.append(self._build_history_summary())

        return "\n\n".join(parts)

    def _build_history_summary(self) -> str:
        """构建历史摘要"""
        if not self.context or not self.context.steps:
            return ""

        lines = []
        steps = self.context.steps

        # 分为两部分：早期步骤（简略）和最近步骤（详细）
        if len(steps) > self.max_detailed_steps:
            # 早期步骤简略显示
            early_steps = steps[:-self.max_detailed_steps]
            lines.append(f"  [步骤 1-{len(early_steps)}] 早期操作摘要:")

            # 按成功/失败分组统计
            success_count = sum(1 for s in early_steps if s.success)
            fail_count = len(early_steps) - success_count

            # 提取关键动作
            key_actions = []
            for s in early_steps:
                if s.key_observation and s.key_observation not in key_actions:
                    key_actions.append(s.key_observation)

            lines.append(f"    成功 {success_count} 步, 失败 {fail_count} 步")
            if key_actions:
                lines.append(f"    经过: {' -> '.join(key_actions[:5])}")

            # 最近步骤详细显示
            recent_steps = steps[-self.max_detailed_steps:]
            lines.append(f"\n  [最近 {len(recent_steps)} 步] 详细记录:")
        else:
            recent_steps = steps
            lines.append("  详细记录:")

        for step in recent_steps:
            status = "✓" if step.success else "✗"
            lines.append(f"  {status} 步骤{step.step_id}: {step.action_summary}")
            lines.append(f"      结果: {step.result_summary}")

        return "\n".join(lines)

    def _compress_if_needed(self) -> None:
        """压缩历史记录"""
        if not self.context:
            return

        # 超过最大步骤数时，删除最早的步骤
        if len(self.context.steps) > self.max_summary_steps:
            # 保留最近的步骤
            self.context.steps = self.context.steps[-self.max_summary_steps:]

    def get_step_count(self) -> int:
        """获取当前步骤数"""
        return self.context.current_step if self.context else 0

    def get_recent_failures(self, count: int = 3) -> List[str]:
        """获取最近的失败信息"""
        if not self.context:
            return []

        failures = []
        for step in reversed(self.context.steps):
            if not step.success:
                failures.append(f"步骤{step.step_id}: {step.result_summary}")
                if len(failures) >= count:
                    break

        return failures
