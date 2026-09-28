from copy import deepcopy

import pytest
from jev_e2e.policy import ScriptedPolicy
from jev_e2e.runner import CounterRunner, RunStopped, allowed_actions, validate_snapshot


class App:
    def __init__(self):
        self.value = 7
        self.taps = 0
        self.changed = False

    async def snapshot(self):
        return {
            "schema_version": 1,
            "nodes": [
                {"id": "counter.value", "value": str(self.value)},
                {
                    "id": "counter.increment",
                    "label": "Increment" + (" updated" if self.changed else ""),
                    "enabled": True,
                    "key_count": 1,
                    "actions": ["tap"],
                },
            ],
        }

    async def tap(self, key):
        assert key == "counter.increment"
        self.taps += 1
        self.value += 1


class Policy:
    actual_model = "fake-test-model"

    def __init__(self, action="tap:counter.increment", confidence=1):
        self.action, self.confidence = action, confidence

    async def choose(self, state, actions):
        return {"action": self.action, "confidence": self.confidence}


async def test_assertion_uses_baseline_and_accepts_last_budgeted_action():
    app, report = App(), {}
    await CounterRunner(app, ScriptedPolicy(), report, max_steps=3).run(3)
    assert report["status"] == "passed"
    assert (report["initial"], report["expected"], report["observed"], app.taps) == (
        7,
        10,
        10,
        3,
    )


@pytest.mark.parametrize(
    "action,confidence",
    [
        ("tap:delete.account", 1),
        ("done", 1),
        ("tap:counter.increment", 0.2),
        ("tap:counter.increment", float("nan")),
        ("tap:counter.increment", 2),
    ],
)
async def test_untrusted_decision_cannot_execute_or_declare_success(action, confidence):
    app, report = App(), {}
    with pytest.raises(RunStopped):
        await CounterRunner(app, Policy(action, confidence), report).run(1)
    assert app.taps == 0
    assert report.get("status") != "passed"


async def test_discards_stale_decision_before_tapping():
    app, report = App(), {}

    class ChangingPolicy(Policy):
        async def choose(self, state, actions):
            app.changed = True
            return await super().choose(state, actions)

    with pytest.raises(RunStopped, match="Step budget"):
        await CounterRunner(app, ChangingPolicy(), report, max_steps=1).run(1)
    assert app.taps == 0
    assert any("discarded" in event for event in report["events"])


async def test_no_effect_does_not_repeat_non_idempotent_tap():
    class BrokenApp(App):
        async def tap(self, key):
            self.taps += 1

    app = BrokenApp()
    with pytest.raises(RunStopped, match="no observed change"):
        await CounterRunner(app, ScriptedPolicy(), {}).run(1)
    assert app.taps == 1


async def test_unexpected_delta_is_not_a_pass():
    class DoubleApp(App):
        async def tap(self, key):
            await super().tap(key)
            self.value += 1

    with pytest.raises(RunStopped, match="exactly one"):
        await CounterRunner(DoubleApp(), ScriptedPolicy(), {}).run(2)


async def test_disabled_or_duplicate_keys_are_not_candidates():
    snapshot = await App().snapshot()
    for field, value in [("enabled", False), ("key_count", 2), ("actions", [])]:
        altered = deepcopy(snapshot)
        altered["nodes"][1][field] = value
        assert "tap:counter.increment" not in allowed_actions(altered)


async def test_duplicate_identifiers_rejected():
    snapshot = await App().snapshot()
    snapshot["nodes"].append(snapshot["nodes"][0])
    with pytest.raises(RunStopped, match="duplicate"):
        validate_snapshot(snapshot)
