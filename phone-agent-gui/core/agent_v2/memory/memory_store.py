import json
from pathlib import Path
from typing import Any, Dict, Optional


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Dict[str, Any] = {
            "facts": {},
            "events": [],
            "summary": "",
        }
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_fact(self, key: str, value: Any, confidence: float, step_id: int) -> None:
        self._data["facts"][key] = {
            "value": value,
            "confidence": confidence,
            "step_id": step_id,
        }
        self._persist()

    def get_fact(self, key: str) -> Optional[Dict[str, Any]]:
        return self._data["facts"].get(key)

    def append_event(self, step_id: int, event: str) -> None:
        self._data["events"].append({"step_id": step_id, "event": event})
        self._persist()

    def set_summary(self, text: str) -> None:
        self._data["summary"] = text
        self._persist()

    def get_summary(self) -> str:
        return self._data.get("summary", "")
