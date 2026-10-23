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
    serve_command = commands.add_parser("serve", help="Expose MCP over stdio or Streamable HTTP")
    serve_command.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve_command.add_argument("--host", default="127.0.0.1")
    serve_command.add_argument("--port", type=int, default=8765)
    prepare = commands.add_parser("prepare-android", help="Open an installed debug APK and discover its VM URI")
    prepare.add_argument("--device-id", required=True)
    prepare.add_argument("--app-id", required=True)
    prepare.add_argument("--avd-name")
    prepare.add_argument("--timeout-seconds", type=int, default=120)
    task = commands.add_parser(
        "task", help="Run a generic UI goal from a JSON task specification"
    )
    task.add_argument("--vm-uri")
    task.add_argument("--backend", choices=("marionette", "uiautomator2"), default="marionette")
    task.add_argument("--device-id")
    task.add_argument("--app-id")
    task.add_argument("--spec", type=Path, required=True)
    task.add_argument("--provider", choices=("jev", "openai"), default="jev")
    task.add_argument("--model", help="Default: jev-latest for Jev; gpt-6-luna for OpenAI Decisions")
    task.add_argument("--min-confidence", type=float, help="Override the JSON confidence threshold (0 to 1)")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import main as serve

        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        serve(transport=args.transport, host=args.host, port=args.port)
        return
    if args.command == "prepare-android":
        report = asyncio.run(prepare_android(
            args.device_id, args.app_id, args.avd_name, args.timeout_seconds,
        ))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(0 if report["status"] == "ready" else 1)
    data = json.loads(args.spec.read_text())
    if args.min_confidence is not None:
        data["min_confidence"] = args.min_confidence
    spec = UITask.model_validate(data)
    report = asyncio.run(execute(
        args.vm_uri, model=args.model, provider=args.provider, task=spec,
        backend=args.backend, device_id=args.device_id, app_id=args.app_id,
    ))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
