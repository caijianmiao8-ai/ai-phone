"""
Dify 工作流集成模块

混合架构设计：
1. Dify 负责高层任务编排（分解、判断、循环控制）
2. PhoneAgent 负责底层执行（截图、识别、操作）
3. 通过 API 双向通信

使用方式：
1. 简单任务（回到桌面、打开App）→ 直接执行
2. 复杂任务（刷视频10分钟、购物）→ Dify 工作流编排
"""

import base64
import json
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import requests


class TaskComplexity(Enum):
    """任务复杂度"""
    SIMPLE = "simple"      # 简单：1-3步可完成
    MEDIUM = "medium"      # 中等：需要判断和循环
    COMPLEX = "complex"    # 复杂：需要多阶段、多条件


class WorkflowStatus(Enum):
    """工作流状态"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_AI = "waiting_ai"      # 等待 AI 执行
    WAITING_USER = "waiting_user"  # 等待用户介入
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DifyConfig:
    """Dify 配置"""
    api_base: str = "http://localhost/v1"
    api_key: str = ""
    # 工作流 ID 映射
    workflow_ids: Dict[str, str] = field(default_factory=dict)
    # 超时设置
    request_timeout: int = 30
    workflow_timeout: int = 600  # 工作流最长执行时间


@dataclass
class StepInstruction:
    """单步执行指令（Dify 发给 PhoneAgent）"""
    action: str                    # 动作类型: tap, swipe, type, launch, wait, check
    params: Dict[str, Any]         # 动作参数
    description: str               # 人类可读描述
    success_condition: str = ""    # 成功条件描述（用于 AI 判断）
    max_retries: int = 3           # 最大重试次数
    timeout_seconds: int = 30      # 单步超时


@dataclass
class StepResult:
    """单步执行结果（PhoneAgent 返回给 Dify）"""
    success: bool
    message: str
    screenshot_base64: str = ""    # 执行后截图
    detected_elements: List[str] = field(default_factory=list)  # 检测到的元素
    current_app: str = ""          # 当前 App
    extra_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowContext:
    """工作流上下文（跨步骤共享）"""
    task_description: str
    variables: Dict[str, Any] = field(default_factory=dict)
    step_history: List[Dict[str, Any]] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    current_step: int = 0
    total_steps: int = 0


class DifyClient:
    """Dify API 客户端"""

    def __init__(self, config: DifyConfig):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        })

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送请求"""
        url = f"{self.config.api_base}{endpoint}"
        kwargs.setdefault("timeout", self.config.request_timeout)

        try:
            response = self._session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def run_workflow(
        self,
        workflow_id: str,
        inputs: Dict[str, Any],
        user_id: str = "phone-agent"
    ) -> Dict[str, Any]:
        """
        运行 Dify 工作流

        Args:
            workflow_id: 工作流 ID
            inputs: 输入变量
            user_id: 用户标识

        Returns:
            工作流执行结果
        """
        payload = {
            "inputs": inputs,
            "response_mode": "blocking",  # 同步等待结果
            "user": user_id
        }

        return self._request(
            "POST",
            f"/workflows/{workflow_id}/run",
            json=payload,
            timeout=self.config.workflow_timeout
        )

    def run_workflow_streaming(
        self,
        workflow_id: str,
        inputs: Dict[str, Any],
        on_event: Callable[[str, Dict], None],
        user_id: str = "phone-agent"
    ):
        """
        流式运行工作流（支持中间结果）

        Args:
            workflow_id: 工作流 ID
            inputs: 输入变量
            on_event: 事件回调
            user_id: 用户标识
        """
        url = f"{self.config.api_base}/workflows/{workflow_id}/run"
        payload = {
            "inputs": inputs,
            "response_mode": "streaming",
            "user": user_id
        }

        try:
            with self._session.post(url, json=payload, stream=True, timeout=self.config.workflow_timeout) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            data = json.loads(line[6:])
                            event_type = data.get('event', 'unknown')
                            on_event(event_type, data)
        except Exception as e:
            on_event('error', {'message': str(e)})

    def chat_completion(
        self,
        query: str,
        conversation_id: str = "",
        files: List[Dict] = None,
        user_id: str = "phone-agent"
    ) -> Dict[str, Any]:
        """
        对话补全（用于 AI 判断）

        Args:
            query: 用户问题
            conversation_id: 会话 ID（用于上下文）
            files: 附件（如截图）
            user_id: 用户标识

        Returns:
            AI 回复
        """
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "user": user_id
        }

        if conversation_id:
            payload["conversation_id"] = conversation_id

        if files:
            payload["files"] = files

        return self._request("POST", "/chat-messages", json=payload)


