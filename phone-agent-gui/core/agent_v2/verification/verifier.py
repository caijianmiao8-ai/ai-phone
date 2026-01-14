from dataclasses import dataclass
from typing import Dict, List

from .postconditions import evaluate_postcheck, summarize_failed_checks
from ..observation import Observation


@dataclass
class VerifyResult:
    success: bool
    failed_checks: List[str]
    details: Dict[str, bool]


class Verifier:
    def verify(self, prev_obs: Observation, now_obs: Observation, postchecks: List[str]) -> VerifyResult:
        results = [evaluate_postcheck(prev_obs, now_obs, check) for check in postchecks]
        failed = summarize_failed_checks(postchecks, results)
        details = {check: result for check, result in zip(postchecks, results)}
        return VerifyResult(success=not failed, failed_checks=failed, details=details)
