import re
from typing import Dict

from ...adb_helper import ADBHelper


class StateProvider:
    def __init__(self, adb_helper: ADBHelper | None = None) -> None:
        self.adb_helper = adb_helper or ADBHelper()

    def get_state(self) -> Dict[str, str | bool]:
        package, activity = self._get_activity()
        is_keyboard_shown = self._is_keyboard_shown()
        return {
            "package": package,
            "activity": activity,
            "is_keyboard_shown": is_keyboard_shown,
        }

    def _get_activity(self) -> tuple[str, str]:
        success, output = self.adb_helper.run_command(["shell", "dumpsys", "window", "windows"])
        if not success:
            return "", ""
        activity_match = re.search(r"mCurrentFocus=Window\{[^}]+\s([^/]+)/([^}\s]+)", output)
        if not activity_match:
            activity_match = re.search(r"mFocusedApp=AppWindowToken\{[^}]+\s([^/]+)/([^}\s]+)", output)
        if activity_match:
            return activity_match.group(1), activity_match.group(2)
        return "", ""

    def _is_keyboard_shown(self) -> bool:
        success, output = self.adb_helper.run_command(["shell", "dumpsys", "input_method"])
        if not success:
            return False
        for line in output.splitlines():
            if "mInputShown" in line or "mIsInputMethodShown" in line:
                if "true" in line.lower():
                    return True
        return False