class TaskRouter:
    """
    任务路由器

    根据任务复杂度决定执行方式：
    - 简单任务：直接调用 PhoneAgent
    - 复杂任务：通过 Dify 工作流编排
    """

    # 简单任务关键词
    SIMPLE_KEYWORDS = [
        "回到桌面", "回到首页", "返回桌面", "返回首页",
        "打开", "启动", "关闭",
        "截图", "截屏",
        "返回", "后退",
    ]

    # 复杂任务关键词
    COMPLEX_KEYWORDS = [
        "刷", "浏览", "逛",  # 时间类
        "购买", "下单", "支付",  # 购物类
        "搜索", "查找", "找到",  # 搜索类
        "发送", "转发", "分享",  # 社交类
        "登录", "注册",  # 账号类
    ]

    # 时间相关词
    TIME_KEYWORDS = ["分钟", "小时", "秒"]

    def __init__(self, dify_config: Optional[DifyConfig] = None):
        self.dify_config = dify_config
        self.dify_client = DifyClient(dify_config) if dify_config else None

    def analyze_task(self, task: str) -> Tuple[TaskComplexity, str]:
        """
        分析任务复杂度

        Args:
            task: 任务描述

        Returns:
            (复杂度, 原因)
        """
        task_lower = task.lower()

        # 检查是否包含时间要求
        has_time = any(kw in task for kw in self.TIME_KEYWORDS)

        # 检查简单任务
        for kw in self.SIMPLE_KEYWORDS:
            if kw in task:
                # 如果只是简单启动/返回，且无其他要求
                if not has_time and len(task) < 20:
                    return TaskComplexity.SIMPLE, f"简单任务：{kw}"

        # 检查复杂任务
        complex_count = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in task)

        if has_time or complex_count >= 2:
            return TaskComplexity.COMPLEX, "需要时间控制或多步骤编排"

        if complex_count == 1:
            return TaskComplexity.MEDIUM, "需要条件判断"

        # 默认中等复杂度
        return TaskComplexity.MEDIUM, "通用任务"

    def get_workflow_id(self, task: str) -> Optional[str]:
        """
        根据任务获取对应的工作流 ID

        Args:
            task: 任务描述

        Returns:
            工作流 ID 或 None
        """
        if not self.dify_config:
            return None

        # 根据关键词匹配工作流
        workflow_ids = self.dify_config.workflow_ids

        if any(kw in task for kw in ["刷视频", "刷抖音", "刷快手", "刷小红书"]):
            return workflow_ids.get("browse_video")

        if any(kw in task for kw in ["购买", "下单", "购物"]):
            return workflow_ids.get("shopping")

        if any(kw in task for kw in ["搜索", "查找"]):
            return workflow_ids.get("search")

        if any(kw in task for kw in ["发消息", "发送消息"]):
            return workflow_ids.get("send_message")

        # 通用工作流
        return workflow_ids.get("general")


