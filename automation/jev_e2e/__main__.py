import argparse
import asyncio
import json

from .app import execute


def main():
    parser = argparse.ArgumentParser(
        description="Semantic E2E runner for the Flutter example"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Expose the high-level MCP tool over stdio")
    run = commands.add_parser("run", help="Execute and save a JSON trace")
    run.add_argument("--vm-uri", required=True)
    run.add_argument("--increments", type=int, default=3)
    run.add_argument("--policy", choices=["jev", "scripted"], default="jev")
    run.add_argument("--model", default="jev-latest")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import main as serve

        serve()
        return
    report = asyncio.run(execute(args.vm_uri, args.increments, args.policy, args.model))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
