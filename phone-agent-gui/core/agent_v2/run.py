import argparse
from pathlib import Path

from .orchestrator import StepRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent v2 runner")
    parser.add_argument("--task", required=True, help="Path to task yaml")
    parser.add_argument("--trace-dir", default="traces", help="Trace output directory")
    args = parser.parse_args()
    trace_dir = Path(args.trace_dir)
    runner = StepRunner(trace_dir=trace_dir, memory_path=trace_dir / "memory.json")
    result = runner.run_task(Path(args.task))
    print(result)


if __name__ == "__main__":
    main()
