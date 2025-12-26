"""
助手规划模块
封装对话式规划逻辑，支持 Tool Calling，复用 OpenAI/OpenRouter 客户端
"""
import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional

from openai import OpenAI


@dataclass
class StructuredPlan:
    """AI 助手生成的结构化计划"""

    task_description: str
    target_devices: List[str] = field(default_factory=list)
    time_requirement: str = ""
    frequency: str = ""
    raw_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_description": self.task_description,
            "target_devices": self.target_devices,
            "time_requirement": self.time_requirement,
            "frequency": self.frequency,
            "raw_text": self.raw_text,
        }


@dataclass
class TaskAnalysisResult:
    """任务执行分析结果"""
    task_description: str = ""
    device_id: str = ""
    success_judgment: bool = False  # AI判断是否成功
    confidence: str = "中"  # 高/中/低
    issues_found: List[str] = field(default_factory=list)  # 发现的问题
    strategy_suggestions: List[str] = field(default_factory=list)  # 策略建议
    summary: str = ""  # 总结
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_description": self.task_description,
            "device_id": self.device_id,
            "success_judgment": self.success_judgment,
            "confidence": self.confidence,
            "issues_found": self.issues_found,
            "strategy_suggestions": self.strategy_suggestions,
            "summary": self.summary,
        }

    def to_markdown(self) -> str:
        """转换为 Markdown 格式显示"""
        status = "✅ 成功" if self.success_judgment else "❌ 失败"
        parts = [
            f"## 任务执行分析",
            f"**任务**: {self.task_description}",
            f"**设备**: {self.device_id}",
            f"**判定**: {status} (置信度: {self.confidence})",
            "",
            f"### 📝 总结",
            self.summary,
        ]
        if self.issues_found:
            parts.append("")
            parts.append("### ⚠️ 发现的问题")
            for issue in self.issues_found:
                parts.append(f"- {issue}")
        if self.strategy_suggestions:
            parts.append("")
            parts.append("### 💡 策略建议")
            for suggestion in self.strategy_suggestions:
                parts.append(f"- {suggestion}")
        return "\n".join(parts)


class ToolCallStatus(Enum):
    """工具调用状态"""
    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"


@dataclass
class ToolCallResult:
    """工具调用结果"""
    tool_name: str
    status: ToolCallStatus
    result: Any = None
    error: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> str:
        """转换为可读消息"""
        if self.status == ToolCallStatus.ERROR:
            return f"❌ {self.tool_name} 执行失败: {self.error}"
        return f"✅ {self.tool_name} 执行成功"

    def to_detailed_message(self) -> str:
        """转换为详细的可读消息，包含执行内容"""
        if self.status == ToolCallStatus.ERROR:
            return f"❌ **执行失败**: {self.error}"

        # 根据工具类型生成不同的详细信息
        if self.tool_name == "execute_task":
            task_desc = self.arguments.get("task_description", "")
            devices = self.arguments.get("device_ids") or [self.arguments.get("device_id", "")]
            devices_str = ", ".join(d for d in devices if d) or "默认设备"
            result_msg = ""
            if isinstance(self.result, dict):
                result_msg = self.result.get("message", "")
            return (
                f"✅ **任务已下发**\n\n"
                f"| 项目 | 内容 |\n"
                f"| --- | --- |\n"
                f"| 📱 发送给设备的指令 | {task_desc} |\n"
                f"| 🎯 目标设备 | {devices_str} |\n"
                f"| 📝 执行状态 | {result_msg or '已启动'} |"
            )
        elif self.tool_name == "schedule_task":
            task_desc = self.arguments.get("task_description", "")
            schedule_type = self.arguments.get("schedule_type", "")
            schedule_value = self.arguments.get("schedule_value", "")
            devices = self.arguments.get("device_ids") or []
            devices_str = ", ".join(devices) if devices else "默认设备"
            type_map = {"once": "一次性", "interval": "间隔重复", "daily": "每日定时"}
            return (
                f"✅ **定时任务已创建**\n\n"
                f"| 项目 | 内容 |\n"
                f"| --- | --- |\n"
                f"| 📱 发送给设备的指令 | {task_desc} |\n"
                f"| ⏰ 调度类型 | {type_map.get(schedule_type, schedule_type)} |\n"
                f"| 🕐 调度时间 | {schedule_value} |\n"
                f"| 🎯 目标设备 | {devices_str} |"
            )
        elif self.tool_name == "create_task_plan":
            name = self.arguments.get("name", "")
            steps = self.arguments.get("steps", [])
            result_msg = ""
            if isinstance(self.result, dict):
                result_msg = self.result.get("message", "")
            if result_msg:
                return f"✅ **任务计划已创建**: {name}\n\n{result_msg}"
            steps_text = "\n".join(f"  {i+1}. {s.get('description', '')}" for i, s in enumerate(steps))
            return f"✅ **任务计划已创建**: {name}\n\n**步骤:**\n{steps_text}"
        else:
            # 其他工具返回简单消息
            result_msg = ""
            if isinstance(self.result, dict):
                result_msg = self.result.get("message", "")
            return f"✅ **{self.tool_name}** 执行成功" + (f": {result_msg}" if result_msg else "")


