import argparse
from pathlib import Path


def list_steps(trace_dir: Path) -> None:
    for step_dir in sorted(trace_dir.glob("step_*")):
        action_path = step_dir / "action.json"
        verify_path = step_dir / "verify.json"
        failure_path = step_dir / "failure.json"
        print(f"{step_dir.name}:")
        print(f"  action: {action_path}")
        print(f"  verify: {verify_path}")
        if failure_path.exists():
            print(f"  failure: {failure_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay trace steps")
    parser.add_argument("trace_dir", help="Trace directory")
    args = parser.parse_args()
    list_steps(Path(args.trace_dir))


if __name__ == "__main__":
    main()
