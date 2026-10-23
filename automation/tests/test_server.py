import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import jev_e2e.server as server_module
from jev_e2e.task import Condition


async def test_prepare_tool_uses_same_exclusive_lock_as_test_runs(monkeypatch):
    async def prepare(device_id, app_id, avd_name, timeout_seconds):
        assert server_module.run_lock.locked()
        assert await server_module.inspect_ui("unused") == {"status": "busy"}
        return {"status": "ready", "vm_uri": "http://127.0.0.1:51000/token=/"}

    monkeypatch.setattr(server_module, "prepare_android", prepare)
    result = await server_module.prepare_android_app("emulator-5556", "com.example.demo")
    assert result["status"] == "ready"
    assert not server_module.run_lock.locked()


@pytest.mark.parametrize("options,expected", [({}, 0.6), ({"min_confidence": 0.8}, 0.8)])
async def test_tool_forwards_confidence_threshold_to_executor(
    monkeypatch, options, expected,
):
    async def fake_execute(vm_uri, *, model, task, provider):
        assert vm_uri == "unused"
        assert provider == "jev"
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


async def test_tool_forwards_openai_provider_model_and_limits(monkeypatch):
    async def fake_execute(vm_uri, *, model, task, provider):
        assert provider == "openai"
        assert model == "gpt-6-luna"
        assert task.min_confidence == 0.55
        assert task.max_steps == 60
        return {"status": "blocked"}

    monkeypatch.setattr(server_module, "execute", fake_execute)
    result = await server_module.run_ui_task(
        vm_uri="unused", goal="Open account",
        success_conditions=[Condition(target="account.home", check="exists")],
        provider="openai", model="gpt-6-luna", min_confidence=0.55, max_steps=60,
    )
    assert result["status"] == "blocked"


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
            "prepare_android_app",
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
        provider = ui_tool.inputSchema["properties"]["provider"]
        assert provider["enum"] == ["jev", "openai"]
        assert provider["default"] == "jev"
        prepare = next(tool for tool in listing.tools if tool.name == "prepare_android_app")
        assert set(prepare.inputSchema["required"]) == {"device_id", "app_id"}
        assert prepare.inputSchema["properties"]["timeout_seconds"]["maximum"] == 300
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
        result = await session.call_tool("run_ui_task", {
            "vm_uri": "unused", "goal": "Open account",
            "success_conditions": [{"target": "account.home", "check": "exists"}],
            "provider": "unsupported",
        })
        assert result.isError
        result = await session.call_tool("prepare_android_app", {
            "device_id": "emulator-5556", "app_id": "com.example.demo", "timeout_seconds": 0,
        })
        assert result.isError