@dataclass
class ChatResponse:
    """聊天响应，可能包含文本回复和/或工具调用"""
    content: str = ""
    tool_calls: List[ToolCallResult] = field(default_factory=list)
    has_tool_call: bool = False
    plan_text: str = ""
    pending_tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    def get_display_message(self) -> str:
        """获取用于显示的消息"""
        parts = []
        if self.content:
            parts.append(self.content)
        if self.plan_text:
            parts.append(self.plan_text)
        for tc in self.tool_calls:
            # 使用详细消息，清晰展示执行内容
            parts.append(tc.to_detailed_message())
        return "\n\n".join(parts) if parts else ""


# 定义可用的工具
AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_task",
            "description": "立即在指定设备上执行任务。当用户确认要执行任务时调用此函数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "给执行AI的操作指令。必须是清晰的祈使句，包含所有具体信息。例如：'打开微信，搜索联系人张三，发送消息：你好'"
                    },
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "目标设备ID列表，支持同时在多个设备上执行。优先使用该字段。"
                    },
                    "device_id": {
                        "type": "string",
                        "description": "目标设备ID（单个设备）。为兼容旧版本保留，未提供 device_ids 时使用"
                    }
                },
                "required": ["task_description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_devices",
            "description": "获取当前可用的设备列表。当用户询问有哪些设备或需要选择设备时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "查询知识库获取任务执行的参考信息。当需要了解如何执行某类任务时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询关键词，如 '微信发消息'、'淘宝购物' 等"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": "创建定时或重复执行的任务。当用户需要在特定时间或按频率执行任务时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "给执行AI的操作指令"
                    },
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "目标设备ID列表"
                    },
                    "schedule_type": {
                        "type": "string",
                        "enum": ["once", "interval", "daily"],
                        "description": "调度类型：once=一次性, interval=间隔重复, daily=每日定时"
                    },
                    "schedule_value": {
                        "type": "string",
                        "description": "调度值：once时为ISO时间，interval时为分钟数，daily时为HH:MM格式"
                    }
                },
                "required": ["task_description", "schedule_type", "schedule_value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_task_status",
            "description": "获取当前正在执行或最近执行的任务状态。当用户询问任务进度时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "设备ID，不指定则返回所有设备的任务状态"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_task_history",
            "description": "分析历史任务执行情况，识别问题模式并给出改进建议。当用户想了解任务执行情况或需要优化时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "指定设备ID进行分析，不指定则分析所有设备"
                    },
                    "task_pattern": {
                        "type": "string",
                        "description": "任务描述关键词，用于筛选特定类型的任务"
                    },
                    "time_range_hours": {
                        "type": "integer",
                        "description": "分析的时间范围（小时），默认24小时"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_execution_summary",
            "description": "获取任务执行的总结报告。当用户询问执行结果、成功率、效率等信息时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "指定设备ID，不指定则返回所有设备的汇总"
                    },
                    "include_recommendations": {
                        "type": "boolean",
                        "description": "是否包含改进建议，默认true"
                    }
                },
                "required": []
            }
        }
    }
]


