import json
from pathlib import Path
from typing import Dict

from ..actions.action_schema import ActionSchema
from ..actions.action_executor import ActionExecutor
from ..observation import ObservationBuilder, ObservationWaiter


class CheckpointManager:
    def __init__(self, path: Path, executor: ActionExecutor, builder: ObservationBuilder) -> None:
        self.path = path
        self.executor = executor
        self.builder = builder
        self.waiter = ObservationWaiter(builder)
        self._data: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_checkpoint(self, name: str, observation_signature: Dict[str, str]) -> None:
        self._data[name] = observation_signature
        self._persist()

    def restore_checkpoint(self, name: str, max_back: int = 3) -> bool:
        signature = self._data.get(name)
        if not signature:
            return False
        for _ in range(max_back):
            self.executor.execute(ActionSchema(action="back"))
            obs = self.waiter.wait_new(None)
            if signature.get("activity_contains") and signature["activity_contains"] in obs.activity:
                return True
            if signature.get("ui_contains") and any(
                signature["ui_contains"] in node.text for node in obs.ui_nodes
            ):
                return True
        if signature.get("package"):
            self._restart_app(signature["package"])
        return False

    def _restart_app(self, package: str) -> None:
        self.executor._adb_run(["shell", "am", "force-stop", package])
        self.executor._adb_run(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
