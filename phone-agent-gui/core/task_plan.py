"""
任务工作流模型
支持多步骤任务计划，包含依赖关系、条件执行、重试机制
"""
import json
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from config.settings import get_user_data_path


class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"      # 等待执行
    WAITING = "waiting"      # 等待依赖完成
    RUNNING = "running"      # 执行中
    SUCCESS = "success"      # 成功
    FAILED = "failed"        # 失败
    SKIPPED = "skipped"      # 跳过
    CANCELLED = "cancelled"  # 取消


class PlanStatus(Enum):
    """计划状态"""
    DRAFT = "draft"          # 草稿
    READY = "ready"          # 就绪
    RUNNING = "running"      # 执行中
    PAUSED = "paused"        # 暂停
    COMPLETED = "completed"  # 完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 取消


@dataclass
class TaskStep:
    """任务步骤"""
    id: str
    index: int                        # 步骤序号
    description: str                  # 任务描述（给PhoneAgent的指令）
    device_ids: List[str] = field(default_factory=list)  # 目标设备
    depends_on: List[int] = field(default_factory=list)  # 依赖的步骤索引
    condition: str = "always"         # 执行条件: always, on_success, on_failure
    retry_count: int = 0              # 已重试次数
    max_retries: int = 1              # 最大重试次数
    timeout_seconds: int = 300        # 超时时间
    status: str = StepStatus.PENDING.value
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    execution_record_id: Optional[str] = None  # 关联的执行记录ID

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskStep":
        return cls(**data)

    def can_execute(self, completed_steps: Dict[int, bool]) -> bool:
        """检查是否可以执行（依赖是否满足）"""
        if not self.depends_on:
            return True

        for dep_index in self.depends_on:
            if dep_index not in completed_steps:
                return False  # 依赖步骤尚未完成

            dep_success = completed_steps[dep_index]

            # 根据条件判断
            if self.condition == "on_success" and not dep_success:
                return False
            if self.condition == "on_failure" and dep_success:
                return False

        return True

    def should_skip(self, completed_steps: Dict[int, bool]) -> bool:
        """检查是否应该跳过"""
        if not self.depends_on:
            return False

        for dep_index in self.depends_on:
            if dep_index not in completed_steps:
                continue

            dep_success = completed_steps[dep_index]

            # 如果条件是 on_success 但依赖失败，跳过
            if self.condition == "on_success" and not dep_success:
                return True
            # 如果条件是 on_failure 但依赖成功，跳过
            if self.condition == "on_failure" and dep_success:
                return True

        return False

    def can_retry(self) -> bool:
        """检查是否可以重试"""
        return self.retry_count < self.max_retries

    def mark_running(self):
        """标记为执行中"""
        self.status = StepStatus.RUNNING.value
        self.started_at = datetime.now().isoformat()

    def mark_success(self):
        """标记为成功"""
        self.status = StepStatus.SUCCESS.value
        self.finished_at = datetime.now().isoformat()
        self.error_message = None

    def mark_failed(self, error: str = ""):
        """标记为失败"""
        self.status = StepStatus.FAILED.value
        self.finished_at = datetime.now().isoformat()
        self.error_message = error

    def mark_skipped(self, reason: str = ""):
        """标记为跳过"""
        self.status = StepStatus.SKIPPED.value
        self.finished_at = datetime.now().isoformat()
        self.error_message = reason

    def reset(self):
        """重置状态"""
        self.status = StepStatus.PENDING.value
        self.started_at = None
        self.finished_at = None
        self.error_message = None
        self.retry_count = 0
        self.execution_record_id = None


