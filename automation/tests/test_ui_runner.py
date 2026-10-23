import json
from itertools import count

import pytest
from jev_e2e.semantics import RunStopped, validate_snapshot
from jev_e2e.task import Condition, InputSpec, TaskValues, UITask, action_candidates
from jev_e2e.ui_runner import UIRunner
from pydantic import ValidationError


class LoginApp:
    def __init__(self):
        self.fields = {"auth.email": "", "auth.password": ""}
        self.signed_in = False
        self.calls = []

    async def snapshot(self):
        if self.signed_in:
            return {
                "schema_version": 2,
                "nodes": [{"id": "account.home", "label": "Account"}],
            }
        nodes = [
            {
                "id": key,
                "role": "textField",
                "label": key,
                "value": value,
                "actions": ["tap", "fill"],
                "enabled": True,
                "is_empty": value == "",
                "obscured": False,
            }
            for key, value in self.fields.items()
        ]
        nodes.append(
            {
                "id": "auth.submit",
                "label": "Entrar",
                "actions": ["tap"],
                "enabled": True,
            }
        )
        return {"schema_version": 2, "nodes": nodes}

    async def fill(self, key, value):
        self.calls.append(("fill", key))
        self.fields[key] = value

    async def tap(self, key):
        self.calls.append(("tap", key))
        assert key == "auth.submit"
        self.signed_in = self.fields == {
            "auth.email": "person@example.test",
            "auth.password": "a-secret-test-password",
        }


class SequencePolicy:
    def __init__(self, targets, confidence=1.0):
        self.targets = iter(targets)
        self.requests = []
        self.confidence = confidence

    async def choose(self, state, candidates):
        self.requests.append({"state": state, "candidates": candidates})
        target = next(self.targets)
        selected = next(
            key for key, action in candidates.items() if action.get("target") == target
        )
        return {"action": selected, "confidence": self.confidence}


def login_task(**options):
    return UITask(
        goal="Sign in using the supplied credentials",
        inputs=[
            InputSpec(
                name="email",
                description="Login email",
                target="auth.email",
                value="person@example.test",
            ),
            InputSpec(
                name="password",
                description="Login password",
                target="auth.password",
                env="TEST_PASSWORD",
            ),
        ],
        success_conditions=[Condition(target="account.home", check="exists")],
        **options,
    )


async def test_generic_login_uses_discovered_targets_and_keeps_values_local():
    task, app, report = login_task(max_steps=3), LoginApp(), {}
    values = TaskValues(task, {"TEST_PASSWORD": "a-secret-test-password"})
    policy = SequencePolicy(["auth.email", "auth.password", "auth.submit"])
    await UIRunner(app, policy, task, values, report).run()
    assert report["status"] == "passed"
    assert report["actions"] == 3
    assert app.signed_in
    serialized = json.dumps({"report": report, "requests": policy.requests})
    assert "a-secret-test-password" not in serialized
    assert "person@example.test" not in serialized
    assert "<input:password>" in serialized


@pytest.mark.parametrize(
    "options,confidence,accepted",
    [
        ({}, 0.59, False),
        ({}, 0.6, True),
        ({}, 0.67, True),
        ({"min_confidence": 0.7}, 0.67, False),
        ({"min_confidence": 0.6}, 0.59, False),
        ({"min_confidence": 0.6}, 0.6, True),
        ({"min_confidence": 0.6}, 0.67, True),
        ({"min_confidence": 0.9}, 0.89, False),
        ({"min_confidence": 0}, 0, True),
        ({"min_confidence": 1}, 1, True),
    ],
)
async def test_confidence_threshold_controls_actions_and_preserves_assertions(
    options, confidence, accepted,
):
    task, app, report = login_task(**options), LoginApp(), {}
    runner = UIRunner(
        app,
        SequencePolicy(["auth.email", "auth.password", "auth.submit"], confidence),
        task,
        TaskValues(task, {"TEST_PASSWORD": "a-secret-test-password"}),
        report,
    )
    if accepted:
        await runner.run()
        assert report["status"] == "passed"
        assert report["actions"] == 3
        assert all(check["passed"] for check in report["assertions"])
    else:
        with pytest.raises(RunStopped, match="below configured") as error:
            await runner.run()
        assert str(confidence) in str(error.value)
        assert str(task.min_confidence) in str(error.value)
        assert app.calls == []
        assert report["actions"] == 0
        assert not all(check["passed"] for check in report["assertions"])
    assert report["min_confidence"] == options.get("min_confidence", 0.6)


