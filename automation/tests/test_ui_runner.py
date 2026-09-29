import json

import pytest
from jev_e2e.runner import RunStopped
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
    def __init__(self, targets):
        self.targets = iter(targets)
        self.requests = []

    async def choose(self, state, candidates):
        self.requests.append({"state": state, "candidates": candidates})
        target = next(self.targets)
        selected = next(
            key for key, action in candidates.items() if action.get("target") == target
        )
        return {"action": selected, "confidence": 1.0}


def login_task():
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
    )


async def test_generic_login_uses_discovered_targets_and_keeps_values_local():
    task, app, report = login_task(), LoginApp(), {}
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


async def test_arbitrary_selector_from_policy_is_rejected():
    class BadPolicy:
        async def choose(self, state, candidates):
            return {"action": "tap:delete.all", "confidence": 1}

    task, app = login_task(), LoginApp()
    with pytest.raises(RunStopped, match="outside"):
        await UIRunner(
            app, BadPolicy(), task, TaskValues(task, {"TEST_PASSWORD": "secret"}), {}
        ).run()
    assert app.calls == []


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