@dataclass
class TaskPlan:
    """任务计划（多步骤工作流）"""
    id: str
    name: str
    description: str = ""
    steps: List[TaskStep] = field(default_factory=list)
    status: str = PlanStatus.DRAFT.value
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    current_step_index: int = 0
    schedule: Optional[Dict[str, Any]] = None  # 调度规则
    parallel_execution: bool = False  # 是否并行执行无依赖的步骤
    stop_on_failure: bool = True  # 失败时是否停止
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["steps"] = [s.to_dict() if isinstance(s, TaskStep) else s for s in self.steps]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskPlan":
        steps_data = data.pop("steps", [])
        plan = cls(**data)
        plan.steps = [
            TaskStep.from_dict(s) if isinstance(s, dict) else s
            for s in steps_data
        ]
        return plan

    def add_step(
        self,
        description: str,
        device_ids: List[str] = None,
        depends_on: List[int] = None,
        condition: str = "always",
        max_retries: int = 1,
        timeout_seconds: int = 300,
    ) -> TaskStep:
        """添加步骤"""
        step = TaskStep(
            id=str(uuid.uuid4()),
            index=len(self.steps),
            description=description,
            device_ids=device_ids or [],
            depends_on=depends_on or [],
            condition=condition,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        self.steps.append(step)
        self.updated_at = datetime.now().isoformat()
        return step

    def get_step(self, index: int) -> Optional[TaskStep]:
        """获取步骤"""
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None

    def get_completed_steps(self) -> Dict[int, bool]:
        """获取已完成步骤的状态映射"""
        completed = {}
        for step in self.steps:
            if step.status == StepStatus.SUCCESS.value:
                completed[step.index] = True
            elif step.status in (StepStatus.FAILED.value, StepStatus.SKIPPED.value):
                completed[step.index] = False
        return completed

    def get_next_steps(self) -> List[TaskStep]:
        """获取下一批可执行的步骤"""
        completed = self.get_completed_steps()
        next_steps = []

        for step in self.steps:
            if step.status != StepStatus.PENDING.value:
                continue

            if step.should_skip(completed):
                step.mark_skipped("依赖条件不满足")
                continue

            if step.can_execute(completed):
                next_steps.append(step)

                # 如果不是并行执行，只返回第一个
                if not self.parallel_execution:
                    break

        return next_steps

    def is_completed(self) -> bool:
        """检查计划是否完成"""
        for step in self.steps:
            if step.status in (StepStatus.PENDING.value, StepStatus.WAITING.value, StepStatus.RUNNING.value):
                return False
        return True

    def has_failures(self) -> bool:
        """检查是否有失败的步骤"""
        return any(s.status == StepStatus.FAILED.value for s in self.steps)

    def get_progress(self) -> Dict[str, Any]:
        """获取执行进度"""
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status in (
            StepStatus.SUCCESS.value, StepStatus.FAILED.value, StepStatus.SKIPPED.value
        ))
        successful = sum(1 for s in self.steps if s.status == StepStatus.SUCCESS.value)
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED.value)
        skipped = sum(1 for s in self.steps if s.status == StepStatus.SKIPPED.value)
        running = sum(1 for s in self.steps if s.status == StepStatus.RUNNING.value)

        return {
            "total": total,
            "completed": completed,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "running": running,
            "pending": total - completed - running,
            "progress_percent": (completed / total * 100) if total > 0 else 0,
        }

    def start(self):
        """开始执行计划"""
        self.status = PlanStatus.RUNNING.value
        self.started_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

    def pause(self):
        """暂停计划"""
        self.status = PlanStatus.PAUSED.value
        self.updated_at = datetime.now().isoformat()

    def resume(self):
        """恢复计划"""
        self.status = PlanStatus.RUNNING.value
        self.updated_at = datetime.now().isoformat()

    def finish(self, success: bool = True):
        """完成计划"""
        self.status = PlanStatus.COMPLETED.value if success else PlanStatus.FAILED.value
        self.finished_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

    def cancel(self):
        """取消计划"""
        self.status = PlanStatus.CANCELLED.value
        self.finished_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        # 取消所有未完成的步骤
        for step in self.steps:
            if step.status in (StepStatus.PENDING.value, StepStatus.WAITING.value):
                step.status = StepStatus.CANCELLED.value

    def reset(self):
        """重置计划"""
        self.status = PlanStatus.DRAFT.value
        self.started_at = None
        self.finished_at = None
        self.current_step_index = 0
        for step in self.steps:
            step.reset()
        self.updated_at = datetime.now().isoformat()

    def get_summary(self) -> str:
        """获取计划摘要"""
        progress = self.get_progress()
        status_icon = {
            PlanStatus.DRAFT.value: "📝",
            PlanStatus.READY.value: "✅",
            PlanStatus.RUNNING.value: "🚀",
            PlanStatus.PAUSED.value: "⏸️",
            PlanStatus.COMPLETED.value: "✅",
            PlanStatus.FAILED.value: "❌",
            PlanStatus.CANCELLED.value: "🚫",
        }.get(self.status, "❓")

        return (
            f"{status_icon} {self.name}\n"
            f"步骤: {progress['completed']}/{progress['total']} "
            f"(成功:{progress['successful']} 失败:{progress['failed']} 跳过:{progress['skipped']})\n"
            f"进度: {progress['progress_percent']:.1f}%"
        )


