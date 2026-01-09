"""
Dify 反向连接器

解决云端 Dify 无法访问本地 API 的问题
本地主动连接 Dify，拉取任务并上报结果
"""

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum
import requests


class ConnectorMode(Enum):
    """连接模式"""
    POLLING = "polling"      # 轮询模式：定期拉取任务
    WORKFLOW = "workflow"    # 工作流模式：作为工作流的一个步骤
    CHAT = "chat"           # 对话模式：通过对话接口交互


@dataclass
class DifyConnectorConfig:
    """Dify 连接配置"""
    # Dify 服务地址
    api_base: str = "https://api.dify.ai/v1"
    api_key: str = ""

    # 连接模式
    mode: ConnectorMode = ConnectorMode.CHAT

    # 轮询间隔（秒）
    poll_interval: float = 2.0

    # 应用类型
    app_type: str = "chat"  # chat / workflow / agent

    # 超时设置
    request_timeout: int = 60

    # 会话管理
    conversation_id: str = ""
    user_id: str = "phone-agent-local"


class DifyConnector:
    """
    Dify 反向连接器

    使用方式：
    1. 在 Dify 创建一个 Chat 应用或 Agent 应用
    2. 本地程序主动调用 Dify API 进行对话
    3. Dify 返回操作指令，本地执行后上报结果
    """

    def __init__(
        self,
        config: DifyConnectorConfig,
        execute_func: Callable[[str, str], Dict[str, Any]],
        screenshot_func: Callable[[str], Optional[str]],
    ):
        """
        初始化连接器

        Args:
            config: 连接配置
            execute_func: 执行函数 (device_id, instruction) -> {"success": bool, "message": str}
            screenshot_func: 截图函数 (device_id) -> base64_string
        """
        self.config = config
        self.execute_func = execute_func
        self.screenshot_func = screenshot_func

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        })

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_device: str = ""
        self._conversation_id: str = config.conversation_id

        # 回调
        self.on_task_received: Optional[Callable[[str], None]] = None
        self.on_action_executed: Optional[Callable[[str, bool], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

    def _log(self, message: str):
        """记录日志"""
        if self.on_log:
            self.on_log(f"[DifyConnector] {message}")
        print(f"[DifyConnector] {message}")

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送请求到 Dify"""
        url = f"{self.config.api_base}{endpoint}"
        kwargs.setdefault("timeout", self.config.request_timeout)

        try:
            response = self._session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self._log(f"请求失败: {e}")
            return {"error": str(e)}

    def start_task(
        self,
        task: str,
        device_id: str,
        max_steps: int = 50,
        timeout: float = 600,
    ) -> Dict[str, Any]:
        """
        启动任务执行

        通过 Dify 对话接口，将任务发送给 Dify，
        Dify 返回操作指令，本地执行并反馈结果，
        循环直到任务完成或超时。

        Args:
            task: 任务描述
            device_id: 设备 ID
            max_steps: 最大步数
            timeout: 超时时间（秒）

        Returns:
            执行结果
        """
        self._current_device = device_id
        start_time = time.time()
        step_count = 0

        # 获取初始截图
        screenshot = self.screenshot_func(device_id)

        # 构建初始消息
        initial_message = self._build_initial_message(task, screenshot)

        self._log(f"开始任务: {task}")
        if self.on_task_received:
            self.on_task_received(task)

        # 开始对话
        response = self._send_message(initial_message, files=self._build_files(screenshot))

        while step_count < max_steps and (time.time() - start_time) < timeout:
            step_count += 1

            if "error" in response:
                self._log(f"Dify 返回错误: {response['error']}")
                break

            # 解析 Dify 的响应
            ai_response = response.get("answer", "")
            self._log(f"Dify 响应: {ai_response[:100]}...")

            # 更新会话 ID
            if response.get("conversation_id"):
                self._conversation_id = response["conversation_id"]

            # 解析操作指令
            action = self._parse_action(ai_response)

            if action.get("completed"):
                self._log("任务完成")
                return {
                    "success": True,
                    "message": action.get("summary", "任务完成"),
                    "steps": step_count
                }

            if action.get("action"):
                # 执行操作
                instruction = action["action"]
                self._log(f"执行: {instruction}")

                result = self.execute_func(device_id, instruction)
                success = result.get("success", False)

                if self.on_action_executed:
                    self.on_action_executed(instruction, success)

                # 等待一下让界面更新
                time.sleep(action.get("wait", 2))

                # 获取新截图
                screenshot = self.screenshot_func(device_id)

                # 反馈给 Dify
                feedback = self._build_feedback_message(instruction, result, screenshot)
                response = self._send_message(feedback, files=self._build_files(screenshot))
            else:
                # 没有解析到有效操作，可能是 AI 在思考
                self._log("未解析到操作，继续对话")
                response = self._send_message(
                    "请告诉我下一步应该执行什么操作？",
                    files=self._build_files(screenshot)
                )

        # 超时或达到最大步数
        return {
            "success": False,
            "message": f"任务未完成（已执行 {step_count} 步）",
            "steps": step_count
        }

    def _build_initial_message(self, task: str, screenshot: Optional[str]) -> str:
        """构建初始消息"""
        message = f"""## 任务
{task}

## 设备信息
设备 ID: {self._current_device}

## 当前屏幕
已附上当前屏幕截图，请分析屏幕内容并告诉我第一步应该执行什么操作。

## 响应格式
请用 JSON 格式回复：
```json
{{
    "thinking": "你的分析思考过程",
    "action": "具体操作指令，如：点击xxx、上滑、输入xxx",
    "wait": 等待秒数（数字）,
    "completed": false
}}
```

如果任务已完成，设置 completed 为 true 并提供 summary。
"""
        return message

    def _build_feedback_message(
        self,
        action: str,
        result: Dict[str, Any],
        screenshot: Optional[str]
    ) -> str:
        """构建反馈消息"""
        success = result.get("success", False)
        message = result.get("message", "")

        feedback = f"""## 执行结果
操作: {action}
状态: {"✅ 成功" if success else "❌ 失败"}
反馈: {message}

## 当前屏幕
已附上执行后的屏幕截图，请分析并告诉我下一步操作。

请用 JSON 格式回复：
```json
{{
    "thinking": "分析当前状态",
    "action": "下一步操作",
    "wait": 等待秒数,
    "completed": false 或 true
}}
```
"""
        return feedback

    def _build_files(self, screenshot: Optional[str]) -> List[Dict]:
        """构建文件列表（用于上传截图）"""
        if not screenshot:
            return []

        # Dify 的文件上传格式
        return [{
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": self._upload_image(screenshot)
        }]

    def _upload_image(self, base64_data: str) -> str:
        """上传图片到 Dify，返回 file_id"""
        try:
            # 解码 base64
            image_data = base64.b64decode(base64_data)

            # 上传文件
            files = {
                "file": ("screenshot.png", image_data, "image/png")
            }

            response = requests.post(
                f"{self.config.api_base}/files/upload",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                files=files,
                data={"user": self.config.user_id},
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result.get("id", "")
        except Exception as e:
            self._log(f"上传图片失败: {e}")
            return ""

    def _send_message(
        self,
        message: str,
        files: List[Dict] = None
    ) -> Dict[str, Any]:
        """发送消息到 Dify"""
        payload = {
            "inputs": {},
            "query": message,
            "response_mode": "blocking",
            "user": self.config.user_id,
        }

        if self._conversation_id:
            payload["conversation_id"] = self._conversation_id

        if files:
            payload["files"] = files

        return self._request("POST", "/chat-messages", json=payload)

    def _parse_action(self, response: str) -> Dict[str, Any]:
        """解析 AI 响应中的操作指令"""
        # 尝试提取 JSON
        import re

        # 匹配 ```json ... ``` 块
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 匹配 { ... } 块
        json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # 尝试从文本中提取操作
        action_patterns = [
            r'操作[：:]\s*(.+?)(?:\n|$)',
            r'执行[：:]\s*(.+?)(?:\n|$)',
            r'action[：:]\s*(.+?)(?:\n|$)',
            r'下一步[：:]\s*(.+?)(?:\n|$)',
        ]

        for pattern in action_patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                return {"action": match.group(1).strip()}

        # 检查是否完成
        if any(kw in response for kw in ["任务完成", "已完成", "completed", "done"]):
            return {"completed": True, "summary": response}

        return {}

    def stop(self):
        """停止连接器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)


class DifyAgentMode:
    """
    Dify Agent 模式

    将 PhoneAgent 作为 Dify Agent 的一个工具（Tool）
    需要在 Dify 中配置自定义工具
    """

    @staticmethod
    def get_tool_schema() -> Dict[str, Any]:
        """
        获取工具定义（用于在 Dify 中配置）

        在 Dify 的 Agent 应用中，添加自定义工具时使用此 schema
        """
        return {
            "name": "phone_control",
            "description": "控制手机执行操作。可以点击、滑动、输入文字、打开应用等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "要执行的操作，如：点击搜索框、上滑切换视频、输入hello、打开微信"
                    },
                    "wait_after": {
                        "type": "number",
                        "description": "操作后等待的秒数，默认2秒",
                        "default": 2
                    }
                },
                "required": ["action"]
            }
        }

    @staticmethod
    def get_webhook_handler():
        """
        获取 Webhook 处理器

        如果使用 Dify 的工具调用功能，需要提供一个 webhook 接收请求
        这需要本地有公网可访问的地址（可用内网穿透）
        """
        # 这里返回一个 FastAPI 路由处理函数
        pass


