import argparse
import asyncio
import json
from pathlib import Path

from .android import prepare_android
from .app import execute
from .task import UITask


def main():
    parser = argparse.ArgumentParser(
        description="Semantic E2E runner for the Flutter example"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Expose the high-level MCP tool over stdio")
    prepare = commands.add_parser("prepare-android", help="Open an installed debug APK and discover its VM URI")
    prepare.add_argument("--device-id", required=True)
    prepare.add_argument("--app-id", required=True)
    prepare.add_argument("--avd-name")
    prepare.add_argument("--timeout-seconds", type=int, default=120)
    task = commands.add_parser(
        "task", help="Run a generic UI goal from a JSON task specification"
    )
    task.add_argument("--vm-uri", required=True)
    task.add_argument("--spec", type=Path, required=True)
    task.add_argument("--model", default="jev-latest")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import main as serve

        serve()
        return
    if args.command == "prepare-android":
        report = asyncio.run(prepare_android(
            args.device_id, args.app_id, args.avd_name, args.timeout_seconds,
        ))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(0 if report["status"] == "ready" else 1)
    spec = UITask.model_validate_json(args.spec.read_text())
    report = asyncio.run(execute(args.vm_uri, model=args.model, task=spec))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
