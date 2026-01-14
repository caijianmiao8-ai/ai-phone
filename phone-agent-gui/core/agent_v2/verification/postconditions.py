from typing import List

from ..observation import Observation


def activity_changed(prev: Observation, now: Observation) -> bool:
    return prev.activity != now.activity


def activity_contains(now: Observation, substring: str) -> bool:
    return substring in now.activity


def ui_contains(now: Observation, field: str, value: str) -> bool:
    for node in now.ui_nodes:
        if field == "text" and value in node.text:
            return True
        if field == "id" and value == node.resource_id:
            return True
    return False


def ui_not_contains(now: Observation, field: str, value: str) -> bool:
    return not ui_contains(now, field, value)


def screen_changed(prev: Observation, now: Observation) -> bool:
    return prev.screen_hash != now.screen_hash


def evaluate_postcheck(prev: Observation, now: Observation, check: str) -> bool:
    if check == "activity_changed":
        return activity_changed(prev, now)
    if check.startswith("activity_contains:"):
        return activity_contains(now, check.split(":", 1)[1])
    if check.startswith("ui_contains:"):
        field, value = check.split(":", 1)[1].split("=", 1)
        return ui_contains(now, field, value)
    if check.startswith("ui_not_contains:"):
        field, value = check.split(":", 1)[1].split("=", 1)
        return ui_not_contains(now, field, value)
    if check == "screen_changed":
        return screen_changed(prev, now)
    return False


def summarize_failed_checks(checks: List[str], results: List[bool]) -> List[str]:
    return [check for check, passed in zip(checks, results) if not passed]
