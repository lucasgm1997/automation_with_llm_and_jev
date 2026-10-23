import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import jev_e2e.server as server_module
from jev_e2e.task import Condition


@pytest.mark.parametrize("options,expected", [({}, 0.6), ({"min_confidence": 0.8}, 0.8)])
async def test_tool_forwards_confidence_threshold_to_executor(
    monkeypatch, options, expected,
):
    async def fake_execute(vm_uri, *, model, task):
        assert vm_uri == "unused"
        assert task.min_confidence == expected
        return {"min_confidence": task.min_confidence}

    monkeypatch.setattr(server_module, "execute", fake_execute)
    result = await server_module.run_ui_task(
        vm_uri="unused",
        goal="Open account",
        success_conditions=[Condition(target="account.home", check="exists")],
        **options,
    )
    assert result["min_confidence"] == expected


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
        assert {tool.name for tool in listing.tools} == {
            "inspect_ui",
            "run_ui_task",
        }
        assert all(tool.outputSchema["type"] == "object" for tool in listing.tools)
        ui_tool = next(tool for tool in listing.tools if tool.name == "run_ui_task")
        threshold = ui_tool.inputSchema["properties"]["min_confidence"]
        assert threshold["type"] == "number"
        assert threshold["default"] == 0.6
        assert threshold["minimum"] == 0
        assert threshold["maximum"] == 1
        # Invalid arguments must fail before connecting to a device or API.
        result = await session.call_tool(
            "run_ui_task",
            {
                "vm_uri": "unused",
                "goal": "Open account",
                "success_conditions": [{"target": "account.home", "check": "exists"}],
                "min_confidence": 1.1,
            },
        )
        assert result.isError
