"""
Agent V2 - LLM 驱动的闭环决策 Agent

核心设计思想：
1. 保留 LLM 完整决策能力（不预编排）
2. 增强观察（截图 + UI 树 + 设备状态）
3. 验证反馈（每步执行后检测变化，反馈给 LLM）
4. LLM 自主恢复（失败时让 LLM 自己调整，而非固定规则）
5. 上下文管理（防止长任务中信息丢失）
"""

import json
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..adb_helper import ADBHelper
from .action import ActionExecutor
from .memory import ContextManager
from .observation import Observer
from .prompt import PromptBuilder
from .prompt.builder import parse_llm_response
from .types import Action, ActionType, Observation, StepResult, TaskResult, VerifyResult
from .verification import Verifier


@dataclass
class AgentConfig:
    """Agent 配置"""
    max_steps: int = 50  # 最大步数
    max_retries_per_step: int = 3  # 每步最大重试次数
    step_timeout: float = 30.0  # 单步超时（秒）
    screen_wait_timeout: float = 5.0  # 等待屏幕变化超时
    verbose: bool = True  # 是否输出详细日志
    output_dir: Optional[Path] = None  # 输出目录（保存截图、日志）


class AgentV2:
    """
    Agent V2 - 闭环决策 Agent

    执行流程：
    1. 观察当前屏幕状态（截图 + UI 树）
    2. 构建增强提示（包含 UI 元素、上下文、上一步反馈）
    3. 调用 LLM 决策下一步操作
    4. 执行操作
    5. 验证操作效果
    6. 将验证结果反馈给下一轮 LLM 决策
    7. 重复直到任务完成或达到限制
    """

    def __init__(
        self,
        llm_client: Any,  # LLM 客户端，需要实现 request(messages) 方法
        config: Optional[AgentConfig] = None,
        adb_helper: Optional[ADBHelper] = None,
    ):
        self.llm_client = llm_client
        self.config = config or AgentConfig()
        self.adb = adb_helper or ADBHelper()

        # 初始化组件
        output_dir = self.config.output_dir
        self.observer = Observer(self.adb, output_dir / "observations" if output_dir else None)
        self.executor = ActionExecutor(self.adb)
        self.verifier = Verifier()
        self.context_manager = ContextManager()
        self.prompt_builder = PromptBuilder()

        # 状态
        self._current_observation: Optional[Observation] = None
        self._step_count = 0
        self._consecutive_failures = 0

    def run(self, task: str) -> TaskResult:
        """
        执行任务

        Args:
            task: 任务描述

        Returns:
            TaskResult 任务执行结果
        """
        start_time = time.time()
        self._step_count = 0
        self._consecutive_failures = 0

        # 初始化上下文
        self.context_manager.start_task(task)

        # 获取初始观察
        try:
            self._current_observation = self.observer.observe()
        except Exception as e:
            return TaskResult(
                task=task,
                success=False,
                message=f"无法获取初始屏幕状态: {e}",
                elapsed_seconds=time.time() - start_time,
            )

        steps: List[StepResult] = []
        last_feedback: Optional[str] = None

        # 主循环
        while self._step_count < self.config.max_steps:
            self._step_count += 1

            if self.config.verbose:
                print(f"\n{'='*50}")
                print(f"步骤 {self._step_count}")
                print(f"{'='*50}")

            try:
                # 执行一步
                step_result = self._execute_step(
                    task=task,
                    is_first_step=(self._step_count == 1),
                    last_feedback=last_feedback,
                )
                steps.append(step_result)

                # 检查是否完成
                if step_result.action.action_type == ActionType.FINISH:
                    return TaskResult(
                        task=task,
                        success=True,
                        message=step_result.action.message or "任务完成",
                        steps=steps,
                        total_steps=self._step_count,
                        elapsed_seconds=time.time() - start_time,
                    )

                # 更新反馈
                last_feedback = step_result.verify_result.to_feedback()

                # 处理连续失败
                if not step_result.verify_result.changed:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= self.config.max_retries_per_step:
                        self.context_manager.set_last_error(
                            f"连续 {self._consecutive_failures} 次操作无效果"
                        )
                else:
                    self._consecutive_failures = 0
                    self.context_manager.clear_last_error()

                # 更新当前观察
                self._current_observation = step_result.observation_after

            except Exception as e:
                if self.config.verbose:
                    traceback.print_exc()
                return TaskResult(
                    task=task,
                    success=False,
                    message=f"执行异常: {e}",
                    steps=steps,
                    total_steps=self._step_count,
                    elapsed_seconds=time.time() - start_time,
                )

        # 达到最大步数
        return TaskResult(
            task=task,
            success=False,
            message=f"达到最大步数限制 ({self.config.max_steps})",
            steps=steps,
            total_steps=self._step_count,
            elapsed_seconds=time.time() - start_time,
        )

    def _execute_step(
        self,
        task: str,
        is_first_step: bool,
        last_feedback: Optional[str],
    ) -> StepResult:
        """执行单步"""
        observation_before = self._current_observation

        # 1. 构建消息
        context_summary = self.context_manager.get_context_for_llm()

        messages = [
            self.prompt_builder.build_system_message(),
            self.prompt_builder.build_user_message(
                observation=observation_before,
                task=task,
                context_summary=context_summary,
                last_action_feedback=last_feedback,
                is_first_step=is_first_step,
            ),
        ]

        # 2. 调用 LLM
        if self.config.verbose:
            print("正在思考...")

        try:
            response = self.llm_client.request(messages)
            response_text = response.action if hasattr(response, 'action') else str(response)
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}")

        # 3. 解析响应
        parsed = parse_llm_response(response_text)
        action = self._parse_action(parsed)

        if self.config.verbose:
            print(f"思考: {action.thinking}")
            print(f"决定: {action.action_type.value}")
            if action.element_index is not None:
                print(f"目标元素: [{action.element_index}]")

        # 4. 执行行动
        if action.action_type != ActionType.FINISH:
            success = self.executor.execute(action, observation_before)
            if not success and self.config.verbose:
                print("警告: 行动执行可能失败")

        # 5. 等待并获取新观察
        if action.action_type not in (ActionType.FINISH, ActionType.WAIT):
            observation_after = self.observer.wait_for_change(
                observation_before,
                timeout=self.config.screen_wait_timeout,
            )
        else:
            observation_after = self.observer.observe()

        # 6. 验证效果
        verify_result = self.verifier.verify(observation_before, observation_after, action)

        if self.config.verbose:
            if verify_result.changed:
                print(f"效果: {verify_result.details}")
            else:
                print(f"效果: 无变化 - {verify_result.details}")

        # 7. 记录到上下文
        action_summary = self._summarize_action(action)
        result_summary = verify_result.details
        key_observation = self._extract_key_observation(observation_after)

        self.context_manager.add_step(
            action_summary=action_summary,
            result_summary=result_summary,
            key_observation=key_observation,
            success=verify_result.changed,
        )

        return StepResult(
            step_id=self._step_count,
            action=action,
            observation_before=observation_before,
            observation_after=observation_after,
            verify_result=verify_result,
            success=verify_result.changed,
        )

    def _parse_action(self, parsed: Dict[str, Any]) -> Action:
        """将解析的响应转换为 Action"""
        action_str = parsed.get("action", "wait")

        # 映射 action 字符串到 ActionType
        action_map = {
            "tap": ActionType.TAP,
            "long_press": ActionType.LONG_PRESS,
            "swipe": ActionType.SWIPE,
            "type": ActionType.TYPE,
            "back": ActionType.BACK,
            "home": ActionType.HOME,
            "wait": ActionType.WAIT,
            "finish": ActionType.FINISH,
        }

        action_type = action_map.get(action_str.lower(), ActionType.WAIT)

        return Action(
            action_type=action_type,
            element_index=parsed.get("element_index"),
            x=parsed.get("x"),
            y=parsed.get("y"),
            direction=parsed.get("direction"),
            distance=parsed.get("distance", 0.3),
            text=parsed.get("text"),
            duration_ms=parsed.get("duration_ms", 500),
            message=parsed.get("message"),
            thinking=parsed.get("thinking", ""),
        )

    def _summarize_action(self, action: Action) -> str:
        """生成行动摘要"""
        action_type = action.action_type

        if action_type == ActionType.TAP:
            if action.element_index is not None:
                return f"点击元素[{action.element_index}]"
            return f"点击坐标({action.x}, {action.y})"

        if action_type == ActionType.LONG_PRESS:
            if action.element_index is not None:
                return f"长按元素[{action.element_index}]"
            return f"长按坐标({action.x}, {action.y})"

        if action_type == ActionType.SWIPE:
            return f"向{action.direction}滑动"

        if action_type == ActionType.TYPE:
            text = action.text or ""
            if len(text) > 20:
                text = text[:20] + "..."
            return f"输入'{text}'"

        if action_type == ActionType.BACK:
            return "返回"

        if action_type == ActionType.HOME:
            return "回到主屏幕"

        if action_type == ActionType.WAIT:
            return f"等待{action.duration_ms}ms"

        if action_type == ActionType.FINISH:
            return f"完成: {action.message}"

        return str(action_type.value)

    def _extract_key_observation(self, observation: Observation) -> str:
        """提取关键观察信息（用于上下文压缩）"""
        parts = []

        # 当前页面
        if observation.activity:
            activity_name = observation.activity.split(".")[-1]
            parts.append(activity_name)

        # 界面关键文字（取前3个有意义的元素）
        key_texts = []
        for elem in observation.ui_elements[:20]:
            if elem.text and len(elem.text) < 20:
                if elem.text not in key_texts:
                    key_texts.append(elem.text)
                    if len(key_texts) >= 3:
                        break

        if key_texts:
            parts.append(f"包含: {', '.join(key_texts)}")

        return " | ".join(parts) if parts else "未知界面"
