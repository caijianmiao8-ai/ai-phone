"""Main PhoneAgent class for orchestrating phone automation."""

import hashlib
import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, List

from phone_agent.actions import ActionHandler
from phone_agent.actions.handler import do, finish, parse_action
from phone_agent.config import get_messages, get_system_prompt
from phone_agent.device_factory import get_device_factory
from phone_agent.model import ModelClient, ModelConfig
from phone_agent.model.client import MessageBuilder


def compute_screen_hash(base64_data: str) -> str:
    """计算截图哈希，用于快速变化检测"""
    return hashlib.md5(base64_data.encode()).hexdigest()[:16]


@dataclass
class AgentConfig:
    """Configuration for the PhoneAgent."""
    max_steps: int = 100
    device_id: str | None = None
    lang: str = "cn"
    system_prompt: str | None = None
    verbose: bool = True
    max_duration_seconds: int = 0  # 时间限制（秒），0表示不限制

    def __post_init__(self):
        if self.system_prompt is None:
            self.system_prompt = get_system_prompt(self.lang)


@dataclass
class StepResult:
    """Result of a single agent step."""
    success: bool
    finished: bool
    action: dict[str, Any] | None
    thinking: str
    message: str | None = None


@dataclass
class ActionRecord:
    """单步操作记录，用于循环检测"""
    step_id: int
    action_type: str          # Tap, Swipe, Type, etc.
    action_params: str        # 参数摘要，如坐标
    screen_hash_before: str   # 操作前屏幕哈希
    screen_hash_after: str    # 操作后屏幕哈希
    screen_changed: bool


