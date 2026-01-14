from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator, validator


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

    @model_validator(mode="after")
    def _validate_action_requirements(self):
        if self.action == "tap" and not self.target:
            raise ValueError("tap action requires target")
        if self.action == "type" and not self.args.text:
            raise ValueError("type action requires args.text")
        if self.action == "swipe":
            if not (self.args.direction and self.args.distance is not None):
                raise ValueError("swipe action requires direction and distance")
        return self

    @validator("target")
    def _validate_target_spec(cls, value, values):
        if value is None:
            return value
        if value.strategy == "uiauto" and not value.query:
            raise ValueError("uiauto target requires query")
        if value.strategy == "coord" and not value.coord:
            raise ValueError("coord target requires coord")
        return value
