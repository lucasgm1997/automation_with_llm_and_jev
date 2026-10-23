import json

import httpx
import pytest
from jev_e2e.driver import websocket_uri
from jev_e2e.policy import JevPolicy


async def test_typesafe_request_and_response_contract(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "unit-test-token")
    state = {"ui": {"nodes": []}, "goal": "Wait for the login form to load"}
    actions = {"blocked": "Stop", "wait": "Wait"}

    def handle(request):
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"] == "Bearer unit-test-token"
        body = json.loads(request.content)
        assert body["state"] == state
        assert body["questions"]["next_action"]["criteria"] == actions
        assert body["questions"]["next_action"]["type"] == "choice"
        return httpx.Response(
            200,
            json={
                "model": "jev-test",
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": "wait",
                        "confidence": 0.91,
                        "probabilities": {"wait": 0.96, "blocked": 0.04},
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        policy = JevPolicy(client)
        assert await policy.choose(state, actions) == {
            "action": "wait",
            "confidence": 0.91,
            "probabilities": {"wait": 0.96, "blocked": 0.04},
        }
        assert policy.actual_model == "jev-test"


async def test_http_error_does_not_copy_response_body(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "unit-test-token")
    transport = httpx.MockTransport(
        lambda _: httpx.Response(401, text="sensitive response body")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="^TypeSafe API returned HTTP 401.$"):
            await JevPolicy(client).choose({}, {})


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("http://127.0.0.1:1234/token=/", "ws://127.0.0.1:1234/token=/ws"),
        ("ws://127.0.0.1:1234/token=/ws", "ws://127.0.0.1:1234/token=/ws"),
        ("https://localhost:1234/", "wss://localhost:1234/ws"),
    ],
)
def test_vm_uri_preserves_authentication_token(uri, expected):
    assert websocket_uri(uri) == expected