@dataclass
class ExecutionContext:
    """执行上下文，用于跟踪任务状态和检测循环"""
    task: str = ""
    start_time: float = field(default_factory=time.time)
    max_duration_seconds: int = 0
    step_count: int = 0
    max_steps: int = 100

    # 操作历史（用于循环检测）
    action_history: List[ActionRecord] = field(default_factory=list)
    screen_hash_history: List[str] = field(default_factory=list)  # 所有出现过的屏幕哈希

    # 结构化任务状态
    milestones: List[str] = field(default_factory=list)  # 已完成的里程碑
    current_stage: str = ""  # 当前阶段描述

    # 循环检测状态
    loop_warning: str = ""  # 循环警告信息
    intervention_action: dict | None = None  # 需要强制执行的干预操作

    def get_elapsed_seconds(self) -> int:
        return int(time.time() - self.start_time)

    def get_remaining_seconds(self) -> int:
        if self.max_duration_seconds <= 0:
            return -1
        return max(0, self.max_duration_seconds - self.get_elapsed_seconds())

    def is_time_exceeded(self) -> bool:
        if self.max_duration_seconds <= 0:
            return False
        return self.get_elapsed_seconds() >= self.max_duration_seconds

    def record_action(self, action: dict, hash_before: str, hash_after: str) -> None:
        """记录操作，用于后续循环检测"""
        action_type = action.get("action", "unknown")

        # 提取关键参数
        if action_type == "Tap":
            params = str(action.get("element", []))
        elif action_type == "Swipe":
            params = f"{action.get('start', [])} -> {action.get('end', [])}"
        elif action_type == "Type":
            text = action.get("text", "")
            params = text[:20] + "..." if len(text) > 20 else text
        elif action_type == "Launch":
            params = action.get("app", "")
        else:
            params = ""

        record = ActionRecord(
            step_id=self.step_count,
            action_type=action_type,
            action_params=params,
            screen_hash_before=hash_before,
            screen_hash_after=hash_after,
            screen_changed=(hash_before != hash_after),
        )
        self.action_history.append(record)

        # 记录屏幕哈希历史
        if hash_after not in self.screen_hash_history:
            self.screen_hash_history.append(hash_after)

    def detect_loop(self) -> str:
        """
        检测操作循环，返回警告信息

        检测策略：
        1. 重复操作：连续N次相同类型+相似参数的操作
        2. 状态循环：屏幕哈希回到之前出现过的状态
        3. 无效操作：连续N次屏幕无变化
        """
        self.loop_warning = ""
        self.intervention_action = None

        if len(self.action_history) < 3:
            return ""

        recent = self.action_history[-5:]  # 最近5步

        # 检测1：连续无变化
        no_change_count = sum(1 for r in recent if not r.screen_changed)
        if no_change_count >= 3:
            self.loop_warning = f"⚠️【循环警告】最近 {len(recent)} 步中有 {no_change_count} 步屏幕无变化，可能陷入无效循环"
            if no_change_count >= 4:
                # 强制干预：返回上一页
                self.intervention_action = {"action": "Back", "_intervention": True}
                self.loop_warning += "\n🔄【自动干预】将执行 Back 返回，尝试重置状态"
            return self.loop_warning

        # 检测2：重复相同操作
        if len(recent) >= 3:
            last_3 = recent[-3:]
            same_type = all(r.action_type == last_3[0].action_type for r in last_3)
            same_params = all(r.action_params == last_3[0].action_params for r in last_3)
            if same_type and same_params and last_3[0].action_type in ["Tap", "Swipe"]:
                self.loop_warning = f"⚠️【循环警告】连续 3 次执行相同的 {last_3[0].action_type} 操作 ({last_3[0].action_params})，请换一种方式"
                return self.loop_warning

        # 检测3：状态循环（回到之前的屏幕）
        if len(self.action_history) >= 2:
            current_hash = self.action_history[-1].screen_hash_after
            # 检查是否回到了5步之前出现过的状态
            for i, record in enumerate(self.action_history[:-5]):
                if record.screen_hash_after == current_hash:
                    self.loop_warning = f"⚠️【循环警告】当前屏幕状态与第 {record.step_id} 步相同，可能在原地循环"
                    return self.loop_warning

        return ""

    def add_milestone(self, milestone: str) -> None:
        """添加已完成的里程碑"""
        if milestone and milestone not in self.milestones:
            self.milestones.append(milestone)

    def set_current_stage(self, stage: str) -> None:
        """设置当前阶段"""
        self.current_stage = stage

    def build_task_state(self) -> str:
        """
        构建结构化任务状态，注入到每一步
        这是解决长任务精度下降的关键
        """
        lines = []

        # 1. 原始任务（始终保留，但截断过长的部分）
        task_desc = self.task
        if "=====" in task_desc:
            task_desc = task_desc.split("=====")[0].strip()
        if len(task_desc) > 150:
            task_desc = task_desc[:150] + "..."
        lines.append(f"【任务目标】{task_desc}")

        # 2. 已完成的里程碑
        if self.milestones:
            lines.append(f"【已完成】{' → '.join(self.milestones)}")

        # 3. 当前阶段
        if self.current_stage:
            lines.append(f"【当前阶段】{self.current_stage}")

        # 4. 执行进度
        lines.append(f"【进度】第 {self.step_count} 步 / 最多 {self.max_steps} 步")

        # 5. 时间状态（如果有限制）
        if self.max_duration_seconds > 0:
            remaining = self.get_remaining_seconds()
            remaining_min = remaining // 60
            remaining_sec = remaining % 60
            lines.append(f"【剩余时间】{remaining_min}分{remaining_sec}秒")
            if remaining < 30:
                lines.append("⚠️ 时间即将结束，请尽快完成")

        # 6. 最近操作摘要（最近3步）
        if self.action_history:
            recent = self.action_history[-3:]
            recent_desc = []
            for r in recent:
                status = "✓" if r.screen_changed else "✗"
                recent_desc.append(f"{status}{r.action_type}")
            lines.append(f"【最近操作】{' → '.join(recent_desc)}")

        # 7. 循环警告（如果有）
        if self.loop_warning:
            lines.append(self.loop_warning)

        return "\n".join(lines)

    def extract_milestone_from_thinking(self, thinking: str) -> None:
        """
        从 LLM 的思考中提取里程碑
        LLM 可以在 think 中用 [里程碑:xxx] 标记完成的关键步骤
        """
        import re
        matches = re.findall(r'\[里程碑[：:]\s*([^\]]+)\]', thinking)
        for m in matches:
            self.add_milestone(m.strip())

        # 也提取当前阶段
        stage_match = re.search(r'\[阶段[：:]\s*([^\]]+)\]', thinking)
        if stage_match:
            self.set_current_stage(stage_match.group(1).strip())