class TaskPlanManager:
    """任务计划管理器"""

    def __init__(self):
        self.plans: Dict[str, TaskPlan] = {}
        self.lock = threading.Lock()
        self.storage_path = self._get_storage_path()
        self._load_plans()

    def _get_storage_path(self) -> str:
        config_dir = f"{get_user_data_path()}/data"
        os.makedirs(config_dir, exist_ok=True)
        return f"{config_dir}/task_plans.json"

    def _load_plans(self):
        """从文件加载计划"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for plan_data in data:
                        plan = TaskPlan.from_dict(plan_data)
                        self.plans[plan.id] = plan
        except Exception:
            self.plans = {}

    def _save_plans(self):
        """保存计划到文件"""
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(
                    [p.to_dict() for p in self.plans.values()],
                    f,
                    ensure_ascii=False,
                    indent=2
                )
        except Exception:
            pass

    def create_plan(
        self,
        name: str,
        description: str = "",
        steps: List[Dict[str, Any]] = None,
        schedule: Dict[str, Any] = None,
        parallel_execution: bool = False,
        stop_on_failure: bool = True,
        tags: List[str] = None,
    ) -> TaskPlan:
        """创建新计划"""
        plan = TaskPlan(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            schedule=schedule,
            parallel_execution=parallel_execution,
            stop_on_failure=stop_on_failure,
            tags=tags or [],
        )

        # 添加步骤
        if steps:
            for i, step_data in enumerate(steps):
                plan.add_step(
                    description=step_data.get("description", f"步骤 {i + 1}"),
                    device_ids=step_data.get("device_ids", []),
                    depends_on=step_data.get("depends_on", []),
                    condition=step_data.get("condition", "always"),
                    max_retries=step_data.get("max_retries", 1),
                    timeout_seconds=step_data.get("timeout_seconds", 300),
                )

        with self.lock:
            self.plans[plan.id] = plan
            self._save_plans()

        return plan

    def get_plan(self, plan_id: str) -> Optional[TaskPlan]:
        """获取计划"""
        with self.lock:
            return self.plans.get(plan_id)

    def update_plan(self, plan: TaskPlan):
        """更新计划"""
        with self.lock:
            plan.updated_at = datetime.now().isoformat()
            self.plans[plan.id] = plan
            self._save_plans()

    def delete_plan(self, plan_id: str) -> bool:
        """删除计划"""
        with self.lock:
            if plan_id in self.plans:
                del self.plans[plan_id]
                self._save_plans()
                return True
            return False

    def list_plans(
        self,
        status: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[TaskPlan]:
        """列出计划"""
        with self.lock:
            plans = list(self.plans.values())

            if status:
                plans = [p for p in plans if p.status == status]

            if tag:
                plans = [p for p in plans if tag in p.tags]

            # 按更新时间排序
            plans.sort(key=lambda p: p.updated_at, reverse=True)
            return plans

    def get_running_plans(self) -> List[TaskPlan]:
        """获取正在执行的计划"""
        return self.list_plans(status=PlanStatus.RUNNING.value)

    def get_plan_summary_list(self) -> List[Dict[str, Any]]:
        """获取计划摘要列表"""
        plans = self.list_plans()
        return [
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "steps_count": len(p.steps),
                "progress": p.get_progress(),
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in plans
        ]
