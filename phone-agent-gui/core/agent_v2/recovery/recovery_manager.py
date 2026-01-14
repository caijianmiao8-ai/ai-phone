from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from ..actions.action_schema import ActionSchema, ActionArgs, TargetSpec
from ..observation import Observation


class FailureType(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    WRONG_PAGE = "WRONG_PAGE"
    POPUP_BLOCK = "POPUP_BLOCK"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    STATE_LOST = "STATE_LOST"


@dataclass
class RecoveryPlan:
    actions: List[ActionSchema]
    reason: str


class FailureClassifier:
    popup_keywords = ["允许", "Allow", "以后再说", "稍后", "更新", "Skip", "X", "同意", "Agree", "关闭", "Later"]
    state_lost_keywords = ["登录", "Sign in", "网络错误", "重新连接"]

    def classify(
        self,
        prev: Observation,
        now: Observation,
        failed_checks: List[str],
        expected_package: str | None = None,
    ) -> FailureType:
        if prev.screen_hash == now.screen_hash and prev.activity == now.activity:
            return FailureType.NO_CHANGE
        if expected_package and now.package and now.package != expected_package:
            return FailureType.WRONG_PAGE
        if self._contains_keywords(now, self.popup_keywords):
            return FailureType.POPUP_BLOCK
        if self._contains_keywords(now, self.state_lost_keywords):
            return FailureType.STATE_LOST
        if any("ui_contains" in check for check in failed_checks):
            return FailureType.TARGET_NOT_FOUND
        return FailureType.TARGET_NOT_FOUND

    def _contains_keywords(self, observation: Observation, keywords: List[str]) -> bool:
        for node in observation.ui_nodes:
            for keyword in keywords:
                if keyword in node.text:
                    return True
        return False


class RecoveryManager:
    def recover(self, failure: FailureType, observation: Observation, last_action: Optional[ActionSchema]) -> RecoveryPlan:
        if failure == FailureType.NO_CHANGE:
            actions = [ActionSchema(action="wait", args=ActionArgs(wait_ms=600))]
            if last_action and last_action.action == "tap":
                actions.append(last_action)
            actions.append(ActionSchema(action="back"))
            return RecoveryPlan(actions=actions, reason="No change detected")
        if failure == FailureType.POPUP_BLOCK:
            for keyword in FailureClassifier.popup_keywords:
                for node in observation.ui_nodes:
                    if keyword in node.text:
                        target = TargetSpec(strategy="uiauto", query=f"contains={keyword}")
                        return RecoveryPlan(
                            actions=[ActionSchema(action="tap", target=target)],
                            reason="Popup detected",
                        )
            return RecoveryPlan(actions=[ActionSchema(action="back")], reason="Popup fallback")
        if failure == FailureType.TARGET_NOT_FOUND:
            actions = [
                ActionSchema(action="swipe", args=ActionArgs(direction="down", distance=0.4)),
                ActionSchema(action="swipe", args=ActionArgs(direction="up", distance=0.4)),
            ]
            return RecoveryPlan(actions=actions, reason="Scroll to find target")
        if failure == FailureType.WRONG_PAGE:
            actions = [ActionSchema(action="back"), ActionSchema(action="back")]
            return RecoveryPlan(actions=actions, reason="Wrong page recovery")
        if failure == FailureType.STATE_LOST:
            actions = [ActionSchema(action="home"), ActionSchema(action="back")]
            return RecoveryPlan(actions=actions, reason="State lost recovery")
        return RecoveryPlan(actions=[], reason="No recovery")
