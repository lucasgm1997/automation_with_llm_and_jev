import asyncio
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .app import execute

server = FastMCP("jev-flutter-e2e")
run_lock = asyncio.Lock()


@server.tool()
async def run_counter_e2e(
    vm_uri: str,
    increments: int = 3,
    policy: Literal["jev", "scripted"] = "jev",
    model: str = "jev-latest",
) -> dict[str, Any]:
    """Tap the example Flutter counter and verify its semantic value.

    Pass the Dart VM service URI from flutter run. Jev makes the decisions
    inside a bounded local loop; scripted is an explicit no-AI transport test.
    Returns status, independent assertion, timing and a local JSON trace path.
    This tool changes the counter. Do not run other UI drivers concurrently.
    """
    if run_lock.locked():
        return {"status": "busy", "reason": "This server already has an active UI run."}
    async with run_lock:
        return await execute(vm_uri, increments, policy, model)


def main():
    server.run(transport="stdio")