@pytest.mark.parametrize(
    "confidence", [None, True, "0.9", -0.1, 1.1, float("nan"), float("inf")]
)
async def test_invalid_policy_confidence_is_rejected_even_with_zero_threshold(confidence):
    task, app = login_task(min_confidence=0), LoginApp()
    with pytest.raises(RunStopped, match="invalid confidence"):
        await UIRunner(
            app,
            SequencePolicy(["auth.email"], confidence),
            task,
            TaskValues(task, {"TEST_PASSWORD": "secret"}),
            {},
        ).run()
    assert app.calls == []


@pytest.mark.parametrize(
    "threshold", [None, True, "0.6", -0.1, 1.1, float("nan"), float("inf")]
)
def test_invalid_confidence_threshold_is_rejected(threshold):
    with pytest.raises(ValidationError):
        login_task(min_confidence=threshold)


async def test_conditions_already_true_do_not_claim_a_journey_was_executed():
    task, app, report = login_task(), LoginApp(), {}
    app.signed_in = True
    await UIRunner(
        app, SequencePolicy([]), task, TaskValues(task, {"TEST_PASSWORD": "x"}), report
    ).run()
    assert report["status"] == "already_satisfied"
    assert app.calls == []


@pytest.mark.parametrize(
    "transition_nodes",
    [[], [{"id": "outgoing", "actions": [], "label": "Leaving page"}]],
)
async def test_empty_route_transition_is_waited_out_without_an_extra_decision(
    transition_nodes,
):
    class TransitionApp(LoginApp):
        empty_frames = 2

        async def snapshot(self):
            if self.signed_in and self.empty_frames:
                self.empty_frames -= 1
                return {"schema_version": 2, "nodes": transition_nodes}
            return await super().snapshot()

    task, app, report = login_task(), TransitionApp(), {}
    policy = SequencePolicy(["auth.email", "auth.password", "auth.submit"])
    await UIRunner(
        app,
        policy,
        task,
        TaskValues(task, {"TEST_PASSWORD": "a-secret-test-password"}),
        report,
    ).run()
    assert report["status"] == "passed"
    assert len(policy.requests) == 3
    assert app.empty_frames == 0


async def test_scope_and_field_bindings_constrain_candidates():
    task = login_task()
    task.allowed_targets = ["auth.email"]
    values = TaskValues(task, {"TEST_PASSWORD": "secret"})
    candidates = action_candidates(task, await LoginApp().snapshot(), values, {})
    actions = [action for action in candidates.values() if "target" in action]
    assert len(actions) == 1
    assert actions[0]["input"] == "email"


@pytest.mark.parametrize("action", ["tap:delete.all", "done"])
async def test_arbitrary_selector_or_completion_from_policy_is_rejected(action):
    class BadPolicy:
        async def choose(self, state, candidates):
            return {"action": action, "confidence": 1}

    task, app = login_task(), LoginApp()
    with pytest.raises(RunStopped, match="outside"):
        await UIRunner(
            app, BadPolicy(), task, TaskValues(task, {"TEST_PASSWORD": "secret"}), {}
        ).run()
    assert app.calls == []


