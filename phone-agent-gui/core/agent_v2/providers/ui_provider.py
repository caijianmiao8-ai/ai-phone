import re
import subprocess
from pathlib import Path
from typing import List, Tuple
from xml.etree import ElementTree

from ...adb_helper import ADBHelper
from ..observation import UINode


class UIProvider:
    def __init__(self, adb_helper: ADBHelper | None = None) -> None:
        self.adb_helper = adb_helper or ADBHelper()

    def dump_ui(self, output_dir: Path, frame_id: int) -> Tuple[Path, List[UINode]]:
        adb_path = self.adb_helper.get_adb_path()
        if not adb_path:
            raise RuntimeError("ADB not available for UI dump")
        subprocess.run([adb_path, "shell", "uiautomator", "dump", "/sdcard/uidump.xml"], timeout=10)
        result = subprocess.run(
            [adb_path, "exec-out", "cat", "/sdcard/uidump.xml"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError("Failed to read ui dump")
        xml_text = result.stdout.decode("utf-8", "replace")
        xml_path = output_dir / f"ui_{frame_id}.xml"
        xml_path.write_text(xml_text, encoding="utf-8")
        nodes = self._parse_nodes(xml_text)
        return xml_path, nodes

    def _parse_nodes(self, xml_text: str) -> List[UINode]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return []
        nodes: List[UINode] = []
        for node in root.iter():
            if node.tag != "node":
                continue
            bounds = self._parse_bounds(node.attrib.get("bounds", ""))
            nodes.append(
                UINode(
                    text=node.attrib.get("text", ""),
                    resource_id=node.attrib.get("resource-id", ""),
                    class_name=node.attrib.get("class", ""),
                    clickable=node.attrib.get("clickable", "false") == "true",
                    enabled=node.attrib.get("enabled", "false") == "true",
                    bounds=bounds,
                )
            )
        return nodes

    def _parse_bounds(self, bounds_str: str) -> Tuple[int, int, int, int]:
        match = re.findall(r"\d+", bounds_str)
        if len(match) == 4:
            return tuple(int(x) for x in match)  # type: ignore[return-value]
        return (0, 0, 0, 0)
