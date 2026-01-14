import io
import subprocess
import time
from dataclasses import dataclass
from typing import Tuple

from PIL import Image

from ...adb_helper import ADBHelper


@dataclass
class Frame:
    frame_id: int
    frame_ts: float
    image: Image.Image


class ScreenProvider:
    def __init__(self, adb_helper: ADBHelper | None = None) -> None:
        self.adb_helper = adb_helper or ADBHelper()
        self._frame_id = 0

    def get_frame(self) -> Tuple[int, float, Image.Image]:
        self._frame_id += 1
        frame_ts = time.time()
        adb_path = self.adb_helper.get_adb_path()
        if not adb_path:
            raise RuntimeError("ADB not available for screen capture")
        result = subprocess.run(
            [adb_path, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to capture screen: {result.stderr.decode('utf-8', 'ignore')}")
        image = Image.open(io.BytesIO(result.stdout))
        image.load()
        return self._frame_id, frame_ts, image
