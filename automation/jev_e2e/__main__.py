import argparse
import asyncio
import json
from pathlib import Path

from .app import execute
from .task import UITask


def main():
    parser = argparse.ArgumentParser(
        description="Semantic E2E runner for the Flutter example"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Expose the high-level MCP tool over stdio")
    task = commands.add_parser(
        "task", help="Run a generic UI goal from a JSON task specification"
    )
    task.add_argument("--vm-uri", required=True)
    task.add_argument("--spec", type=Path, required=True)
    task.add_argument("--model", default="jev-latest")
    run = commands.add_parser("run", help="Legacy counter smoke test")
    run.add_argument("--vm-uri", required=True)
    run.add_argument("--increments", type=int, default=3)
    run.add_argument("--policy", choices=["jev", "scripted"], default="jev")
    run.add_argument("--model", default="jev-latest")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import main as serve

        serve()
        return
    if args.command == "task":
        spec = UITask.model_validate_json(args.spec.read_text())
        report = asyncio.run(execute(args.vm_uri, model=args.model, task=spec))
    else:
        report = asyncio.run(
            execute(args.vm_uri, args.increments, args.policy, args.model)
        )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
