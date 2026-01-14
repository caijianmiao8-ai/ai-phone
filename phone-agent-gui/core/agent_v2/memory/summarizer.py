from ..actions.action_schema import ActionSchema
from ..observation import Observation
from ..verification.verifier import VerifyResult
from .memory_store import MemoryStore


class Summarizer:
    def __init__(self, memory: MemoryStore, every_n_steps: int = 5) -> None:
        self.memory = memory
        self.every_n_steps = every_n_steps

    def maybe_summarize(
        self,
        step_id: int,
        observation: Observation,
        last_action: ActionSchema | None,
        last_verify: VerifyResult | None,
    ) -> None:
        if step_id % self.every_n_steps != 0:
            return
        action_text = last_action.action if last_action else "none"
        verify_text = "success" if last_verify and last_verify.success else "pending"
        summary = (
            f"Step {step_id}: activity={observation.activity} package={observation.package}\n"
            f"Last action={action_text} verify={verify_text}\n"
            "Next: continue task steps"
        )
        self.memory.set_summary(summary)
