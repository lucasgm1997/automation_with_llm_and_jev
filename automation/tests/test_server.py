import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_stdio_tool_discovery_and_invalid_run():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jev_e2e", "serve"],
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listing = await session.list_tools()
        assert [tool.name for tool in listing.tools] == ["run_counter_e2e"]
        assert listing.tools[0].outputSchema["type"] == "object"
        # Invalid arguments must fail before connecting to a device or API.
        result = await session.call_tool(
            "run_counter_e2e", {"vm_uri": "unused", "increments": 0}
        )
        assert result.isError
