import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from jev_e2e.driver import Marionette
from jev_e2e import driver as driver_module
from jev_e2e.semantics import RunStopped, validate_snapshot


@pytest.mark.parametrize("binary,command,args", [
    (None, "/local/dart", ["pub", "global", "run", "marionette_mcp"]),
    ("/usr/local/bin/marionette_mcp", "/usr/local/bin/marionette_mcp", []),
])
async def test_connection_supports_native_binary_and_keeps_cleanup(monkeypatch, binary, command, args):
    calls = []
    if binary:
        monkeypatch.setenv("MARIONETTE_BIN", binary)
    else:
        monkeypatch.delenv("MARIONETTE_BIN", raising=False)

    @asynccontextmanager
    async def stdio(params):
        assert params.command == command and params.args == args
        yield None, None

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append("closed")

        async def initialize(self):
            calls.append("initialized")

    async def call(self, tool, arguments):
        calls.append((tool, arguments))

    monkeypatch.setattr(driver_module, "stdio_client", stdio)
    monkeypatch.setattr(driver_module, "ClientSession", Session)
    monkeypatch.setattr(Marionette, "call", call)
    uri = "http://host.docker.internal:44037/token=/"
    async with driver_module.connect(uri, dart="/local/dart"):
        pass
    assert calls == [
        "initialized", ("connect", {"uri": "ws://host.docker.internal:44037/token=/ws"}),
        ("disconnect", {}), "closed",
    ]


class RecordingDriver(Marionette):
    def __init__(self, focused=True):
        super().__init__(None)
        self.calls = []
        self.focused = focused

    async def call(self, tool, args):
        self.calls.append((tool, args))
        return json.dumps({"status": "Success", "performed": True})

    async def snapshot(self):
        return {
            "schema_version": 2,
            "nodes": [
                {
                    "id": "login.email",
                    "role": "textField",
                    "enabled": True,
                    "focused": self.focused,
                    "actions": ["fill"],
                }
            ],
        }


async def test_actions_use_semantic_id_and_focused_input_without_keys():
    driver = RecordingDriver()
    await driver.tap("login.submit")
    await driver.fill("login.email", "local@example.test")
    assert driver.calls == [
        (
            "call_custom_extension",
            {
                "extension": "e2e_action",
                "args": {"identifier": "login.submit", "operation": "tap"},
            },
        ),
        (
            "call_custom_extension",
            {
                "extension": "e2e_action",
                "args": {"identifier": "login.email", "operation": "focus"},
            },
        ),
        ("enter_text", {"focused_element": True, "input": "local@example.test"}),
    ]


async def test_wrong_focus_never_receives_input(monkeypatch):
    timeout = asyncio.timeout
    monkeypatch.setattr("jev_e2e.driver.asyncio.timeout", lambda _: timeout(0.01))
    driver = RecordingDriver(focused=False)
    with pytest.raises(RunStopped, match="acquire focus"):
        await driver.fill("login.email", "must-not-type")
    assert all(tool != "enter_text" for tool, _ in driver.calls)


async def test_failed_semantic_action_never_types():
    class RejectedDriver(RecordingDriver):
        async def call(self, tool, args):
            self.calls.append((tool, args))
            return json.dumps({"status": "Error"})

    driver = RejectedDriver()
    with pytest.raises(RuntimeError, match="Semantic interaction failed"):
        await driver.fill("login.email", "must-not-type")
    assert len(driver.calls) == 1


def test_old_instrumentation_requires_hot_restart():
    with pytest.raises(RunStopped, match="hot restart"):
        validate_snapshot({"schema_version": 1, "nodes": []})
