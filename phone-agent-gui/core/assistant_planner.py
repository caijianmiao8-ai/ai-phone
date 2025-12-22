"""
助手规划模块
封装对话式规划逻辑，复用 OpenAI/OpenRouter 客户端
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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


class AssistantPlanner:
    """封装对话式规划，维护历史并输出结构化计划"""

    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base
        self.api_key = api_key
        self.model = model
        self.history: List[Dict[str, str]] = []
        self.system_prompt = (
            "你是设备任务规划助手，负责将用户需求拆解为可执行任务，"
            "并标注目标设备、时间窗口和执行频率。保持回答简洁，必要时使用列表或表格。"
        )

    def update_config(self, api_base: str, api_key: str, model: str):
        """更新接口配置"""
        self.api_base = api_base
        self.api_key = api_key
        self.model = model

    def _get_client(self) -> OpenAI:
        return OpenAI(
            base_url=self.api_base,
            api_key=self.api_key,
        )

    def start_session(self):
        """清空会话历史，开始新会话"""
        self.history = []

    def chat(self, user_msg: str) -> str:
        """对话模式，返回助手回复"""
        if not user_msg:
            return "请先输入问题或需求。"

        messages = [{"role": "system", "content": self.system_prompt}] + self.history + [
            {"role": "user", "content": user_msg}
        ]

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
            )
            reply = (response.choices[0].message.content or "").strip()
        except Exception as e:
            reply = f"❌ 调用助手失败: {str(e)}"

        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def summarize_plan(self, devices: List[str], time_requirement: str = "") -> StructuredPlan:
        """
        基于当前对话生成结构化计划
        返回 StructuredPlan，包含任务描述、目标设备、时间窗口/频率
        """
        prompt = (
            "请基于当前对话生成一份结构化执行计划，返回 JSON，字段包括：\n"
            "task_description: 任务概要（中文），\n"
            "target_devices: 需执行的设备ID列表（可为空数组），\n"
            "time_requirement: 时间要求/时间窗口（字符串，可为空），\n"
            "frequency: 执行频率描述（如一次性/每2小时/每天9:00，字符串）。\n"
            "请只返回 JSON，不要添加额外说明。"
        )

        messages = [{"role": "system", "content": prompt}] + self.history
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
            payload = json.loads(raw_reply)
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
