import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

from .providers.screen_provider import ScreenProvider
from .providers.state_provider import StateProvider
from .providers.ui_provider import UIProvider


@dataclass
class UINode:
    text: str
    resource_id: str
    class_name: str
    clickable: bool
    enabled: bool
    bounds: Tuple[int, int, int, int]


@dataclass
class Observation:
    frame_id: int
    frame_ts: float
    screenshot_path: str
    screen_hash: str
    package: str
    activity: str
    is_keyboard_shown: bool
    ui_xml_path: str
    ui_nodes: List[UINode]


class ObservationBuilder:
    def __init__(
        self,
        screen_provider: ScreenProvider,
        state_provider: StateProvider,
        ui_provider: UIProvider,
        output_dir: Path,
    ) -> None:
        self.screen_provider = screen_provider
        self.state_provider = state_provider
        self.ui_provider = ui_provider
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(self) -> Observation:
        frame_id, frame_ts, image = self.screen_provider.get_frame()
        screenshot_path = self._save_screenshot(frame_id, image)
        screen_hash = self._compute_hash(image)
        state = self.state_provider.get_state()
        ui_xml_path, ui_nodes = self.ui_provider.dump_ui(self.output_dir, frame_id)
        return Observation(
            frame_id=frame_id,
            frame_ts=frame_ts,
            screenshot_path=str(screenshot_path),
            screen_hash=screen_hash,
            package=state.get("package", ""),
            activity=state.get("activity", ""),
            is_keyboard_shown=state.get("is_keyboard_shown", False),
            ui_xml_path=str(ui_xml_path),
            ui_nodes=ui_nodes,
        )

    def _save_screenshot(self, frame_id: int, image: Image.Image) -> Path:
        filename = f"frame_{frame_id}.png"
        path = self.output_dir / filename
        image.save(path)
        return path

    def _compute_hash(self, image: Image.Image) -> str:
        resized = image.convert("L").resize((8, 8))
        pixels = list(resized.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if px >= avg else "0" for px in pixels)
        return hashlib.sha256(bits.encode("utf-8")).hexdigest()

    @staticmethod
    def serialize(observation: Observation) -> str:
        return json.dumps(asdict(observation), ensure_ascii=False, indent=2)


class ObservationWaiter:
    def __init__(self, builder: ObservationBuilder, timeout_s: float = 5.0) -> None:
        self.builder = builder
        self.timeout_s = timeout_s

    def wait_new(self, previous: Optional[Observation]) -> Observation:
        start = time.time()
        while True:
            obs = self.builder.build()
            if previous is None:
                return obs
            if obs.screen_hash != previous.screen_hash or obs.activity != previous.activity:
                return obs
            if time.time() - start >= self.timeout_s:
                return obs
            time.sleep(0.3)
