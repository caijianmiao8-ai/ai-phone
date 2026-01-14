import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from ..actions.action_schema import ActionSchema
from ..observation import Observation
from ..verification.verifier import VerifyResult


class TraceLogger:
    def __init__(self, base_dir: Path, task_name: str) -> None:
        self.task_dir = base_dir / task_name
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.step_id = 0

    def log_step(
        self,
        obs_before: Observation,
        obs_after: Observation,
        action: ActionSchema,
        resolved: dict[str, Any],
        verify: VerifyResult,
        failure: Optional[dict[str, Any]] = None,
        llm_raw: Optional[str] = None,
    ) -> None:
        self.step_id += 1
        step_dir = self.task_dir / f"step_{self.step_id}"
        step_dir.mkdir(parents=True, exist_ok=True)
        self._copy(obs_before.screenshot_path, step_dir / "before.png")
        self._copy(obs_after.screenshot_path, step_dir / "after.png")
        self._copy(obs_before.ui_xml_path, step_dir / "ui_before.xml")
        self._copy(obs_after.ui_xml_path, step_dir / "ui_after.xml")
        (step_dir / "obs_before.json").write_text(
            json.dumps(asdict(obs_before), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (step_dir / "obs_after.json").write_text(
            json.dumps(asdict(obs_after), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (step_dir / "action.json").write_text(
            json.dumps({"action": action.dict(), "resolved": resolved}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (step_dir / "verify.json").write_text(
            json.dumps(asdict(verify), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if failure:
            (step_dir / "failure.json").write_text(
                json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if llm_raw:
            (step_dir / "llm_raw.txt").write_text(llm_raw, encoding="utf-8")

    def _copy(self, source: str, dest: Path) -> None:
        shutil.copy(source, dest)
