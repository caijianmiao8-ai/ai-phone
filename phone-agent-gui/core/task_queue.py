"""
增强版任务队列管理器
支持优先级、依赖关系、并发控制、持久化
"""
import json
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.settings import get_user_data_path


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class TaskItemStatus(Enum):
    """任务项状态"""
    QUEUED = "queued"        # 排队中
    WAITING = "waiting"      # 等待依赖
    READY = "ready"          # 就绪
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 取消


@dataclass
class TaskItem:
    """队列中的任务项"""
    id: str
    task_description: str
    device_ids: List[str] = field(default_factory=list)
    priority: int = TaskPriority.NORMAL.value
    status: str = TaskItemStatus.QUEUED.value
    depends_on: List[str] = field(default_factory=list)  # 依赖的任务ID
    use_knowledge: bool = True
    parallel: bool = True  # 是否并行执行多设备
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    plan_id: Optional[str] = None  # 关联的任务计划ID
    step_index: Optional[int] = None  # 在计划中的步骤索引
    max_retries: int = 1
    retry_count: int = 0
    timeout_seconds: int = 600

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskItem":
        return cls(**data)

    def can_execute(self, completed_tasks: Dict[str, bool]) -> bool:
        """检查依赖是否满足"""
        if not self.depends_on:
            return True
        return all(
            dep_id in completed_tasks and completed_tasks[dep_id]
            for dep_id in self.depends_on
        )

    def mark_running(self):
        self.status = TaskItemStatus.RUNNING.value
        self.started_at = datetime.now().isoformat()

    def mark_completed(self, result: Dict[str, Any] = None):
        self.status = TaskItemStatus.COMPLETED.value
        self.finished_at = datetime.now().isoformat()
        self.result = result

    def mark_failed(self, error: str = ""):
        self.status = TaskItemStatus.FAILED.value
        self.finished_at = datetime.now().isoformat()
        self.error_message = error

    def mark_cancelled(self):
        self.status = TaskItemStatus.CANCELLED.value
        self.finished_at = datetime.now().isoformat()

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries


@dataclass
class QueueStatistics:
    """队列统计"""
    total_queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    waiting: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TaskQueueManager:
    """任务队列管理器"""

    def __init__(
        self,
        max_concurrent: int = 3,
        persist: bool = True,
    ):
        self.max_concurrent = max_concurrent
        self.persist = persist
        self.queue: List[TaskItem] = []  # 待执行队列
        self.running: Dict[str, TaskItem] = {}  # 正在执行的任务
        self.completed: Dict[str, TaskItem] = {}  # 已完成的任务（缓存最近100个）
        self.lock = threading.Lock()
        self.storage_path = self._get_storage_path()

        if persist:
            self._load_queue()

    def _get_storage_path(self) -> str:
        config_dir = f"{get_user_data_path()}/data"
        os.makedirs(config_dir, exist_ok=True)
        return f"{config_dir}/task_queue.json"

    def _load_queue(self):
        """从文件加载队列"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.queue = [TaskItem.from_dict(t) for t in data.get("queue", [])]
                    # 恢复时重置正在执行的任务状态
                    for task in self.queue:
                        if task.status == TaskItemStatus.RUNNING.value:
                            task.status = TaskItemStatus.QUEUED.value
        except Exception:
            self.queue = []

    def _save_queue(self):
        """保存队列到文件"""
        if not self.persist:
            return
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"queue": [t.to_dict() for t in self.queue]},
                    f,
                    ensure_ascii=False,
                    indent=2
                )
        except Exception:
            pass

    def enqueue(
        self,
        task_description: str,
        device_ids: List[str] = None,
        priority: int = TaskPriority.NORMAL.value,
        depends_on: List[str] = None,
        use_knowledge: bool = True,
        parallel: bool = True,
        plan_id: Optional[str] = None,
        step_index: Optional[int] = None,
        max_retries: int = 1,
        timeout_seconds: int = 600,
    ) -> TaskItem:
        """添加任务到队列"""
        task = TaskItem(
            id=str(uuid.uuid4()),
            task_description=task_description,
            device_ids=device_ids or [],
            priority=priority,
            depends_on=depends_on or [],
            use_knowledge=use_knowledge,
            parallel=parallel,
            plan_id=plan_id,
            step_index=step_index,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )

        with self.lock:
            self.queue.append(task)
            self._sort_queue()
            self._save_queue()

        return task

    def enqueue_batch(
        self,
        tasks: List[Dict[str, Any]],
    ) -> List[TaskItem]:
        """批量添加任务"""
        items = []
        with self.lock:
            for task_data in tasks:
                task = TaskItem(
                    id=str(uuid.uuid4()),
                    task_description=task_data.get("task_description", ""),
                    device_ids=task_data.get("device_ids", []),
                    priority=task_data.get("priority", TaskPriority.NORMAL.value),
                    depends_on=task_data.get("depends_on", []),
                    use_knowledge=task_data.get("use_knowledge", True),
                    parallel=task_data.get("parallel", True),
                    plan_id=task_data.get("plan_id"),
                    step_index=task_data.get("step_index"),
                    max_retries=task_data.get("max_retries", 1),
                    timeout_seconds=task_data.get("timeout_seconds", 600),
                )
                self.queue.append(task)
                items.append(task)

            self._sort_queue()
            self._save_queue()

        return items

    def _sort_queue(self):
        """按优先级和创建时间排序"""
        self.queue.sort(
            key=lambda t: (-t.priority, t.created_at)
        )

    def _get_completed_status(self) -> Dict[str, bool]:
        """获取已完成任务的状态映射"""
        result = {}
        for task_id, task in self.completed.items():
            result[task_id] = task.status == TaskItemStatus.COMPLETED.value
        return result

    def dequeue(self) -> Optional[TaskItem]:
        """获取下一个可执行的任务"""
        with self.lock:
            if len(self.running) >= self.max_concurrent:
                return None

            completed_status = self._get_completed_status()

            for i, task in enumerate(self.queue):
                if task.status != TaskItemStatus.QUEUED.value:
                    continue

                if task.can_execute(completed_status):
                    task.mark_running()
                    self.running[task.id] = task
                    self.queue.pop(i)
                    self._save_queue()
                    return task

        return None

    def dequeue_all_ready(self) -> List[TaskItem]:
        """获取所有可执行的任务"""
        ready_tasks = []
        with self.lock:
            available_slots = self.max_concurrent - len(self.running)
            if available_slots <= 0:
                return []

            completed_status = self._get_completed_status()
            to_remove = []

            for i, task in enumerate(self.queue):
                if len(ready_tasks) >= available_slots:
                    break

                if task.status != TaskItemStatus.QUEUED.value:
                    continue

                if task.can_execute(completed_status):
                    task.mark_running()
                    self.running[task.id] = task
                    ready_tasks.append(task)
                    to_remove.append(i)

            # 从后往前删除，避免索引问题
            for i in reversed(to_remove):
                self.queue.pop(i)

            if ready_tasks:
                self._save_queue()

        return ready_tasks

    def complete_task(
        self,
        task_id: str,
        success: bool,
        result: Dict[str, Any] = None,
        error: str = "",
    ):
        """完成任务"""
        with self.lock:
            task = self.running.pop(task_id, None)
            if not task:
                return

            if success:
                task.mark_completed(result)
            else:
                task.mark_failed(error)

            # 缓存已完成的任务
            self.completed[task.id] = task

            # 限制缓存大小
            if len(self.completed) > 100:
                oldest_id = min(self.completed.keys(), key=lambda k: self.completed[k].finished_at)
                del self.completed[oldest_id]

            self._save_queue()

    def retry_task(self, task_id: str) -> bool:
        """重试失败的任务"""
        with self.lock:
            task = self.completed.get(task_id)
            if not task or not task.can_retry():
                return False

            task.retry_count += 1
            task.status = TaskItemStatus.QUEUED.value
            task.started_at = None
            task.finished_at = None
            task.error_message = None
            task.result = None

            self.queue.append(task)
            del self.completed[task_id]
            self._sort_queue()
            self._save_queue()
            return True

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self.lock:
            # 从队列中查找
            for i, task in enumerate(self.queue):
                if task.id == task_id:
                    task.mark_cancelled()
                    self.completed[task.id] = task
                    self.queue.pop(i)
                    self._save_queue()
                    return True

            # 从运行中查找
            if task_id in self.running:
                task = self.running.pop(task_id)
                task.mark_cancelled()
                self.completed[task.id] = task
                self._save_queue()
                return True

        return False

    def cancel_all(self):
        """取消所有任务"""
        with self.lock:
            for task in self.queue:
                task.mark_cancelled()
                self.completed[task.id] = task

            for task_id, task in list(self.running.items()):
                task.mark_cancelled()
                self.completed[task.id] = task

            self.queue.clear()
            self.running.clear()
            self._save_queue()

    def get_task(self, task_id: str) -> Optional[TaskItem]:
        """获取任务"""
        with self.lock:
            # 在队列中查找
            for task in self.queue:
                if task.id == task_id:
                    return task

            # 在运行中查找
            if task_id in self.running:
                return self.running[task_id]

            # 在已完成中查找
            return self.completed.get(task_id)

    def get_queue(self) -> List[TaskItem]:
        """获取队列快照"""
        with self.lock:
            return list(self.queue)

    def get_running(self) -> List[TaskItem]:
        """获取正在运行的任务"""
        with self.lock:
            return list(self.running.values())

    def get_completed(self, limit: int = 20) -> List[TaskItem]:
        """获取已完成的任务"""
        with self.lock:
            tasks = list(self.completed.values())
            tasks.sort(key=lambda t: t.finished_at or "", reverse=True)
            return tasks[:limit]

    def get_statistics(self) -> QueueStatistics:
        """获取队列统计"""
        with self.lock:
            queued = len([t for t in self.queue if t.status == TaskItemStatus.QUEUED.value])
            waiting = len([t for t in self.queue if t.status == TaskItemStatus.WAITING.value])
            running = len(self.running)
            completed = len([t for t in self.completed.values() if t.status == TaskItemStatus.COMPLETED.value])
            failed = len([t for t in self.completed.values() if t.status == TaskItemStatus.FAILED.value])

            return QueueStatistics(
                total_queued=queued,
                running=running,
                completed=completed,
                failed=failed,
                waiting=waiting,
            )

    def get_queue_summary(self) -> str:
        """获取队列摘要文本"""
        stats = self.get_statistics()
        return (
            f"队列状态: 排队({stats.total_queued}) | "
            f"运行中({stats.running}) | "
            f"完成({stats.completed}) | "
            f"失败({stats.failed})"
        )

    def is_empty(self) -> bool:
        """检查队列是否为空"""
        with self.lock:
            return len(self.queue) == 0 and len(self.running) == 0

    def has_running_tasks(self) -> bool:
        """检查是否有正在运行的任务"""
        with self.lock:
            return len(self.running) > 0

    def clear_completed(self):
        """清理已完成的任务"""
        with self.lock:
            self.completed.clear()

    def get_plan_tasks(self, plan_id: str) -> List[TaskItem]:
        """获取指定计划的所有任务"""
        with self.lock:
            all_tasks = list(self.queue) + list(self.running.values()) + list(self.completed.values())
            return [t for t in all_tasks if t.plan_id == plan_id]

    def update_task_priority(self, task_id: str, priority: int) -> bool:
        """更新任务优先级"""
        with self.lock:
            for task in self.queue:
                if task.id == task_id:
                    task.priority = priority
                    self._sort_queue()
                    self._save_queue()
                    return True
        return False