# ==================== 便捷函数 ====================

def create_dify_connector(
    api_base: str,
    api_key: str,
    execute_func: Callable,
    screenshot_func: Callable,
) -> DifyConnector:
    """
    创建 Dify 连接器

    Args:
        api_base: Dify API 地址，如 "https://api.dify.ai/v1"
        api_key: Dify 应用的 API Key
        execute_func: 执行函数
        screenshot_func: 截图函数

    Returns:
        DifyConnector 实例
    """
    config = DifyConnectorConfig(
        api_base=api_base,
        api_key=api_key,
    )
    return DifyConnector(config, execute_func, screenshot_func)


# ==================== Dify 应用配置建议 ====================

DIFY_APP_SETUP_GUIDE = """
=== Dify 应用配置指南 ===

1. 创建应用
   - 登录 Dify 控制台
   - 创建新应用，选择 "Agent" 类型
   - 选择一个支持视觉的模型（如 GPT-4V、Claude 3）

2. 配置 System Prompt
   ```
   你是一个手机操作助手。用户会给你任务和手机屏幕截图，
   你需要分析屏幕内容，决定下一步操作。

   ## 响应格式
   始终用 JSON 格式回复：
   {
       "thinking": "你的分析过程",
       "action": "具体操作指令",
       "wait": 等待秒数,
       "completed": false
   }

   ## 操作类型
   - 点击xxx：点击屏幕上的某个元素
   - 上滑/下滑/左滑/右滑：滑动屏幕
   - 输入xxx：在当前输入框输入文字
   - 打开xxx：打开某个应用
   - 返回：按返回键

   ## 注意事项
   - 仔细观察屏幕内容再决定操作
   - 如果操作失败，尝试其他方法
   - 任务完成时设置 completed: true
   ```

3. 获取 API Key
   - 在应用设置中找到 "API 访问"
   - 复制 API Key

4. 测试连接
   ```python
   from core.dify_connector import create_dify_connector

   connector = create_dify_connector(
       api_base="https://api.dify.ai/v1",  # 或你的私有部署地址
       api_key="app-xxxxx",
       execute_func=my_execute_func,
       screenshot_func=my_screenshot_func,
   )

   result = connector.start_task(
       task="打开抖音刷5分钟视频",
       device_id="192.168.1.100:5555",
   )
   ```
"""


def print_setup_guide():
    """打印配置指南"""
    print(DIFY_APP_SETUP_GUIDE)
