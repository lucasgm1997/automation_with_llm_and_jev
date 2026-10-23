import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from jev_e2e import app
from jev_e2e.task import Condition, UITask


@pytest.mark.parametrize("confidence,status", [(0.67, "passed"), (0.59, "blocked")])
async def test_execute_generic_task_records_result_and_closes_driver(
    monkeypatch, tmp_path, confidence, status,
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

        def __init__(self, *args):
            pass

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
    monkeypatch.setattr(app, "dotenv_values", lambda _: {})
    monkeypatch.setattr(app, "ARTIFACTS", tmp_path)
    task = UITask(
        goal="Open account",
        success_conditions=[Condition(target="account.home", check="exists")],
        min_confidence=0.6,
    )
    result = await app.execute("unused", task=task)
    assert result["status"] == status
    assert result["min_confidence"] == 0.6
    assert result["scenario"] == "ui_task"
    assert result["policy"] == "jev"
    assert result["actions"] == (1 if status == "passed" else 0)
    assert driver.closed
    assert "events" not in result
    trace = json.loads(Path(result["artifact"]).read_text())
    assert trace["events"]
    assert trace["status"] == status
    assert trace["min_confidence"] == 0.6
