import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from jev_e2e import app
from jev_e2e.task import Condition, UITask


@pytest.mark.parametrize("confidence,status", [(0.67, "passed"), (0.59, "blocked")])
@pytest.mark.parametrize("provider", ["jev", "openai"])
async def test_execute_generic_task_records_result_and_closes_driver(
    monkeypatch, tmp_path, confidence, status, provider,
):
    class Driver:
        opened = False
        closed = False

        async def snapshot(self):
            return {
                "schema_version": 2,
                "nodes": [
                    {"id": "account.home"} if self.opened else
                    {"id": "account.open", "enabled": True, "actions": ["tap"]}
                ],
            }

        async def tap(self, target):
            assert target == "account.open"
            self.opened = True

    class Policy:
        actual_model = "jev-test"

        def __init__(self, client, model, api_key):
            assert model == ("gpt-6-luna" if provider == "openai" else "jev-latest")
            assert api_key == f"test-{provider}-key"

        async def choose(self, state, candidates):
            selected = next(
                key for key, action in candidates.items()
                if action.get("target") == "account.open"
            )
            return {"action": selected, "confidence": confidence}

    driver = Driver()

    @asynccontextmanager
    async def connect(vm_uri, dart):
        assert vm_uri == "unused"
        try:
            yield driver
        finally:
            driver.closed = True

    monkeypatch.setattr(app, "connect", connect)
    monkeypatch.setattr(app, "JevPolicy", Policy)
    monkeypatch.setattr(app, "OpenAIDecisionsPolicy", Policy)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-jev-key")
    monkeypatch.setattr(app, "dotenv_values", lambda _: {})
    monkeypatch.setattr(app, "ARTIFACTS", tmp_path)
    task = UITask(
        goal="Open account",
        success_conditions=[Condition(target="account.home", check="exists")],
        min_confidence=0.6,
    )
    result = await app.execute("unused", task=task, provider=provider)
    assert result["status"] == status
    assert result["min_confidence"] == 0.6
    assert result["scenario"] == "ui_task"
    assert result["policy"] == provider
    assert result["timings"][provider]["calls"] == 1
    assert result["actions"] == (1 if status == "passed" else 0)
    assert driver.closed
    assert "events" not in result
    trace = json.loads(Path(result["artifact"]).read_text())
    assert trace["events"]
    assert trace["status"] == status
    assert trace["min_confidence"] == 0.6


@pytest.mark.parametrize("options,reason", [
    ({"provider": "openai"}, "Set OPENAI_API_KEY"),
    ({"provider": "openai", "model": "jev-latest"}, "supports model gpt-6-luna only"),
    ({"provider": "unknown"}, "provider must be jev or openai"),
])
async def test_provider_configuration_fails_before_device_connection(
    monkeypatch, tmp_path, options, reason,
):
    def no_connection(*args):
        pytest.fail("Invalid provider configuration must not connect to the app")

    monkeypatch.setattr(app, "connect", no_connection)
    monkeypatch.setattr(app, "dotenv_values", lambda _: {})
    monkeypatch.setattr(app, "ARTIFACTS", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # A Jev key must never be reused as an OpenAI credential or trigger fallback.
    monkeypatch.setenv("TYPESAFE_API_KEY", "jev-only-token")
    task = UITask(
        goal="Open account",
        success_conditions=[Condition(target="account.home", check="exists")],
    )
    result = await app.execute("unused", task=task, **options)
    assert result["status"] == "failed"
    assert result["actions"] == 0
    assert reason in result["reason"]
    assert Path(result["artifact"]).exists()
