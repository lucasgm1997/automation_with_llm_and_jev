import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from jev_e2e import server as server_module


async def test_http_health_discovery_inspection_and_shared_lock(monkeypatch):
    monkeypatch.setenv("JEV_ANDROID_PREPARE_ENABLED", "0")
    monkeypatch.setattr(server_module.server.settings, "host", "0.0.0.0")
    application = server_module.server.streamable_http_app()

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), **kwargs)

    async with application.router.lifespan_context(application):
        async with client_factory() as client:
            health = await client.get("http://127.0.0.1:8765/healthz")
            assert health.status_code == 200
            assert health.json() == {
                "status": "ok", "service": "jev-e2e", "busy": False,
                "marionette": "on_demand", "android_prepare_enabled": False,
            }

        async with (
            client_factory() as http_client,
            streamable_http_client(
                "http://127.0.0.1:8765/mcp", http_client=http_client,
            ) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listing = await session.list_tools()
            assert {tool.name for tool in listing.tools} == {
                "prepare_android_app", "inspect_ui", "run_ui_task",
            }
            run_tool = next(t for t in listing.tools if t.name == "run_ui_task")
            assert run_tool.inputSchema["properties"]["provider"]["enum"] == ["jev", "openai"]
            assert run_tool.inputSchema["properties"]["min_confidence"]["default"] == 0.6

            # Preparation must not try to control the host from inside the container.
            def unexpected_prepare(*args):
                pytest.fail("Android preparation must remain on the host")

            monkeypatch.setattr(server_module, "prepare_android", unexpected_prepare)
            result = await session.call_tool("prepare_android_app", {
                "device_id": "emulator-5556", "app_id": "com.example.app",
            })
            assert result.structuredContent["status"] == "blocked"
            assert "host" in result.structuredContent["reason"]

            # All HTTP clients use the same process lock; health remains responsive.
            async with server_module.run_lock:
                result = await session.call_tool("inspect_ui", {"vm_uri": "unused"})
                assert result.structuredContent == {"status": "busy"}
                async with client_factory() as client:
                    response = await client.get("http://127.0.0.1:8765/healthz")
                    assert response.status_code == 200
                    assert response.json()["busy"] is True

            # DNS rebinding protection must survive container binding on 0.0.0.0.
            async with client_factory() as client:
                response = await client.post(
                    "http://127.0.0.1:8765/mcp", headers={"Host": "untrusted.example"},
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
                )
                assert response.status_code == 421
