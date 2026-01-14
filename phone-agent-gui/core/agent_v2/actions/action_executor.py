import random
import time
from typing import Tuple

from ...adb_helper import ADBHelper
from ..targeting.target_resolver import ResolvedTarget
from .action_schema import ActionSchema


class ActionExecutor:
    def __init__(self, adb_helper: ADBHelper | None = None) -> None:
        self.adb_helper = adb_helper or ADBHelper()

    def execute(self, action: ActionSchema, resolved: ResolvedTarget | None = None) -> None:
        if action.action == "tap":
            if not resolved:
                raise ValueError("tap requires resolved target")
            coord = self._resolve_coord(resolved)
            if not coord:
                raise ValueError("tap requires coord or bounds")
            self.tap(*coord)
            return
        if action.action == "swipe":
            self.swipe(action)
            return
        if action.action == "type":
            self.type_text(action.args.text or "")
            return
        if action.action == "back":
            self.back()
            return
        if action.action == "home":
            self.home()
            return
        if action.action == "wait":
            wait_ms = action.args.wait_ms or 600
            time.sleep(wait_ms / 1000)
            return
        if action.action == "finish":
            return
        raise ValueError(f"Unsupported action {action.action}")

    def tap(self, x: int, y: int) -> None:
        self._adb_run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, action: ActionSchema) -> None:
        direction = action.args.direction
        distance = action.args.distance or 0.3
        duration = action.args.duration_ms or 300
        width, height = 1080, 1920
        start_x, start_y = width // 2, height // 2
        offset = int(distance * (height if direction in {"up", "down"} else width))
        if direction == "up":
            end_x, end_y = start_x, start_y - offset
        elif direction == "down":
            end_x, end_y = start_x, start_y + offset
        elif direction == "left":
            end_x, end_y = start_x - offset, start_y
        else:
            end_x, end_y = start_x + offset, start_y
        self._adb_run([
            "shell",
            "input",
            "swipe",
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(duration),
        ])

    def type_text(self, text: str) -> None:
        escaped = text.replace(" ", "%s").replace("&", "\\&")
        self._adb_run(["shell", "input", "text", escaped])

    def back(self) -> None:
        self._adb_run(["shell", "input", "keyevent", "4"])

    def home(self) -> None:
        self._adb_run(["shell", "input", "keyevent", "3"])

    def _resolve_coord(self, resolved: ResolvedTarget) -> Tuple[int, int] | None:
        if resolved.coord:
            return resolved.coord
        if not resolved.bounds:
            return None
        l, t, r, b = resolved.bounds
        x = (l + r) // 2
        y = (t + b) // 2
        if resolved.confidence < 0.6:
            x += random.randint(-3, 3)
            y += random.randint(-3, 3)
        return x, y

    def _adb_run(self, args: list[str]) -> None:
        success, output = self.adb_helper.run_command(args)
        if not success:
            raise RuntimeError(f"ADB action failed: {output}")
