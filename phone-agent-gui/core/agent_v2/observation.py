from dataclasses import dataclass
from typing import List, Tuple


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
