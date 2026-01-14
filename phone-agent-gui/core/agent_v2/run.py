import argparse
from pathlib import Path

from .orchestrator import StepRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent v2 runner")
    parser.add_argument("--task", required=True, help="Path to task yaml")
    parser.add_argument("--trace-dir", default="traces", help="Trace output directory")
    args = parser.parse_args()
    trace_dir = Path(args.trace_dir)
    try:
        runner = StepRunner(trace_dir=trace_dir, memory_path=trace_dir / "memory.json")
        result = runner.run_task(Path(args.task))
        print(
            {
                "task": result.get("task"),
                "success": result.get("success"),
                "current_package": result.get("current_package"),
                "current_activity": result.get("current_activity"),
                "expected_package": result.get("expected_package"),
                "error": result.get("error"),
            }
        )
    except Exception as exc:
        print({"error": str(exc)})
        raise
    finally:
        print(f"trace_dir={trace_dir}")


if __name__ == "__main__":
    main()
