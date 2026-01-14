from typing import List, Literal, Optional

from pydantic import BaseModel, Field, root_validator, validator


ActionType = Literal["tap", "swipe", "type", "back", "home", "wait", "finish"]
StrategyType = Literal["uiauto", "coord"]
RiskType = Literal["low", "medium", "high"]


class TargetSpec(BaseModel):
    strategy: StrategyType
    query: Optional[str] = None
    bounds: Optional[List[int]] = None
    coord: Optional[List[int]] = None
    confidence: float = 0.0


class ActionArgs(BaseModel):
    text: Optional[str] = None
    direction: Optional[Literal["up", "down", "left", "right"]] = None
    distance: Optional[float] = None
    duration_ms: Optional[int] = None
    wait_ms: Optional[int] = None


class ActionSchema(BaseModel):
    action: ActionType
    target: Optional[TargetSpec] = None
    args: ActionArgs = Field(default_factory=ActionArgs)
    precheck: List[str] = Field(default_factory=list)
    postcheck: List[str] = Field(default_factory=list)
    risk: RiskType = "low"
    rationale_short: str = ""

    @root_validator
    def _validate_action_requirements(cls, values):
        action = values.get("action")
        target = values.get("target")
        args = values.get("args")
        if action == "tap" and not target:
            raise ValueError("tap action requires target")
        if action == "type" and not (args and args.text):
            raise ValueError("type action requires args.text")
        if action == "swipe":
            if not (args and args.direction and args.distance is not None):
                raise ValueError("swipe action requires direction and distance")
        return values

    @validator("target")
    def _validate_target_spec(cls, value, values):
        if value is None:
            return value
        if value.strategy == "uiauto" and not value.query:
            raise ValueError("uiauto target requires query")
        if value.strategy == "coord" and not value.coord:
            raise ValueError("coord target requires coord")
        return value
