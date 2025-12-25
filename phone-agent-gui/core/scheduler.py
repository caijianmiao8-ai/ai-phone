"""
简易调度模块
支持一次性、间隔、每日定时任务，并持久化到 config 目录
"""
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.settings import get_user_data_path


@dataclass
class JobSpec:
    id: str
    description: str
    device_ids: List[str] = field(default_factory=list)
    use_knowledge: bool = True
    rule: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    parallel: bool = True
    last_status: str = ""
    last_run: Optional[str] = None
    next_run: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SchedulerManager:
    """线程安全的调度器"""

    def __init__(self, task_executor: Callable[[JobSpec], Tuple[bool, str]], tick_seconds: int = 10):
        self.task_executor = task_executor
        self.tick_seconds = tick_seconds
        self.jobs: Dict[str, JobSpec] = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.storage_path = self._get_storage_path()

        self._load_jobs()
        self.worker = threading.Thread(target=self._run_loop, daemon=True)
        self.worker.start()

    def _get_storage_path(self) -> str:
        config_dir = f"{get_user_data_path()}/config"
        os.makedirs(config_dir, exist_ok=True)
        return f"{config_dir}/scheduled_jobs.json"

    # ---------------- 持久化 ----------------
    def _load_jobs(self):
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    job = JobSpec(**item)
                    if not job.next_run:
                        # 一次性任务已执行过（有 last_run）则不重新调度
                        rule_type = (job.rule.get("type") or "").lower()
                        if rule_type == "once" and job.last_run:
                            # 已执行的一次性任务保持禁用状态
                            job.enabled = False
                        else:
                            job.next_run = self._compute_next_run(job.rule)
                    self.jobs[job.id] = job
        except FileNotFoundError:
            return
        except Exception:
            return

    def _save_jobs(self):
        try:
            payload = [job.to_dict() for job in self.jobs.values()]
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- 业务操作 ----------------
    def add_job(self, spec: Dict[str, Any]) -> JobSpec:
        with self.lock:
            job_id = spec.get("id") or str(uuid.uuid4())
            rule = spec.get("rule", {})
            next_run = self._compute_next_run(rule)
            job = JobSpec(
                id=job_id,
                description=spec.get("description", "未命名任务"),
                device_ids=spec.get("device_ids", []),
                use_knowledge=spec.get("use_knowledge", True),
                rule=rule,
                enabled=spec.get("enabled", True),
                parallel=spec.get("parallel", True),
                last_status=spec.get("last_status", ""),
                last_run=None,
                next_run=next_run,
            )
            self.jobs[job.id] = job
            self._save_jobs()
            return job

    def remove_job(self, job_id: str) -> bool:
        with self.lock:
            if job_id in self.jobs:
                self.jobs.pop(job_id)
                self._save_jobs()
                return True
            return False

    def toggle_job(self, job_id: str, enabled: bool) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            job.enabled = enabled
            if enabled and not job.next_run:
                job.next_run = self._compute_next_run(job.rule)
            self._save_jobs()
            return True

    def list_jobs(self) -> List[JobSpec]:
        with self.lock:
            return list(self.jobs.values())

    # ---------------- 运行循环 ----------------
    def _compute_next_run(self, rule: Dict[str, Any], is_reschedule: bool = False) -> Optional[str]:
        """
        根据规则计算下次执行时间（ISO字符串）
        Args:
            rule: 调度规则
            is_reschedule: 是否是任务执行后的重新调度
        """
        try:
            now = datetime.now()
            rule_type = (rule.get("type") or "").lower()

            if rule_type == "once":
                # 一次性任务：执行后不再调度
                if is_reschedule:
                    return None
                run_at = rule.get("run_at")
                if run_at:
                    dt = datetime.fromisoformat(run_at)
                    if dt < now:
                        # 如果时间已过，立即执行（仅首次）
                        dt = now
                    return dt.isoformat()

            if rule_type == "interval":
                seconds = float(rule.get("seconds") or 0)
                if seconds <= 0 and "minutes" in rule:
                    seconds = float(rule.get("minutes") or 0) * 60
                if seconds <= 0 and "hours" in rule:
                    seconds = float(rule.get("hours") or 0) * 3600
                if seconds <= 0:
                    seconds = 60
                return (now + timedelta(seconds=seconds)).isoformat()

            if rule_type == "daily":
                time_str = rule.get("time") or "09:00"
                hour, minute = [int(x) for x in time_str.split(":")]
                dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if dt <= now:
                    dt = dt + timedelta(days=1)
                return dt.isoformat()
        except Exception:
            return None
        return None

    def _run_loop(self):
        while not self.stop_event.is_set():
            now = datetime.now()
            to_run: List[JobSpec] = []
            with self.lock:
                for job in self.jobs.values():
                    if not job.enabled or not job.next_run:
                        continue
                    try:
                        next_dt = datetime.fromisoformat(job.next_run)
                    except Exception:
                        job.next_run = self._compute_next_run(job.rule)
                        continue
                    if next_dt <= now:
                        to_run.append(job)
                        # 立即更新 next_run 防止重复触发
                        # 一次性任务设为 None，其他任务计算下次时间
                        job.next_run = self._compute_next_run(job.rule, is_reschedule=True)
                        if job.next_run is None:
                            # 一次性任务：标记为已触发，等待执行完成后禁用
                            pass
                # 保存更新后的 next_run
                if to_run:
                    self._save_jobs()

            for job in to_run:
                threading.Thread(target=self._execute_job, args=(job,), daemon=True).start()

            time.sleep(self.tick_seconds)

    def _execute_job(self, job: JobSpec):
        success = False
        message = ""
        try:
            success, message = self.task_executor(job)
        except Exception as e:
            success = False
            message = str(e)

        with self.lock:
            job.last_run = datetime.now().isoformat()
            prefix = "✅ " if success else "❌ "
            if message and (message.startswith("✅ ") or message.startswith("❌ ")):
                job.last_status = message
            else:
                job.last_status = prefix + (message or "已触发执行")
            # next_run 已在 _run_loop 中更新，这里只需处理一次性任务的禁用
            # 一次性任务执行后自动禁用，防止程序重启后重复执行
            rule_type = (job.rule.get("type") or "").lower()
            if rule_type == "once":
                job.enabled = False
            self._save_jobs()

    def shutdown(self):
        self.stop_event.set()
        if self.worker.is_alive():
            self.worker.join(timeout=1)