class HybridExecutor:
    """
    混合执行器

    协调 Dify 工作流和 PhoneAgent 执行
    """

    def __init__(
        self,
        dify_config: DifyConfig,
        phone_agent_executor: Callable[[str, str], Tuple[bool, str]],
        screenshot_getter: Callable[[str], Optional[str]],
    ):
        """
        初始化混合执行器

        Args:
            dify_config: Dify 配置
            phone_agent_executor: PhoneAgent 执行函数 (device_id, instruction) -> (success, message)
            screenshot_getter: 截图获取函数 (device_id) -> base64_image
        """
        self.dify_client = DifyClient(dify_config)
        self.task_router = TaskRouter(dify_config)
        self.phone_agent_executor = phone_agent_executor
        self.screenshot_getter = screenshot_getter

        self._current_workflow: Optional[WorkflowContext] = None
        self._stop_event = threading.Event()

    def execute_task(
        self,
        task: str,
        device_id: str,
        on_progress: Callable[[str, int, int], None] = None,
        on_step_complete: Callable[[StepResult], None] = None,
    ) -> Tuple[bool, str]:
        """
        执行任务

        Args:
            task: 任务描述
            device_id: 设备 ID
            on_progress: 进度回调 (message, current_step, total_steps)
            on_step_complete: 步骤完成回调

        Returns:
            (成功, 消息)
        """
        self._stop_event.clear()

        # 分析任务复杂度
        complexity, reason = self.task_router.analyze_task(task)

        if on_progress:
            on_progress(f"任务分析: {complexity.value} - {reason}", 0, 0)

        # 简单任务：直接执行
        if complexity == TaskComplexity.SIMPLE:
            return self._execute_simple(task, device_id, on_progress)

        # 中等/复杂任务：尝试使用工作流
        workflow_id = self.task_router.get_workflow_id(task)

        if workflow_id:
            return self._execute_with_workflow(
                task, device_id, workflow_id,
                on_progress, on_step_complete
            )
        else:
            # 无匹配工作流，使用通用 AI 执行
            return self._execute_with_ai(task, device_id, on_progress, on_step_complete)

    def _execute_simple(
        self,
        task: str,
        device_id: str,
        on_progress: Callable[[str, int, int], None] = None,
    ) -> Tuple[bool, str]:
        """执行简单任务"""
        if on_progress:
            on_progress("直接执行简单任务", 1, 1)

        return self.phone_agent_executor(device_id, task)

    def _execute_with_workflow(
        self,
        task: str,
        device_id: str,
        workflow_id: str,
        on_progress: Callable[[str, int, int], None] = None,
        on_step_complete: Callable[[StepResult], None] = None,
    ) -> Tuple[bool, str]:
        """使用 Dify 工作流执行"""
        # 获取当前截图
        screenshot = self.screenshot_getter(device_id)

        # 准备工作流输入
        inputs = {
            "task": task,
            "device_id": device_id,
            "screenshot": screenshot or "",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 创建上下文
        self._current_workflow = WorkflowContext(
            task_description=task,
            variables=inputs,
        )

        if on_progress:
            on_progress("启动 Dify 工作流", 0, 0)

        # 流式执行工作流
        final_result = {"success": False, "message": "工作流未完成"}

        def handle_event(event_type: str, data: Dict):
            nonlocal final_result

            if self._stop_event.is_set():
                return

            if event_type == "workflow_started":
                if on_progress:
                    on_progress("工作流已启动", 0, data.get("total_steps", 0))

            elif event_type == "node_started":
                node_title = data.get("node_title", "")
                if on_progress:
                    step = data.get("step", 0)
                    total = data.get("total_steps", 0)
                    on_progress(f"执行: {node_title}", step, total)

            elif event_type == "node_finished":
                # 检查是否需要执行 PhoneAgent 操作
                outputs = data.get("outputs", {})
                if outputs.get("action_required"):
                    instruction = outputs.get("instruction", "")
                    success, message = self.phone_agent_executor(device_id, instruction)

                    # 更新截图
                    new_screenshot = self.screenshot_getter(device_id)

                    result = StepResult(
                        success=success,
                        message=message,
                        screenshot_base64=new_screenshot or "",
                        current_app=outputs.get("expected_app", ""),
                    )

                    if on_step_complete:
                        on_step_complete(result)

            elif event_type == "workflow_finished":
                outputs = data.get("outputs", {})
                final_result = {
                    "success": outputs.get("success", True),
                    "message": outputs.get("message", "工作流完成"),
                }

            elif event_type == "error":
                final_result = {
                    "success": False,
                    "message": data.get("message", "工作流错误"),
                }

        # 执行工作流
        self.dify_client.run_workflow_streaming(
            workflow_id, inputs, handle_event
        )

        return final_result["success"], final_result["message"]

    def _execute_with_ai(
        self,
        task: str,
        device_id: str,
        on_progress: Callable[[str, int, int], None] = None,
        on_step_complete: Callable[[StepResult], None] = None,
    ) -> Tuple[bool, str]:
        """使用纯 AI 执行（无工作流模板）"""
        if on_progress:
            on_progress("使用 AI 智能执行", 0, 0)

        # 直接调用 PhoneAgent
        return self.phone_agent_executor(device_id, task)

    def stop(self):
        """停止当前执行"""
        self._stop_event.set()


# 工作流模板建议
WORKFLOW_TEMPLATES = """
=== Dify 工作流设计建议 ===

1. 刷视频工作流 (browse_video)
   节点设计：
   ├── 开始节点：接收 task, device_id, screenshot
   ├── 变量节点：解析时间要求（如"刷10分钟"→600秒）
   ├── 循环节点：
   │   ├── 截图判断：当前是否在视频App
   │   │   └── 否：发送 Launch 指令
   │   ├── 发送指令：上滑切换视频
   │   ├── 等待节点：5-10秒
   │   ├── 时间判断：是否达到目标时间
   │   │   └── 是：退出循环
   │   └── 随机互动：10%概率点赞
   └── 结束节点：返回统计信息

2. 购物工作流 (shopping)
   节点设计：
   ├── 开始节点：接收商品名称、店铺偏好
   ├── 搜索节点：
   │   ├── 打开购物App
   │   └── 搜索商品
   ├── 筛选节点：
   │   ├── 截图分析：是否有搜索结果
   │   ├── 滑动查找目标商品
   │   └── 价格/店铺筛选
   ├── 下单节点：
   │   ├── 点击商品
   │   ├── 选择规格
   │   ├── 加入购物车/立即购买
   │   └── 确认订单（不付款）
   └── 结束节点：返回订单信息

3. 发消息工作流 (send_message)
   节点设计：
   ├── 开始节点：接收联系人、消息内容
   ├── 查找联系人：
   │   ├── 打开通讯App
   │   ├── 搜索联系人
   │   └── 匹配确认
   ├── 发送消息：
   │   ├── 进入对话
   │   ├── 输入内容
   │   └── 发送确认
   └── 结束节点：返回发送状态

=== API 接口设计 ===

PhoneAgent 需要暴露以下接口供 Dify 调用：

POST /api/execute
请求：{
    "device_id": "xxx",
    "instruction": "点击屏幕中央",
    "wait_after": 2  # 执行后等待秒数
}
响应：{
    "success": true,
    "message": "已执行",
    "screenshot": "base64...",
    "current_app": "com.xxx.xxx"
}

POST /api/screenshot
请求：{"device_id": "xxx"}
响应：{
    "screenshot": "base64...",
    "width": 1080,
    "height": 1920
}

POST /api/analyze
请求：{
    "screenshot": "base64...",
    "question": "当前页面是否显示搜索结果？"
}
响应：{
    "answer": "是",
    "confidence": 0.95,
    "details": "检测到10条商品列表"
}
"""


def get_workflow_templates() -> str:
    """获取工作流模板建议"""
    return WORKFLOW_TEMPLATES