class AssistantPlanner:
    """封装对话式规划，支持 Tool Calling，维护历史并输出结构化计划"""

    def __init__(self, api_base: str, api_key: str, model: str, require_confirmation: bool = False):
        self.api_base = api_base
        self.api_key = api_key
        self.model = model
        self.history: List[Dict[str, Any]] = []
        self.tool_handlers: Dict[str, Callable] = {}
        self.enable_tools = True
        self.require_confirmation = require_confirmation

        self.system_prompt = """你是 Phone Agent 的智能任务执行助手。**收到请求后直接执行，调用工具后立即告知结果。**

## 核心原则
1. **直接执行**：信息完整就调用工具，不要确认
2. **立即反馈**：调用工具后，在同一条消息中说明结果（如"已创建每日任务，明天10:50开始执行"）
3. **不要拖延**：绝对不要说"正在处理"然后等待下一轮对话

## 可用工具
1. **execute_task**: 立即执行任务
2. **schedule_task**: 创建定时任务
   - schedule_type: "once"(一次性), "interval"(间隔), "daily"(每日)
   - schedule_value: 一次性用ISO时间，间隔用分钟数，每日用"HH:MM"
3. **list_devices**: 查看设备
4. **get_task_status**: 查询状态
5. **analyze_task_history**: 分析历史任务

## 时间任务转换
用户说时间 → 转换为次数（每10秒一次）
- "刷10分钟视频" → "连续浏览约60个视频，每个约10秒"

## 正确示例
用户："帮我打开快手刷视频10分钟，每天10点50分"
你的回复：
"✅ 已创建每日定时任务：
- 时间：每天 10:50
- 内容：打开快手，浏览约60个视频，随机点赞评论
- 从明天开始执行"
[同时调用 schedule_task 工具]

## 错误示例（绝对禁止）
- ❌ "好的，我来帮你设置" → 等待用户回复
- ❌ "正在分析..." → 不给出结果
- ❌ 分多轮对话完成简单任务

## 查询类请求
用户问"任务执行得怎么样"时：
1. 调用 get_task_status 或 analyze_task_history
2. 在同一条消息中直接告诉用户结果
3. 不要说"正在查询"然后等待

## 回复要求
- 简洁明了
- 调用工具后立即说明结果
- 使用与用户相同的语言"""

        self.system_prompt_no_tools = """你是 Phone Agent 的智能任务规划助手。你的核心职责是：通过对话理解用户需求，并生成可被【执行AI】准确理解的任务指令。

## 重要概念
- **用户**：与你对话的人，用自然语言描述需求
- **执行AI（PhoneAgent）**：另一个AI，负责在手机上执行任务。它会根据你生成的任务描述来操作手机
- **你的产出**：任务描述（task_description）是给执行AI看的，不是给用户看的

## 你的职责
1. **理解需求**：通过对话了解用户想要完成什么任务
2. **收集关键信息**：主动询问执行任务所需的具体信息
3. **生成任务指令**：将用户需求转化为执行AI能准确理解的操作指令

## 任务描述的编写规范（非常重要）
生成的任务描述必须遵循以下原则：

### ✅ 正确示例
- "打开微信，搜索联系人'张三'，发送消息：明天下午3点开会"
- "打开淘宝，搜索'无线蓝牙耳机'，按销量排序，浏览前5个商品"
- "打开抖音，在搜索框输入'美食探店'，浏览10个视频"
- "打开美团外卖，搜索'肯德基'，点击进入店铺，将'香辣鸡腿堡'加入购物车"

### ❌ 错误示例（不要这样写）
- "帮你打开微信给张三发消息"（口语化，包含"帮你"等无关词汇）
- "用户想要发微信"（描述用户意图而非操作指令）
- "请在手机上操作微信"（模糊，缺少具体步骤）
- "完成发送消息的任务"（抽象，没有具体内容）

### 任务描述格式要求
1. 使用祈使句，直接描述操作步骤
2. 包含所有必要的具体信息（App名称、搜索关键词、联系人姓名、消息内容等）
3. 复杂任务按顺序描述步骤，用逗号分隔
4. 不要包含"帮你"、"请"、"用户想要"等口语化表达
5. 不要包含时间、频率等调度信息（这些在其他字段中指定）

## 对话风格
- 友好、简洁、专业
- 主动引导，一次只问一个问题
- 使用与用户相同的语言回复
- 确保收集到生成准确任务指令所需的所有信息

## 需要收集的信息
1. **具体操作**：要做什么？在哪个App？
2. **关键参数**：搜索词、联系人、消息内容、商品名称等
3. **目标设备**：在哪个设备上执行？（如有多设备）
4. **执行时间/频率**：立即执行？定时？重复？

## 可执行的任务类型
- 打开 App 并执行操作（搜索、浏览、点击等）
- 发送消息（微信、短信等）
- 购物操作（搜索商品、加购物车、下单等）
- 外卖点餐（搜索店铺、选择商品等）
- 内容浏览（刷视频、看资讯等）
- 日常操作（打卡、签到等）

请开始与用户对话，了解他们的需求，并确保收集足够的信息来生成准确的任务指令。"""

    def register_tool_handler(self, tool_name: str, handler: Callable):
        """注册工具处理函数"""
        self.tool_handlers[tool_name] = handler

    def update_config(self, api_base: str, api_key: str, model: str, require_confirmation: Optional[bool] = None):
        """更新接口配置"""
        self.api_base = api_base
        self.api_key = api_key
        self.model = model
        if require_confirmation is not None:
            self.require_confirmation = require_confirmation

    def _get_client(self) -> OpenAI:
        return OpenAI(
            base_url=self.api_base,
            api_key=self.api_key,
        )

    def start_session(self):
        """清空会话历史，开始新会话"""
        self.history = []

    def _get_language_hint(self, latest_user_msg: Optional[str]) -> str:
        """根据最近的用户消息提示模型使用相同语言"""
        if latest_user_msg:
            snippet = latest_user_msg.strip()
        else:
            snippet = ""
            for msg in reversed(self.history):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        snippet = content.strip()
                        break
        if snippet:
            sample = snippet[:120]
            return (
                "请使用与用户最近消息相同的语言回复，保持自然表达。"
                f"最近的用户内容示例: {sample}"
            )
        return "如果无法判断语言，请使用简洁的双语（中文/English）回应用户。"

    def _get_datetime_context(self) -> str:
        """获取当前日期时间上下文，用于帮助AI理解相对时间"""
        from datetime import datetime
        now = datetime.now()
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_names[now.weekday()]
        return (
            f"【当前时间】{now.strftime('%Y年%m月%d日')} {weekday} {now.strftime('%H:%M')}\n"
            f"用户说"今天"指的是{now.strftime('%Y-%m-%d')}，"明天"指的是{(now + timedelta(days=1)).strftime('%Y-%m-%d')}。\n"
            f"设置定时任务时，请使用正确的日期。"
        )

    def _execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolCallResult:
        """执行工具调用"""
        if tool_name not in self.tool_handlers:
            return ToolCallResult(
                tool_name=tool_name,
                status=ToolCallStatus.ERROR,
                error=f"未注册的工具: {tool_name}",
                arguments=arguments,
            )

        try:
            handler = self.tool_handlers[tool_name]
            result = handler(**arguments)
            is_success = True
            error_message = None

            if isinstance(result, dict):
                # 规范化工具返回，优先读取 success/message 字段
                if "success" in result:
                    is_success = bool(result.get("success"))
                error_message = result.get("message") or result.get("error")

            if not is_success:
                return ToolCallResult(
                    tool_name=tool_name,
                    status=ToolCallStatus.ERROR,
                    result=result,
                    error=error_message or "工具执行失败",
                    arguments=arguments,
                )
            return ToolCallResult(
                tool_name=tool_name,
                status=ToolCallStatus.SUCCESS,
                result=result,
                arguments=arguments,
            )
        except Exception as e:
            return ToolCallResult(
                tool_name=tool_name,
                status=ToolCallStatus.ERROR,
                error=str(e),
                arguments=arguments,
            )

    def _build_plan_text(self, tool_calls: List[Dict[str, Any]]) -> str:
        """将工具调用信息转换为可展示的计划文本"""
        if not tool_calls:
            return ""
        tasks = []
        devices = set()
        schedules = []
        tool_descriptions = []

        for call in tool_calls:
            tool_name = call.get("tool_name") or "未知工具"
            args = call.get("arguments") or {}
            tool_descriptions.append(f"{tool_name}：{json.dumps(args, ensure_ascii=False)}")

            if tool_name == "execute_task":
                task_desc = args.get("task_description")
                if task_desc:
                    tasks.append(str(task_desc))
                device_ids = args.get("device_ids") or ([] if not args.get("device_id") else [args.get("device_id")])
                devices.update(str(d) for d in device_ids if d)

            if tool_name == "schedule_task":
                task_desc = args.get("task_description")
                if task_desc:
                    tasks.append(str(task_desc))
                device_ids = args.get("device_ids") or []
                devices.update(str(d) for d in device_ids if d)
                schedule_type = args.get("schedule_type") or "once"
                schedule_value = args.get("schedule_value") or "-"
                schedules.append(f"{schedule_type}: {schedule_value}")

        device_text = ", ".join(sorted(devices)) if devices else "未指定（默认使用在线设备）"
        plan_rows = [
            "| 项 | 内容 |",
            "| --- | --- |",
            f"| 任务 | {'；'.join(tasks) if tasks else '未提供'} |",
            f"| 设备 | {device_text} |",
            f"| 调度 | {'；'.join(schedules) if schedules else '立即执行'} |",
            f"| 工具调用 | {'；'.join(tool_descriptions) if tool_descriptions else '无'} |",
            "| 操作 | 点击“确认计划并执行”后将自动完成以上步骤，无需再次确认。 |",
        ]
        return "\n".join(plan_rows)

    def chat(self, user_msg: str, context_messages: Optional[List[Dict[str, str]]] = None) -> str:
        """对话模式，返回助手回复（兼容旧接口）"""
        response = self.chat_with_tools(user_msg, context_messages)
        return response.get_display_message()

    def chat_with_tools(
        self,
        user_msg: str,
        context_messages: Optional[List[Dict[str, str]]] = None
    ) -> ChatResponse:
        """对话模式，支持工具调用，返回结构化响应"""
        if not user_msg:
            return ChatResponse(content="请先输入问题或需求。")

        # 根据是否有注册的工具处理器决定使用哪个 prompt
        use_tools = self.enable_tools and len(self.tool_handlers) > 0
        system_prompt = self.system_prompt if use_tools else self.system_prompt_no_tools

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": self._get_language_hint(user_msg)},
            {"role": "system", "content": self._get_datetime_context()},
        ]
        if context_messages:
            messages.extend(context_messages)
        messages += self.history + [{"role": "user", "content": user_msg}]

        try:
            client = self._get_client()

            # 根据是否启用工具决定调用方式
            if use_tools:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=AVAILABLE_TOOLS,
                    tool_choice="auto",
                    temperature=0.3,
                )
            else:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                )

            message = response.choices[0].message
            content = (message.content or "").strip()
            tool_calls_results = []
            pending_tool_calls: List[Dict[str, Any]] = []
            plan_text = ""

            # 处理工具调用
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                    if self.require_confirmation:
                        pending_tool_calls.append({
                            "tool_name": tool_name,
                            "arguments": arguments,
                        })
                    else:
                        result = self._execute_tool(tool_name, arguments)
                        tool_calls_results.append(result)

            if self.require_confirmation and pending_tool_calls:
                plan_text = self._build_plan_text(pending_tool_calls)
                if content:
                    content = f"{content}\n\n{plan_text}"
                else:
                    content = plan_text

            # 更新历史
            self.history.append({"role": "user", "content": user_msg})
            if content:
                self.history.append({"role": "assistant", "content": content})

            return ChatResponse(
                content=content,
                tool_calls=tool_calls_results,
                has_tool_call=len(tool_calls_results) > 0 or len(pending_tool_calls) > 0,
                plan_text=plan_text,
                pending_tool_calls=pending_tool_calls,
            )

        except Exception as e:
            error_msg = f"❌ 调用助手失败: {str(e)}"
            self.history.append({"role": "user", "content": user_msg})
            self.history.append({"role": "assistant", "content": error_msg})
            return ChatResponse(content=error_msg)

    def chat_stream(
        self,
        user_msg: str,
        context_messages: Optional[List[Dict[str, str]]] = None
    ) -> Generator[str, None, ChatResponse]:
        """流式对话，逐步返回内容，最后返回完整响应"""
        if not user_msg:
            yield "请先输入问题或需求。"
            return ChatResponse(content="请先输入问题或需求。")

        use_tools = self.enable_tools and len(self.tool_handlers) > 0
        system_prompt = self.system_prompt if use_tools else self.system_prompt_no_tools

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": self._get_language_hint(user_msg)},
            {"role": "system", "content": self._get_datetime_context()},
        ]
        if context_messages:
            messages.extend(context_messages)
        messages += self.history + [{"role": "user", "content": user_msg}]

        try:
            client = self._get_client()

            if use_tools:
                stream = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=AVAILABLE_TOOLS,
                    tool_choice="auto",
                    temperature=0.3,
                    stream=True,
                )
            else:
                stream = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    stream=True,
                )

            full_content = ""
            tool_calls_data: Dict[int, Dict[str, Any]] = {}

            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                # 处理文本内容
                if delta.content:
                    full_content += delta.content
                    yield delta.content

                # 处理工具调用（流式累积）
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_data:
                            tool_calls_data[idx] = {
                                "name": "",
                                "arguments": ""
                            }
                        if tc.function.name:
                            tool_calls_data[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_data[idx]["arguments"] += tc.function.arguments

            # 执行工具调用
            tool_calls_results = []
            pending_tool_calls: List[Dict[str, Any]] = []

            for idx in sorted(tool_calls_data.keys()):
                tc_data = tool_calls_data[idx]
                tool_name = tc_data["name"]
                try:
                    arguments = json.loads(tc_data["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                if self.require_confirmation:
                    pending_tool_calls.append({
                        "tool_name": tool_name,
                        "arguments": arguments,
                    })
                else:
                    result = self._execute_tool(tool_name, arguments)
                    tool_calls_results.append(result)
                    yield f"\n\n{result.to_detailed_message()}"

            plan_text = ""
            if self.require_confirmation and pending_tool_calls:
                plan_text = self._build_plan_text(pending_tool_calls)
                if plan_text:
                    full_content = f"{full_content}\n\n{plan_text}"
                    yield f"\n\n{plan_text}"

            # 更新历史
            self.history.append({"role": "user", "content": user_msg})
            if full_content:
                self.history.append({"role": "assistant", "content": full_content})

            return ChatResponse(
                content=full_content,
                tool_calls=tool_calls_results,
                has_tool_call=len(tool_calls_results) > 0 or len(pending_tool_calls) > 0,
                plan_text=plan_text,
                pending_tool_calls=pending_tool_calls,
            )

        except Exception as e:
            error_msg = f"❌ 调用助手失败: {str(e)}"
            yield error_msg
            self.history.append({"role": "user", "content": user_msg})
            self.history.append({"role": "assistant", "content": error_msg})
            return ChatResponse(content=error_msg)

    def summarize_plan(
        self,
        devices: List[str],
        time_requirement: str = "",
        context_messages: Optional[List[Dict[str, str]]] = None,
    ) -> StructuredPlan:
        """
        基于当前对话生成结构化计划
        返回 StructuredPlan，包含任务描述、目标设备、时间窗口/频率
        """
        prompt = (
            "请基于当前对话生成一份结构化执行计划，返回 JSON，字段包括：\n"
            "task_description: 给执行AI的操作指令（非常重要，请遵循以下规范），\n"
            "target_devices: 需执行的设备ID列表（可为空数组），\n"
            "time_requirement: 时间要求/时间窗口（字符串，可为空），\n"
            "frequency: 执行频率描述（如一次性/每2小时/每天9:00，字符串）。\n\n"
            "【task_description 编写规范】\n"
            "1. 这是给另一个AI（PhoneAgent）执行的指令，不是给用户看的\n"
            "2. 使用祈使句，直接描述操作步骤，如：'打开微信，搜索联系人张三，发送消息：你好'\n"
            "3. 包含所有具体信息：App名称、搜索关键词、联系人、消息内容等\n"
            "4. 不要使用'帮你'、'请'、'用户想要'等口语化表达\n"
            "5. 不要在 task_description 中包含时间/频率信息\n\n"
            "请只返回 JSON，不要添加额外说明。"
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "system", "content": self._get_language_hint(None)},
        ]
        if context_messages:
            messages.extend(context_messages)
        messages += self.history
        if devices:
            messages.append(
                {"role": "user", "content": f"当前用户选择的设备: {', '.join(devices)}"}
            )
        if time_requirement:
            messages.append({"role": "user", "content": f"时间要求: {time_requirement}"})

        raw_reply = ""
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
            raw_reply = (response.choices[0].message.content or "").strip()
        except Exception as e:
            raw_reply = json.dumps({"error": str(e)}, ensure_ascii=False)

        plan = self._safe_parse_plan(raw_reply, devices, time_requirement)
        return plan

    def _safe_parse_plan(
        self, raw_reply: str, fallback_devices: List[str], time_requirement: str
    ) -> StructuredPlan:
        """将模型输出解析为 StructuredPlan，异常时兜底"""
        try:
            # 尝试提取 JSON（可能被 markdown 包裹）
            reply = raw_reply.strip()
            if reply.startswith("```"):
                # 移除 markdown 代码块
                lines = reply.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.strip().startswith("```"):
                        in_block = not in_block
                        continue
                    # 只在代码块内收集内容
                    if in_block:
                        json_lines.append(line)
                reply = "\n".join(json_lines) if json_lines else reply

            # 尝试直接解析，如果失败则尝试提取 JSON 对象
            try:
                payload = json.loads(reply)
            except json.JSONDecodeError:
                # 尝试提取第一个 JSON 对象
                json_match = re.search(r'\{[\s\S]*\}', reply)
                if json_match:
                    payload = json.loads(json_match.group())
                else:
                    raise
            description = payload.get("task_description") or payload.get("summary") or "待执行任务"
            targets = payload.get("target_devices") or fallback_devices or []
            frequency = payload.get("frequency") or ""
            time_req = payload.get("time_requirement") or time_requirement or ""
            return StructuredPlan(
                task_description=str(description),
                target_devices=[str(d) for d in targets],
                time_requirement=str(time_req),
                frequency=str(frequency),
                raw_text=raw_reply,
            )
        except Exception:
            return StructuredPlan(
                task_description="任务计划生成失败，请检查配置或稍后重试。",
                target_devices=fallback_devices or [],
                time_requirement=time_requirement,
                frequency="",
                raw_text=raw_reply,
            )

    def analyze_task_execution(
        self,
        task_description: str,
        device_id: str,
        success: bool,
        steps_executed: int,
        duration_seconds: float,
        logs: List[str],
        error_message: Optional[str] = None,
    ) -> TaskAnalysisResult:
        """
        分析任务执行结果，判断是否成功完成，识别问题并给出策略建议

        Args:
            task_description: 任务描述
            device_id: 设备ID
            success: 程序判定的成功状态
            steps_executed: 执行的步骤数
            duration_seconds: 执行时长（秒）
            logs: 执行日志列表
            error_message: 错误信息（如有）

        Returns:
            TaskAnalysisResult: 分析结果
        """
        # 构建日志摘要（限制长度）
        log_text = "\n".join(logs[-50:]) if logs else "无日志"
        if len(log_text) > 3000:
            log_text = log_text[-3000:]

        duration_str = f"{int(duration_seconds // 60)}分{int(duration_seconds % 60)}秒"

        analysis_prompt = f"""请分析以下手机自动化任务的执行情况，判断任务是否真正完成，识别问题并给出改进建议。

## 任务信息
- **任务描述**: {task_description}
- **执行设备**: {device_id}
- **程序状态**: {"成功" if success else "失败"}
- **执行步数**: {steps_executed} 步
- **执行时长**: {duration_str}
- **错误信息**: {error_message or "无"}

## 执行日志
```
{log_text}
```

## 请返回 JSON 格式的分析结果
{{
    "success_judgment": true/false,  // 你判断任务是否真正完成了预期目标
    "confidence": "高/中/低",  // 判断的置信度
    "issues_found": ["问题1", "问题2"],  // 发现的问题列表
    "strategy_suggestions": ["建议1", "建议2"],  // 改进策略建议
    "summary": "简要总结任务执行情况，2-3句话"
}}

## 分析要点
1. **成功判断**: 不要只看程序状态，要根据日志判断任务是否真正达成目标
   - 例如：任务是"浏览10分钟视频"，但只执行了2分钟就结束，应判断为失败
   - 例如：任务是"发送微信消息"，但遇到登录页面没有完成，应判断为失败
2. **问题识别**:
   - 是否遇到登录/验证障碍？
   - 是否有重复无效的操作？
   - 是否正确理解了时间要求？
   - 是否因为超时或步数限制提前结束？
3. **策略建议**:
   - 如何优化任务描述使AI更准确理解？
   - 是否需要调整时间限制或步数限制？
   - 是否需要预先处理登录问题？

请只返回 JSON，不要添加其他说明。"""

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的任务执行分析师，擅长分析自动化任务的执行日志，判断任务是否成功完成，识别问题并给出改进建议。"},
                    {"role": "user", "content": analysis_prompt},
                ],
                temperature=0.2,
            )
            raw_reply = (response.choices[0].message.content or "").strip()
            return self._parse_analysis_result(
                raw_reply, task_description, device_id, success
            )
        except Exception as e:
            return TaskAnalysisResult(
                task_description=task_description,
                device_id=device_id,
                success_judgment=success,
                confidence="低",
                issues_found=[f"分析失败: {str(e)}"],
                strategy_suggestions=[],
                summary=f"无法完成分析: {str(e)}",
                raw_response="",
            )

    def _parse_analysis_result(
        self,
        raw_reply: str,
        task_description: str,
        device_id: str,
        fallback_success: bool,
    ) -> TaskAnalysisResult:
        """解析分析结果 JSON"""
        try:
            # 尝试提取 JSON
            reply = raw_reply.strip()

            # 处理 markdown 代码块包裹的情况
            if reply.startswith("```"):
                lines = reply.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.strip().startswith("```"):
                        in_block = not in_block
                        continue
                    # 只在代码块内收集内容
                    if in_block:
                        json_lines.append(line)
                reply = "\n".join(json_lines) if json_lines else reply

            # 尝试直接解析，如果失败则尝试提取 JSON 对象
            try:
                payload = json.loads(reply)
            except json.JSONDecodeError:
                # 尝试提取第一个 JSON 对象
                json_match = re.search(r'\{[\s\S]*\}', reply)
                if json_match:
                    payload = json.loads(json_match.group())
                else:
                    raise
            return TaskAnalysisResult(
                task_description=task_description,
                device_id=device_id,
                success_judgment=bool(payload.get("success_judgment", fallback_success)),
                confidence=str(payload.get("confidence", "中")),
                issues_found=list(payload.get("issues_found", [])),
                strategy_suggestions=list(payload.get("strategy_suggestions", [])),
                summary=str(payload.get("summary", "")),
                raw_response=raw_reply,
            )
        except Exception:
            return TaskAnalysisResult(
                task_description=task_description,
                device_id=device_id,
                success_judgment=fallback_success,
                confidence="低",
                issues_found=["无法解析分析结果"],
                strategy_suggestions=[],
                summary=raw_reply[:200] if raw_reply else "分析结果解析失败",
                raw_response=raw_reply,
            )
