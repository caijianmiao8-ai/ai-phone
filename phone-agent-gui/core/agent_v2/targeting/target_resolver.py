from dataclasses import dataclass
from typing import Optional, Tuple

from ..observation import Observation, UINode


@dataclass
class ResolvedTarget:
    bounds: Optional[Tuple[int, int, int, int]]
    coord: Optional[Tuple[int, int]]
    confidence: float
    query: str


class TargetResolver:
    def resolve(self, observation: Observation, target_spec: dict) -> ResolvedTarget:
        strategy = target_spec.get("strategy")
        if strategy == "uiauto":
            query = target_spec.get("query", "")
            node = self._find_node(observation.ui_nodes, query)
            if node:
                return ResolvedTarget(bounds=node.bounds, coord=None, confidence=0.9, query=query)
            return ResolvedTarget(bounds=None, coord=None, confidence=0.0, query=query)
        if strategy == "coord":
            coord = target_spec.get("coord")
            return ResolvedTarget(bounds=None, coord=tuple(coord), confidence=1.0, query="coord")
        return ResolvedTarget(bounds=None, coord=None, confidence=0.0, query="")

    def _find_node(self, nodes: list[UINode], query: str) -> Optional[UINode]:
        if not query:
            return None
        parts = [part.strip() for part in query.split(" OR ")]
        for part in parts:
            key, _, value = part.partition("=")
            key = key.strip()
            value = value.strip()
            for node in nodes:
                if self._matches(node, key, value):
                    return node
        return None

    def _matches(self, node: UINode, key: str, value: str) -> bool:
        if key == "text":
            return node.text == value
        if key == "id":
            return node.resource_id == value
        if key == "class":
            return node.class_name == value
        if key == "contains":
            return value in node.text
        return False
