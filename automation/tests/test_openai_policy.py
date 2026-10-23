import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from jev_e2e import app
from jev_e2e.openai_policy import OpenAIDecisionsPolicy
from jev_e2e.policy import ACTION_INSTRUCTIONS
from jev_e2e.semantics import RunStopped
from jev_e2e.task import Condition, InputSpec, UITask


ACTIONS = {"wait": {"operation": "wait"}, "blocked": {"operation": "blocked"}}


def answer_for(actions, selected, confidence=0.55):
    return {
        "model": "gpt-6-luna",
        "answers": [{
            "name": "next_action", "type": "choice",
            "choice": selected, "confidence": confidence,
            "probabilities": [
                {"value": key, "probability": 0.96 if key == selected else 0.04 / (len(actions) - 1)}
                for key in actions
            ],
        }],
    }


async def test_openai_decisions_request_and_response_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-token")
    state = {"goal": "Wait for the form", "ui": {"nodes": []}}

    def handle(request):
        assert str(request.url) == "https://api.openai.com/v1/decisions"
        assert request.headers["authorization"] == "Bearer test-openai-token"
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna"
        assert body["input"] == [{
            "role": "user", "content": [{"type": "input_json", "data": state}],
        }]
        question, = body["questions"]
        assert question["name"] == "next_action"
        assert question["type"] == "choice"
        assert question["instructions"] == ACTION_INSTRUCTIONS
        assert {c["value"]: json.loads(c["description"]) for c in question["choices"]} == ACTIONS
        payload = answer_for(ACTIONS, "wait", 0.55)
        payload["model"] = "gpt-6-luna-test-snapshot"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        policy = OpenAIDecisionsPolicy(client)
        result = await policy.choose(state, ACTIONS)
    assert result == {
        "action": "wait", "confidence": 0.55,
        "probabilities": {"wait": 0.96, "blocked": 0.04},
    }
    assert policy.actual_model == "gpt-6-luna-test-snapshot"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_openai_http_errors_do_not_expose_response_body(status):
    transport = httpx.MockTransport(lambda _: httpx.Response(status, text="sensitive body"))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match=f"^OpenAI Decisions API returned HTTP {status}.$"):
            await OpenAIDecisionsPolicy(client, api_key="test").choose({}, ACTIONS)


@pytest.mark.parametrize("patch", [
    {"name": "wrong-question"}, {"type": "score"}, {"confidence": None, "probabilities": None},
    {"probabilities": []},
    {"probabilities": [{"value": "wait", "probability": 1}] * 2},
    {"probabilities": [{"value": "unknown", "probability": 1}]},
    {"probabilities": [{"value": "wait", "probability": True}]},
])
async def test_openai_rejects_malformed_answers(patch):
    payload = answer_for(ACTIONS, "wait")
    payload["answers"][0].update(patch)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="^OpenAI Decisions returned an invalid response.$"):
            await OpenAIDecisionsPolicy(client, api_key="test").choose({}, ACTIONS)


async def test_openai_refusal_stops_without_inventing_confidence():
    payload = {"model": "gpt-6-luna", "answers": [{"name": "next_action", "type": "refusal"}]}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RunStopped, match="refused to choose an action"):
            await OpenAIDecisionsPolicy(client, api_key="test").choose({}, ACTIONS)


@pytest.mark.parametrize("confidence,status", [(0.55, "passed"), (0.54, "blocked"), (True, "blocked")])
async def test_openai_execution_keeps_assertions_confidence_and_fixture_redaction(
    monkeypatch, tmp_path, confidence, status,
):
    secret = "fixture-only@example.test"
    task = UITask(
        goal="Fill the email field",
        inputs=[InputSpec(name="email", description="Email", target="form.email", value=secret)],
        success_conditions=[
            Condition(target="form.email", check="value_equals", input_ref="email"),
            Condition(target="form.done", check="exists"),
        ],
        min_confidence=0.55, max_steps=60,
    )

    class Driver:
        filled = False
        closed = False

        async def snapshot(self):
            nodes = [{
                "id": "form.email", "role": "textField", "enabled": True,
                "actions": ["fill"], "value": secret if self.filled else "",
            }]
            if self.filled:
                nodes.append({"id": "form.done"})
            return {"schema_version": 2, "nodes": nodes}

        async def fill(self, target, value):
            assert target == "form.email" and value == secret
            self.filled = True

    driver = Driver()

    @asynccontextmanager
    async def connect(*args, **kwargs):
        try:
            yield driver
        finally:
            driver.closed = True

    calls = []

    def handle(request):
        assert secret not in request.content.decode()
        body = json.loads(request.content)
        choices = body["questions"][0]["choices"]
        actions = {c["value"]: json.loads(c["description"]) for c in choices}
        selected = next(key for key, a in actions.items() if a["operation"] == "fill")
        calls.append(selected)
        return httpx.Response(200, json=answer_for(actions, selected, confidence))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(app.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(app, "connect", connect)
    monkeypatch.setattr(app, "dotenv_values", lambda _: {"OPENAI_API_KEY": "local-test-key"})
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(app, "ARTIFACTS", tmp_path)
    result = await app.execute("unused", task=task, provider="openai")

    assert result["status"] == status
    assert result["actions"] == (1 if status == "passed" else 0)
    assert all(c["passed"] for c in result["assertions"]) == (status == "passed")
    assert result["min_confidence"] == 0.55
    assert result["max_steps"] == 60
    assert result["policy"] == "openai"
    assert result["timings"]["openai"]["calls"] == 1
    assert driver.closed and client.is_closed and len(calls) == 1
    trace_text = Path(result["artifact"]).read_text()
    assert secret not in trace_text and "local-test-key" not in trace_text
    decisions = [e["decision"] for e in json.loads(trace_text)["events"] if "decision" in e]
    assert decisions[0]["confidence"] == confidence
