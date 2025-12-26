"""
任务执行历史记录模块
持久化存储任务执行记录，支持查询和统计分析
"""
import json
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config.settings import get_user_data_path


@dataclass
class TaskExecutionRecord:
    """任务执行记录"""
    id: str
    task_description: str
    device_id: str
    started_at: str
    finished_at: Optional[str] = None
    duration_seconds: float = 0.0
    success: bool = False
    steps_executed: int = 0
    max_steps: int = 50
    error_message: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    final_status: str = ""
    knowledge_used: Optional[str] = None
    plan_id: Optional[str] = None  # 关联的任务计划ID
    step_index: Optional[int] = None  # 在任务计划中的步骤索引

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskExecutionRecord":
        return cls(**data)

    def finish(self, success: bool, message: str = "", steps: int = 0):
        """标记任务完成"""
        self.finished_at = datetime.now().isoformat()
        self.success = success
        self.final_status = message
        self.steps_executed = steps
        if self.started_at:
            try:
                start = datetime.fromisoformat(self.started_at)
                end = datetime.fromisoformat(self.finished_at)
                self.duration_seconds = (end - start).total_seconds()
            except Exception:
                pass


@dataclass
class TaskStatistics:
    """任务统计数据"""
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    success_rate: float = 0.0
    average_duration: float = 0.0
    average_steps: float = 0.0
    total_duration: float = 0.0
    most_common_errors: List[Dict[str, Any]] = field(default_factory=list)
    tasks_by_device: Dict[str, int] = field(default_factory=dict)
    tasks_by_day: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TaskHistoryManager:
    """任务执行历史管理器"""

    def __init__(self, max_records: int = 1000):
        self.max_records = max_records
        self.records: List[TaskExecutionRecord] = []
        self.lock = threading.Lock()
        self.storage_path = self._get_storage_path()
        self._load_records()

    def _get_storage_path(self) -> str:
        config_dir = f"{get_user_data_path()}/data"
        os.makedirs(config_dir, exist_ok=True)
        return f"{config_dir}/task_history.json"

    def _load_records(self):
        """从文件加载历史记录"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.records = [TaskExecutionRecord.from_dict(r) for r in data]
        except Exception:
            self.records = []

    def _save_records(self):
        """保存历史记录到文件"""
        try:
            # 只保留最近的记录
            if len(self.records) > self.max_records:
                self.records = self.records[-self.max_records:]

            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump([r.to_dict() for r in self.records], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def create_record(
        self,
        task_description: str,
        device_id: str,
        plan_id: Optional[str] = None,
        step_index: Optional[int] = None,
        max_steps: int = 50,
    ) -> TaskExecutionRecord:
        """创建新的执行记录"""
        record = TaskExecutionRecord(
            id=str(uuid.uuid4()),
            task_description=task_description,
            device_id=device_id,
            started_at=datetime.now().isoformat(),
            plan_id=plan_id,
            step_index=step_index,
            max_steps=max_steps,
        )
        with self.lock:
            self.records.append(record)
            self._save_records()
        return record

    def update_record(self, record: TaskExecutionRecord):
        """更新执行记录"""
        with self.lock:
            for i, r in enumerate(self.records):
                if r.id == record.id:
                    self.records[i] = record
                    break
            self._save_records()

    def add_log(self, record_id: str, message: str):
        """添加日志到记录"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            for r in self.records:
                if r.id == record_id:
                    r.logs.append(f"[{timestamp}] {message}")
                    # 限制日志数量
                    if len(r.logs) > 200:
                        r.logs = r.logs[-200:]
                    break
            self._save_records()

    def finish_record(
        self,
        record_id: str,
        success: bool,
        message: str = "",
        steps: int = 0,
        error: Optional[str] = None,
    ):
        """完成执行记录"""
        with self.lock:
            for r in self.records:
                if r.id == record_id:
                    r.finish(success, message, steps)
                    if error:
                        r.error_message = error
                    break
            self._save_records()

    def get_record(self, record_id: str) -> Optional[TaskExecutionRecord]:
        """获取单条记录"""
        with self.lock:
            for r in self.records:
                if r.id == record_id:
                    return r
        return None

    def get_records_by_device(
        self,
        device_id: str,
        limit: int = 50,
    ) -> List[TaskExecutionRecord]:
        """获取指定设备的执行记录"""
        with self.lock:
            filtered = [r for r in self.records if r.device_id == device_id]
            return filtered[-limit:]

    def get_records_by_plan(self, plan_id: str) -> List[TaskExecutionRecord]:
        """获取指定计划的所有执行记录"""
        with self.lock:
            return [r for r in self.records if r.plan_id == plan_id]

    def get_recent_records(
        self,
        limit: int = 50,
        device_id: Optional[str] = None,
        success_only: Optional[bool] = None,
        time_range_hours: Optional[int] = None,
    ) -> List[TaskExecutionRecord]:
        """获取最近的执行记录"""
        with self.lock:
            filtered = list(self.records)

            if device_id:
                filtered = [r for r in filtered if r.device_id == device_id]

            if success_only is not None:
                filtered = [r for r in filtered if r.success == success_only]

            if time_range_hours:
                cutoff = datetime.now() - timedelta(hours=time_range_hours)
                cutoff_str = cutoff.isoformat()
                filtered = [r for r in filtered if r.started_at >= cutoff_str]

            return filtered[-limit:]

    def search_records(
        self,
        keyword: str,
        limit: int = 50,
    ) -> List[TaskExecutionRecord]:
        """搜索执行记录"""
        keyword = keyword.lower()
        with self.lock:
            filtered = [
                r for r in self.records
                if keyword in r.task_description.lower()
                or keyword in (r.error_message or "").lower()
            ]
            return filtered[-limit:]

    def get_statistics(
        self,
        device_id: Optional[str] = None,
        time_range_hours: Optional[int] = None,
    ) -> TaskStatistics:
        """获取统计数据"""
        records = self.get_recent_records(
            limit=1000,
            device_id=device_id,
            time_range_hours=time_range_hours,
        )

        if not records:
            return TaskStatistics()

        total = len(records)
        successful = sum(1 for r in records if r.success)
        failed = total - successful

        # 计算平均值
        durations = [r.duration_seconds for r in records if r.duration_seconds > 0]
        steps = [r.steps_executed for r in records if r.steps_executed > 0]

        avg_duration = sum(durations) / len(durations) if durations else 0
        avg_steps = sum(steps) / len(steps) if steps else 0

        # 统计错误
        error_counts: Dict[str, int] = {}
        for r in records:
            if r.error_message:
                # 简化错误消息作为key
                key = r.error_message[:100]
                error_counts[key] = error_counts.get(key, 0) + 1

        most_common_errors = [
            {"error": k, "count": v}
            for k, v in sorted(error_counts.items(), key=lambda x: -x[1])[:5]
        ]

        # 按设备统计
        tasks_by_device: Dict[str, int] = {}
        for r in records:
            tasks_by_device[r.device_id] = tasks_by_device.get(r.device_id, 0) + 1

        # 按日期统计
        tasks_by_day: Dict[str, int] = {}
        for r in records:
            try:
                day = r.started_at[:10]  # YYYY-MM-DD
                tasks_by_day[day] = tasks_by_day.get(day, 0) + 1
            except Exception:
                pass

        return TaskStatistics(
            total_tasks=total,
            successful_tasks=successful,
            failed_tasks=failed,
            success_rate=successful / total if total > 0 else 0,
            average_duration=avg_duration,
            average_steps=avg_steps,
            total_duration=sum(durations),
            most_common_errors=most_common_errors,
            tasks_by_device=tasks_by_device,
            tasks_by_day=tasks_by_day,
        )

    def clear_old_records(self, days: int = 30):
        """清理旧记录"""
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        with self.lock:
            self.records = [r for r in self.records if r.started_at >= cutoff_str]
            self._save_records()

    def export_records(
        self,
        limit: int = 100,
        device_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """导出记录为字典列表"""
        records = self.get_recent_records(limit=limit, device_id=device_id)
        return [r.to_dict() for r in records]
