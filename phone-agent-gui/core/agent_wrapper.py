"""
Agent包装器模块
集成原有PhoneAgent，并添加知识库增强功能
"""
import sys
import os
from typing import Optional, Callable, Generator, Tuple
from dataclasses import dataclass

# 添加项目路径到sys.path
PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

# 检查本地是否有 phone_agent 模块（打包后或复制后的情况）
LOCAL_PHONE_AGENT = os.path.join(PROJECT_PATH, "phone_agent")

# 如果本地没有，则从原项目路径查找
if not os.path.exists(LOCAL_PHONE_AGENT):
    ORIGINAL_PROJECT_PATH = os.path.join(
        os.path.dirname(PROJECT_PATH),
        "Open-AutoGLM-main"
    )
    if os.path.exists(ORIGINAL_PROJECT_PATH) and ORIGINAL_PROJECT_PATH not in sys.path:
        sys.path.insert(0, ORIGINAL_PROJECT_PATH)

from knowledge_base.manager import KnowledgeManager, KnowledgeItem


@dataclass
class StepResult:
    """单步执行结果"""
    success: bool
    finished: bool
    action: str
    thinking: str
    screenshot: Optional[bytes] = None
    error: str = ""
    knowledge_used: Optional[str] = None


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    message: str
    steps_executed: int
    history: list


class AgentWrapper:
    """PhoneAgent包装器，集成知识库功能"""

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        model_name: str = "autoglm-phone-9b",
        max_tokens: int = 3000,
        temperature: float = 0.1,
        device_id: Optional[str] = None,
        max_steps: int = 50,
        language: str = "cn",
        verbose: bool = True,
        knowledge_manager: Optional[KnowledgeManager] = None,
        use_knowledge_base: bool = True,
    ):
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.device_id = device_id
        self.max_steps = max_steps
        self.language = language
        self.verbose = verbose
        self.knowledge_manager = knowledge_manager
        self.use_knowledge_base = use_knowledge_base

        self._agent = None
        self._is_running = False
        self._should_stop = False

        # 回调函数
        self.on_step_callback: Optional[Callable[[StepResult], None]] = None
        self.on_log_callback: Optional[Callable[[str], None]] = None

    def _log(self, message: str):
        """记录日志"""
        if self.on_log_callback:
            self.on_log_callback(message)

    def _init_agent(self):
        """初始化原始Agent"""
        try:
            from phone_agent import PhoneAgent
            from phone_agent.agent import ModelConfig, AgentConfig

            model_config = ModelConfig(
                base_url=self.api_base_url,
                api_key=self.api_key,
                model_name=self.model_name,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            agent_config = AgentConfig(
                max_steps=self.max_steps,
                device_id=self.device_id,
                lang=self.language,
                verbose=self.verbose,
            )

            self._agent = PhoneAgent(
                model_config=model_config,
                agent_config=agent_config,
            )

            return True
        except ImportError as e:
            self._log(f"导入PhoneAgent失败: {str(e)}")
            return False
        except Exception as e:
            self._log(f"初始化Agent失败: {str(e)}")
            return False

    def _enhance_task_with_knowledge(self, task: str) -> Tuple[str, Optional[KnowledgeItem]]:
        """使用知识库增强任务描述"""
        if not self.use_knowledge_base or not self.knowledge_manager:
            return task, None

        # 搜索匹配的知识
        matched_item = self.knowledge_manager.get_best_match(task)

        if matched_item:
            self._log(f"知识库匹配: {matched_item.title}")
            # 构建增强后的任务描述
            enhanced_task = f"""{task}

[参考操作指南 - {matched_item.title}]:
{matched_item.content}

请参考以上指南执行任务，但要根据实际屏幕内容灵活调整。"""
            return enhanced_task, matched_item

        return task, None

    def test_api_connection(self) -> Tuple[bool, str]:
        """测试API连接"""
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=self.api_base_url,
                api_key=self.api_key or "test-key",
            )

            # 简单测试请求
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10,
            )

            return True, "API连接成功"
        except Exception as e:
            return False, f"API连接失败: {str(e)}"

    def run_task(self, task: str) -> Generator[StepResult, None, TaskResult]:
        """
        执行任务（生成器模式，逐步返回结果）

        Usage:
            for step_result in agent.run_task("打开淘宝"):
                print(step_result.action)
        """
        self._is_running = True
        self._should_stop = False
        steps_executed = 0
        history = []

        try:
            # 初始化Agent
            self._log("正在初始化Agent...")
            if not self._init_agent():
                yield StepResult(
                    success=False,
                    finished=True,
                    action="",
                    thinking="",
                    error="Agent初始化失败"
                )
                return TaskResult(
                    success=False,
                    message="Agent初始化失败",
                    steps_executed=0,
                    history=[]
                )

            # 知识库增强
            enhanced_task, knowledge_item = self._enhance_task_with_knowledge(task)
            knowledge_used = knowledge_item.title if knowledge_item else None

            self._log(f"开始执行任务: {task}")
            if knowledge_used:
                self._log(f"使用知识库: {knowledge_used}")

            # 重置Agent状态
            self._agent.reset()

            # 执行循环
            while not self._should_stop and steps_executed < self.max_steps:
                steps_executed += 1
                self._log(f"执行步骤 {steps_executed}/{self.max_steps}")

                try:
                    # 执行单步
                    step_result = self._agent.step(enhanced_task)

                    # 获取截图
                    screenshot = None
                    try:
                        from phone_agent.device_factory import DeviceFactory
                        factory = DeviceFactory.get_instance()
                        screenshot_obj = factory.get_screenshot()
                        if screenshot_obj and screenshot_obj.data:
                            import base64
                            screenshot = base64.b64decode(screenshot_obj.data)
                    except Exception:
                        pass

                    result = StepResult(
                        success=step_result.success,
                        finished=step_result.finished,
                        action=step_result.action or "",
                        thinking=step_result.thinking or "",
                        screenshot=screenshot,
                        knowledge_used=knowledge_used
                    )

                    history.append({
                        "step": steps_executed,
                        "action": result.action,
                        "thinking": result.thinking,
                    })

                    self._log(f"AI思考: {result.thinking[:100]}..." if len(result.thinking) > 100 else f"AI思考: {result.thinking}")
                    self._log(f"执行动作: {result.action}")

                    yield result

                    if result.finished:
                        self._log("任务完成!")
                        break

                except Exception as e:
                    error_msg = str(e)
                    self._log(f"步骤执行错误: {error_msg}")
                    yield StepResult(
                        success=False,
                        finished=False,
                        action="",
                        thinking="",
                        error=error_msg
                    )

            # 任务结束
            if self._should_stop:
                message = "任务已手动停止"
            elif steps_executed >= self.max_steps:
                message = f"已达到最大步数限制 ({self.max_steps})"
            else:
                message = "任务执行完成"

            self._log(message)
            return TaskResult(
                success=not self._should_stop,
                message=message,
                steps_executed=steps_executed,
                history=history
            )

        finally:
            self._is_running = False

    def stop(self):
        """停止任务执行"""
        self._should_stop = True
        self._log("正在停止任务...")

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._is_running

    def reset(self):
        """重置Agent状态"""
        if self._agent:
            self._agent.reset()
        self._is_running = False
        self._should_stop = False