async def test_discards_decision_when_ui_changes_during_inference():
    task, app, report = login_task(max_steps=1), LoginApp(), {}

    class ChangingPolicy(SequencePolicy):
        async def choose(self, state, candidates):
            app.fields["auth.email"] = "external-change@example.test"
            return await super().choose(state, candidates)

    with pytest.raises(RunStopped, match="Step budget"):
        await UIRunner(
            app,
            ChangingPolicy(["auth.email"]),
            task,
            TaskValues(task, {"TEST_PASSWORD": "secret"}),
            report,
        ).run()
    assert app.calls == []
    assert any("discarded" in event for event in report["events"])


async def test_action_without_observed_effect_is_not_repeated(monkeypatch):
    class UnchangedApp(LoginApp):
        async def tap(self, key):
            self.calls.append(("tap", key))

    # Advance the observation deadline without a real three-second wait.
    ticks = count(step=4)
    monkeypatch.setattr("jev_e2e.ui_runner.perf_counter", lambda: next(ticks))
    task, app, report = login_task(), UnchangedApp(), {}
    with pytest.raises(RunStopped, match="No semantic change"):
        await UIRunner(
            app,
            SequencePolicy(["auth.submit"]),
            task,
            TaskValues(task, {"TEST_PASSWORD": "secret"}),
            report,
        ).run()
    assert app.calls == [("tap", "auth.submit")]
    assert report.get("status") != "passed"


@pytest.mark.parametrize("field,value", [("enabled", False), ("actions", [])])
async def test_disabled_or_non_actionable_nodes_are_not_candidates(field, value):
    task = login_task()
    snapshot = await LoginApp().snapshot()
    snapshot["nodes"][-1][field] = value
    candidates = action_candidates(
        task, snapshot, TaskValues(task, {"TEST_PASSWORD": "secret"}), {}
    )
    assert all(action.get("target") != "auth.submit" for action in candidates.values())


async def test_duplicate_identifiers_rejected():
    snapshot = await LoginApp().snapshot()
    snapshot["nodes"].append(snapshot["nodes"][0])
    with pytest.raises(RunStopped, match="duplicate"):
        validate_snapshot(snapshot)


async def test_negative_test_passes_only_on_expected_error():
    class InvalidApp(LoginApp):
        async def tap(self, key):
            self.calls.append(("tap", key))

        async def snapshot(self):
            snapshot = await super().snapshot()
            if self.calls:
                snapshot["nodes"].append(
                    {"id": "auth.error", "label": "Credenciais inválidas"}
                )
            return snapshot

    task = UITask(
        goal="Submit empty form and check the expected error",
        success_conditions=[
            Condition(
                target="auth.error",
                check="label_contains",
                expected="Credenciais inválidas",
            ),
            Condition(target="account.home", check="absent"),
        ],
    )
    report = {}
    await UIRunner(
        InvalidApp(),
        SequencePolicy(["auth.submit"]),
        task,
        TaskValues(task, {}),
        report,
    ).run()
    assert report["status"] == "passed"
    assert all(c["passed"] for c in report["assertions"])


def test_missing_local_credential_is_reported_without_value():
    with pytest.raises(RunStopped, match="Missing local environment"):
        TaskValues(login_task(), {})


def test_redaction_is_idempotent_and_preserves_identifiers():
    task = UITask(
        goal="Fill field",
        inputs=[InputSpec(name="price", description="Price", value="1")],
        success_conditions=[Condition(target="product.1", check="exists")],
    )
    values = TaskValues(task, {})
    payload = {
        "id": "product.1",
        "value": "1",
        "model": "jev-1.13.0",
        "label": "Item 1",
    }
    redacted = values.redact(payload)
    assert redacted["id"] == payload["id"]
    assert redacted["model"] == payload["model"]
    assert redacted["value"] == "<input:price>"
    assert values.redact(redacted) == redacted


@pytest.mark.parametrize(
    "condition",
    [
        {"target": "x", "check": "label_contains", "expected": ""},
        {"target": "x", "check": "value_equals"},
        {"target": "x", "check": "value_increased_by", "expected": "three"},
    ],
)
def test_invalid_assertions_fail_before_running(condition):
    with pytest.raises(ValidationError):
        Condition.model_validate(condition)