class PhoneAgent:
    """
    AI-powered agent for automating Android phone interactions.
    """

    def __init__(
        self,
        model_config: ModelConfig | None = None,
        agent_config: AgentConfig | None = None,
        confirmation_callback: Callable[[str], bool] | None = None,
        takeover_callback: Callable[[str], None] | None = None,
    ):
        self.model_config = model_config or ModelConfig()
        self.agent_config = agent_config or AgentConfig()

        self.model_client = ModelClient(self.model_config)
        self.action_handler = ActionHandler(
            device_id=self.agent_config.device_id,
            confirmation_callback=confirmation_callback,
            takeover_callback=takeover_callback,
        )

        self._context: list[dict[str, Any]] = []
        self._step_count = 0
        self._exec_context: ExecutionContext | None = None
        self._last_screen_hash: str = ""
        self._max_context_messages: int = 20

    def run(self, task: str) -> str:
        """Run the agent to complete a task."""
        self._context = []
        self._step_count = 0
        self._last_screen_hash = ""
        self._exec_context = ExecutionContext(
            task=task,
            start_time=time.time(),
            max_duration_seconds=self.agent_config.max_duration_seconds,
            max_steps=self.agent_config.max_steps,
        )

        result = self._execute_step(task, is_first=True)

        if result.finished:
            return result.message or "Task completed"

        while self._step_count < self.agent_config.max_steps:
            if self._exec_context and self._exec_context.is_time_exceeded():
                elapsed = self._exec_context.get_elapsed_seconds()
                return f"已达到时间限制 ({elapsed}秒)，任务自动结束"

            result = self._execute_step(is_first=False)

            if result.finished:
                return result.message or "Task completed"

        return "Max steps reached"

    def step(self, task: str | None = None) -> StepResult:
        """Execute a single step of the agent."""
        is_first = len(self._context) == 0

        if is_first and not task:
            raise ValueError("Task is required for the first step")

        if is_first:
            self._exec_context = ExecutionContext(
                task=task,
                start_time=time.time(),
                max_duration_seconds=self.agent_config.max_duration_seconds,
                max_steps=self.agent_config.max_steps,
            )

        if self._exec_context and self._exec_context.is_time_exceeded():
            elapsed = self._exec_context.get_elapsed_seconds()
            return StepResult(
                success=True,
                finished=True,
                action={"_metadata": "finish", "message": f"已达到时间限制 ({elapsed}秒)"},
                thinking="时间限制已到，自动结束任务",
                message=f"已达到时间限制 ({elapsed}秒)，任务自动结束",
            )

        return self._execute_step(task, is_first)

    def reset(self) -> None:
        """Reset the agent state for a new task."""
        self._context = []
        self._step_count = 0
        self._exec_context = None
        self._last_screen_hash = ""

    def _execute_step(
        self, user_prompt: str | None = None, is_first: bool = False
    ) -> StepResult:
        """Execute a single step of the agent loop."""
        self._step_count += 1

        if self._exec_context:
            self._exec_context.step_count = self._step_count

            # 检查是否有强制干预操作
            if self._exec_context.intervention_action:
                intervention = self._exec_context.intervention_action
                self._exec_context.intervention_action = None
                if self.agent_config.verbose:
                    print(f"🔄 执行干预操作: {intervention.get('action')}")
                # 直接执行干预操作
                device_factory = get_device_factory()
                screenshot = device_factory.get_screenshot(self.agent_config.device_id)
                self.action_handler.execute(intervention, screenshot.width, screenshot.height)
                time.sleep(0.5)

        # Capture current screen state
        device_factory = get_device_factory()
        screenshot = device_factory.get_screenshot(self.agent_config.device_id)
        current_app = device_factory.get_current_app(self.agent_config.device_id)
        current_screen_hash = compute_screen_hash(screenshot.base64_data)

        # Build messages
        if is_first:
            self._context.append(
                MessageBuilder.create_system_message(self.agent_config.system_prompt)
            )
            screen_info = MessageBuilder.build_screen_info(current_app)

            # 第一步的提示
            task_state = ""
            if self._exec_context and self._exec_context.max_duration_seconds > 0:
                task_state = self._exec_context.build_task_state() + "\n\n"

            text_content = f"{user_prompt}\n\n{task_state}{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )
            self._last_screen_hash = current_screen_hash
        else:
            screen_info = MessageBuilder.build_screen_info(current_app)

            # 构建结构化任务状态
            task_state = ""
            if self._exec_context:
                # 先检测循环
                self._exec_context.detect_loop()
                task_state = self._exec_context.build_task_state()

            text_content = f"---\n{task_state}\n---\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )

        # 智能上下文压缩
        self._compress_context_if_needed()

        # Get model response
        try:
            msgs = get_messages(self.agent_config.lang)
            print("\n" + "=" * 50)
            print(f"💭 {msgs['thinking']}:")
            print("-" * 50)
            response = self.model_client.request(self._context)
        except Exception as e:
            if self.agent_config.verbose:
                traceback.print_exc()
            return StepResult(
                success=False,
                finished=True,
                action=None,
                thinking="",
                message=f"Model error: {e}",
            )

        # 从思考中提取里程碑
        if self._exec_context and response.thinking:
            self._exec_context.extract_milestone_from_thinking(response.thinking)

        # Parse action from response
        try:
            action = parse_action(response.action)
        except ValueError as e:
            if self.agent_config.verbose:
                traceback.print_exc()
            if not response.action or not response.action.strip():
                print("⚠️ AI model returned empty response, will retry...")
                return StepResult(
                    success=True,
                    finished=False,
                    action=do(action="Wait", duration="1 seconds"),
                    thinking=response.thinking or "Empty response, waiting...",
                    message="Waiting for AI response...",
                )
            action = finish(message=response.action)

        if self.agent_config.verbose:
            print("-" * 50)
            print(f"🎯 {msgs['action']}:")
            print(json.dumps(action, ensure_ascii=False, indent=2))
            print("=" * 50 + "\n")

        # Remove image from context to save space
        self._context[-1] = MessageBuilder.remove_images_from_message(self._context[-1])

        # Execute action
        try:
            result = self.action_handler.execute(
                action, screenshot.width, screenshot.height
            )
        except Exception as e:
            if self.agent_config.verbose:
                traceback.print_exc()
            result = self.action_handler.execute(
                finish(message=str(e)), screenshot.width, screenshot.height
            )

        # 记录操作结果用于循环检测
        if action.get("_metadata") != "finish":
            time.sleep(0.3)
            screenshot_after = device_factory.get_screenshot(self.agent_config.device_id)
            screen_hash_after = compute_screen_hash(screenshot_after.base64_data)

            # 先判断是否变化（在更新之前）
            screen_changed = (self._last_screen_hash != screen_hash_after)

            if self._exec_context:
                self._exec_context.record_action(action, self._last_screen_hash, screen_hash_after)

            # 更新哈希
            self._last_screen_hash = screen_hash_after

            # 打印操作结果
            if self.agent_config.verbose:
                if screen_changed:
                    print("✓ 屏幕已更新")
                else:
                    print("✗ 屏幕无变化")

        # Add assistant response to context
        self._context.append(
            MessageBuilder.create_assistant_message(
                f"<think>{response.thinking}</think><answer>{response.action}</answer>"
            )
        )

        finished = action.get("_metadata") == "finish" or result.should_finish

        if finished and self.agent_config.verbose:
            msgs = get_messages(self.agent_config.lang)
            print("\n" + "🎉 " + "=" * 48)
            print(f"✅ {msgs['task_completed']}: {result.message or action.get('message', msgs['done'])}")
            print("=" * 50 + "\n")

        return StepResult(
            success=result.success,
            finished=finished,
            action=action,
            thinking=response.thinking,
            message=result.message or action.get("message"),
        )

    @property
    def context(self) -> list[dict[str, Any]]:
        return self._context.copy()

    @property
    def step_count(self) -> int:
        return self._step_count

    def _compress_context_if_needed(self) -> None:
        """
        智能上下文压缩
        保留：系统消息 + 第一条用户消息（含原始任务） + 最近N轮对话
        """
        if len(self._context) <= self._max_context_messages:
            return

        system_msg = self._context[0] if self._context else None
        first_user_msg = self._context[1] if len(self._context) > 1 else None

        # 保留最近的消息
        keep_recent = self._max_context_messages - 2  # 减去系统消息和第一条用户消息
        recent_messages = self._context[-keep_recent:]

        # 重建上下文
        new_context = []
        if system_msg:
            new_context.append(system_msg)
        if first_user_msg:
            new_context.append(first_user_msg)
        new_context.extend(recent_messages)

        self._context = new_context

        if self.agent_config.verbose:
            print(f"📝 上下文已压缩至 {len(self._context)} 条消息")
