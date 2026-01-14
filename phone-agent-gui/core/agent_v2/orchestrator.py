import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .actions.action_executor import ActionExecutor
from .actions.action_schema import ActionSchema
from .logging.trace_logger import TraceLogger
from .memory.checkpoint import CheckpointManager
from .memory.memory_store import MemoryStore
from .memory.summarizer import Summarizer
from .observation_builder import ObservationBuilder, ObservationWaiter
from .providers.screen_provider import ScreenProvider
from .providers.state_provider import StateProvider
from .providers.ui_provider import UIProvider
from .recovery.recovery_manager import FailureClassifier, RecoveryManager
from .targeting.target_resolver import TargetResolver
from .verification.verifier import Verifier


class StepRunner:
    def __init__(self, trace_dir: Path, memory_path: Path) -> None:
        screen_provider = ScreenProvider()
        state_provider = StateProvider()
        ui_provider = UIProvider()
        self.observation_builder = ObservationBuilder(
            screen_provider=screen_provider,
            state_provider=state_provider,
            ui_provider=ui_provider,
            output_dir=trace_dir / "observations",
        )
        self.waiter = ObservationWaiter(self.observation_builder)
        self.executor = ActionExecutor()
        self.resolver = TargetResolver()
        self.verifier = Verifier()
        self.classifier = FailureClassifier()
        self.recovery = RecoveryManager()
        self.trace_logger = TraceLogger(trace_dir, "task")
        self.memory = MemoryStore(memory_path)
        self.summarizer = Summarizer(self.memory)
        self.checkpoints = CheckpointManager(trace_dir / "checkpoints.json", self.executor, self.observation_builder)

    def run_task(self, task_path: Path, max_retries: int = 3) -> Dict[str, Any]:
        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        steps = task.get("steps", [])
        expected_package = task.get("app", "")
        obs = self.waiter.wait_new(None)
        obs = self._ensure_app(expected_package, obs)
        results = {
            "task": task.get("name", task_path.stem),
            "success": True,
            "steps": [],
            "retries": 0,
            "failures": [],
            "expected_package": expected_package,
            "current_package": obs.package,
            "current_activity": obs.activity,
        }
        for step_id, step in enumerate(steps, start=1):
            retries = 0
            while retries <= max_retries:
                action_hint = step.get("action_hint")
                action = ActionSchema(**action_hint)
                resolved = {}
                resolved_target = None
                if action.target:
                    resolved_target = self.resolver.resolve(obs, action.target.dict())
                if action.action == "tap" and not self._is_valid_tap_target(resolved_target):
                else:
                    try:
                        self.executor.execute(action, resolved_target)
                        next_obs = self.waiter.wait_new(obs)
                        verify = self.verifier.verify(obs, next_obs, step.get("postcheck", []))
                    except TargetUnresolvedError:
                        next_obs = self.waiter.wait_new(obs)
                        verify = self._target_not_found_verify()
                self.summarizer.maybe_summarize(step_id, next_obs, action, verify)
                if verify.success:
                    obs = next_obs
                    results["current_package"] = obs.package
                    results["current_activity"] = obs.activity
                    results["steps"].append({"step": step.get("name"), "success": True})
                    break
                failure = self.classifier.classify(obs, next_obs, verify.failed_checks, expected_package)
                results["failures"].append(failure.value)
                recovery_plan = self.recovery.recover(failure, next_obs, action)
                for recovery_action in recovery_plan.actions:
                    self.executor.execute(recovery_action, None)
                    time.sleep(0.5)
                retries += 1
                results["retries"] += 1
                obs = self.waiter.wait_new(next_obs)
            if retries > max_retries:
                results["success"] = False
                results["steps"].append({"step": step.get("name"), "success": False})
                break
        return results

    def _ensure_app(self, expected_package: str, obs) -> Any:
        if not expected_package:
            return obs
        if expected_package == obs.package:
            return obs
        if expected_package == "com.android.settings":
            self.executor._adb_run(["shell", "am", "start", "-a", "android.settings.SETTINGS"])
        else:
            self.executor._adb_run([
                "shell",
                "monkey",
                "-p",
                expected_package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ])
    def _is_valid_tap_target(self, resolved_target) -> bool:
        if not resolved_target:
            return False
        if resolved_target.coord:
            return True
        return bool(resolved_target.bounds)

        return self.waiter.wait_new(obs)
