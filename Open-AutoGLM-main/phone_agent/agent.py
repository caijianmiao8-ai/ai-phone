"""Main PhoneAgent class for orchestrating phone automation."""

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from phone_agent.actions import ActionHandler
from phone_agent.actions.handler import do, finish, parse_action
from phone_agent.config import get_messages, get_system_prompt
from phone_agent.device_factory import get_device_factory
from phone_agent.model import ModelClient, ModelConfig
from phone_agent.model.client import MessageBuilder


@dataclass
class AgentConfig:
    """Configuration for the PhoneAgent."""

    max_steps: int = 100
    device_id: str | None = None
    lang: str = "cn"
    system_prompt: str | None = None
    verbose: bool = True
    # 新增：时间限制（秒），0表示不限制
    max_duration_seconds: int = 0

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
class ExecutionContext:
    """执行上下文，用于跟踪任务状态"""
    task: str = ""
    start_time: float = field(default_factory=time.time)
    max_duration_seconds: int = 0
    step_count: int = 0
    max_steps: int = 100

    def get_elapsed_seconds(self) -> int:
        """获取已执行时间（秒）"""
        return int(time.time() - self.start_time)

    def get_remaining_seconds(self) -> int:
        """获取剩余时间（秒），-1表示无限制"""
        if self.max_duration_seconds <= 0:
            return -1
        remaining = self.max_duration_seconds - self.get_elapsed_seconds()
        return max(0, remaining)

    def is_time_exceeded(self) -> bool:
        """检查是否超时"""
        if self.max_duration_seconds <= 0:
            return False
        return self.get_elapsed_seconds() >= self.max_duration_seconds

    def build_context_hint(self) -> str:
        """构建上下文提示，注入到每一步"""
        elapsed = self.get_elapsed_seconds()
        remaining = self.get_remaining_seconds()

        hints = []
        hints.append(f"【当前任务】{self.task}")
        hints.append(f"【执行进度】第 {self.step_count} 步 / 最多 {self.max_steps} 步")

        if self.max_duration_seconds > 0:
            elapsed_min = elapsed // 60
            elapsed_sec = elapsed % 60
            remaining_min = remaining // 60
            remaining_sec = remaining % 60
            hints.append(f"【时间状态】已执行 {elapsed_min}分{elapsed_sec}秒，剩余约 {remaining_min}分{remaining_sec}秒")

            # 时间提醒
            if remaining < 30:
                hints.append("⚠️ 时间即将结束，请尽快完成当前操作并调用 finish() 结束任务")
            elif remaining < 60:
                hints.append("⏰ 剩余时间不足1分钟，请准备结束任务")

        return "\n".join(hints)


class PhoneAgent:
    """
    AI-powered agent for automating Android phone interactions.

    The agent uses a vision-language model to understand screen content
    and decide on actions to complete user tasks.

    Args:
        model_config: Configuration for the AI model.
        agent_config: Configuration for the agent behavior.
        confirmation_callback: Optional callback for sensitive action confirmation.
        takeover_callback: Optional callback for takeover requests.

    Example:
        >>> from phone_agent import PhoneAgent
        >>> from phone_agent.model import ModelConfig
        >>>
        >>> model_config = ModelConfig(base_url="http://localhost:8000/v1")
        >>> agent = PhoneAgent(model_config)
        >>> agent.run("Open WeChat and send a message to John")
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

    def run(self, task: str) -> str:
        """
        Run the agent to complete a task.

        Args:
            task: Natural language description of the task.

        Returns:
            Final message from the agent.
        """
        self._context = []
        self._step_count = 0
        self._exec_context = ExecutionContext(
            task=task,
            start_time=time.time(),
            max_duration_seconds=self.agent_config.max_duration_seconds,
            max_steps=self.agent_config.max_steps,
        )

        # First step with user prompt
        result = self._execute_step(task, is_first=True)

        if result.finished:
            return result.message or "Task completed"

        # Continue until finished or max steps reached
        while self._step_count < self.agent_config.max_steps:
            # 检查时间限制
            if self._exec_context and self._exec_context.is_time_exceeded():
                elapsed = self._exec_context.get_elapsed_seconds()
                return f"已达到时间限制 ({elapsed}秒)，任务自动结束"

            result = self._execute_step(is_first=False)

            if result.finished:
                return result.message or "Task completed"

        return "Max steps reached"

    def step(self, task: str | None = None) -> StepResult:
        """
        Execute a single step of the agent.

        Useful for manual control or debugging.

        Args:
            task: Task description (only needed for first step).

        Returns:
            StepResult with step details.
        """
        is_first = len(self._context) == 0

        if is_first and not task:
            raise ValueError("Task is required for the first step")

        # 初始化执行上下文
        if is_first:
            self._exec_context = ExecutionContext(
                task=task,
                start_time=time.time(),
                max_duration_seconds=self.agent_config.max_duration_seconds,
                max_steps=self.agent_config.max_steps,
            )

        # 检查时间限制
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

    def _execute_step(
        self, user_prompt: str | None = None, is_first: bool = False
    ) -> StepResult:
        """Execute a single step of the agent loop."""
        self._step_count += 1

        # 更新执行上下文
        if self._exec_context:
            self._exec_context.step_count = self._step_count

        # Capture current screen state
        device_factory = get_device_factory()
        screenshot = device_factory.get_screenshot(self.agent_config.device_id)
        current_app = device_factory.get_current_app(self.agent_config.device_id)

        # Build messages
        if is_first:
            self._context.append(
                MessageBuilder.create_system_message(self.agent_config.system_prompt)
            )

            screen_info = MessageBuilder.build_screen_info(current_app)

            # 第一步也包含时间和任务提示（如果有时间限制）
            context_hint = ""
            if self._exec_context and self._exec_context.max_duration_seconds > 0:
                context_hint = self._exec_context.build_context_hint() + "\n\n"

            text_content = f"{user_prompt}\n\n{context_hint}{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )
        else:
            screen_info = MessageBuilder.build_screen_info(current_app)

            # 构建上下文提示（包含任务提醒、进度、时间状态）
            context_hint = ""
            if self._exec_context:
                context_hint = self._exec_context.build_context_hint()

            # 在每一步都提醒 AI 当前任务和状态
            text_content = f"** 执行状态 **\n\n{context_hint}\n\n** Screen Info **\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )

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

        # Parse action from response
        try:
            action = parse_action(response.action)
        except ValueError:
            if self.agent_config.verbose:
                traceback.print_exc()
            action = finish(message=response.action)

        if self.agent_config.verbose:
            # Print thinking process
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

        # Add assistant response to context
        self._context.append(
            MessageBuilder.create_assistant_message(
                f"<think>{response.thinking}</think><answer>{response.action}</answer>"
            )
        )

        # Check if finished
        finished = action.get("_metadata") == "finish" or result.should_finish

        if finished and self.agent_config.verbose:
            msgs = get_messages(self.agent_config.lang)
            print("\n" + "🎉 " + "=" * 48)
            print(
                f"✅ {msgs['task_completed']}: {result.message or action.get('message', msgs['done'])}"
            )
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
        """Get the current conversation context."""
        return self._context.copy()

    @property
    def step_count(self) -> int:
        """Get the current step count."""
        return self._step_count
