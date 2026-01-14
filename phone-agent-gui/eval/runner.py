import argparse
from collections import Counter
from pathlib import Path

from core.agent_v2.orchestrator import StepRunner


def run_all(tasks_dir: Path, trace_dir: Path) -> None:
    runner = StepRunner(trace_dir=trace_dir, memory_path=trace_dir / "memory.json")
    results = []
    for task_file in sorted(tasks_dir.glob("*.yaml")):
        result = runner.run_task(task_file)
        results.append(result)
    success_count = sum(1 for r in results if r["success"])
    failure_types = Counter()
    for result in results:
        failure_types.update(result.get("failures", []))
    avg_steps = sum(len(r["steps"]) for r in results) / max(len(results), 1)
    avg_retries = sum(r["retries"] for r in results) / max(len(results), 1)
    print("Results:")
    print(f"Success rate: {success_count}/{len(results)}")
    print(f"Average steps: {avg_steps:.2f}")
    print(f"Average retries: {avg_retries:.2f}")
    print("Failure types:")
    for failure, count in failure_types.items():
        print(f"  {failure}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent v2 eval runner")
    parser.add_argument("--tasks", default="eval/tasks", help="Tasks directory")
    parser.add_argument("--trace-dir", default="traces", help="Trace output directory")
    args = parser.parse_args()
    run_all(Path(args.tasks), Path(args.trace_dir))


if __name__ == "__main__":
    main()
