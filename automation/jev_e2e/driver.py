"""A persistent MCP session to Marionette; no process startup per gesture."""

import json
import os
import shutil
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def websocket_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
        raise ValueError("Use the Dart VM service URI printed by flutter run.")
    path = parsed.path.rstrip("/")
    if not path.endswith("/ws"):
        path += "/ws"
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme, parsed.scheme)
    return urlunsplit((scheme, parsed.netloc, path, parsed.query, ""))


def dart_binary() -> str:
    local = Path(__file__).resolve().parents[2] / ".fvm/flutter_sdk/bin/dart"
    return os.environ.get("DART_BIN") or (
        str(local) if local.exists() else shutil.which("dart") or "dart"
    )


class Marionette:
    def __init__(self, session: ClientSession):
        self.session = session

    async def call(self, tool: str, args: dict) -> str:
        result = await self.session.call_tool(tool, args)
        text = "\n".join(item.text for item in result.content if item.type == "text")
        if result.isError:
            # Errors may contain VM URLs or application data: don't copy raw
            # transport messages into the report returned to an outer agent.
            raise RuntimeError(f"Marionette tool {tool!r} failed.")
        return text

    async def snapshot(self) -> dict:
        raw = await self.call("call_custom_extension", {"extension": "e2e_snapshot"})
        response = json.loads(raw)
        if response.get("status") != "Success":
            raise RuntimeError("Semantic snapshot extension failed.")
        return {
            "schema_version": response["schema_version"],
            "nodes": response["nodes"],
        }

    async def tap(self, key: str) -> None:
        await self.call("tap", {"key": key})


@asynccontextmanager
async def connect(uri: str, dart: str | None = None):
    params = StdioServerParameters(
        command=dart or dart_binary(), args=["pub", "global", "run", "marionette_mcp"]
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=15)
        ) as session,
    ):
        await session.initialize()
        driver = Marionette(session)
        await driver.call("connect", {"uri": websocket_uri(uri)})
        try:
            yield driver
        finally:
            # Close the VM WebSocket before closing stdio so the Dart process
            # can exit immediately instead of waiting for a forced termination.
            await driver.call("disconnect", {})
