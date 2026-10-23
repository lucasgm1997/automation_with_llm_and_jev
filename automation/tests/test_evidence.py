import asyncio
import base64
import json

import pytest
from websockets.asyncio.server import serve

from jev_e2e.evidence import Capture, EvidenceManager
from jev_e2e.evidence_redaction import body_preview, clean, clean_text, clean_url
from jev_e2e.vm_service import VMConnection, VMError

URI = "ws://127.0.0.1:9000/token=/ws"


class FakeVM:
    def __init__(self):
        self.connected = True
        self.events = asyncio.Queue()
        self.events_dropped = 0
        self.calls = []
        self.live = ["i1"]
        self.enabled = {"i1": False}
        self.requests = []
        self.timestamp = 1000
        self.extensions = True
        self.detail = {}

    async def open(self, uri):
        self.connected = True

    async def close(self):
        self.connected = False

    async def call(self, method, **params):
        self.calls.append((method, params))
        isolate = params.get("isolateId", "i1")
        if method == "getVM":
            return {"isolates": [{"id": i} for i in self.live]}
        if method == "getIsolate":
            return {"extensionRPCs": ["ext.dart.io.getHttpProfile", "ext.dart.io.httpEnableTimelineLogging"] if self.extensions else []}
        if method == "ext.dart.io.httpEnableTimelineLogging":
            if "enabled" in params:
                self.enabled[isolate] = params["enabled"] == "true"
            return {"enabled": self.enabled.get(isolate, False)}
        if method == "ext.dart.io.getHttpProfile":
            return {"timestamp": self.timestamp, "requests": self.requests}
        if method == "ext.dart.io.getHttpProfileRequest":
            return self.detail
        if method == "streamListen":
            return {"type": "Success"}
        if method == "getObject":
            return {"valueAsString": "resolved stack trace"}
        raise AssertionError(method)


def request(**changes):
    return {"id": "r1", "method": "GET", "uri": "https://example.test/products?token=private&sort=name",
            "startTime": 2000, "endTime": 3000, "request": {"contentLength": 0}, **changes}


@pytest.mark.parametrize("value", [
    'Authorization: Bearer abc123', 'password="private value"',
    '{"refresh_token": "private"}', 'apiKey=private',
])
def test_common_console_credentials_are_removed(value):
    result = clean_text(value)
    assert "private" not in result and "abc123" not in result
    assert "<redacted>" in result


def test_network_redaction_preserves_diagnostic_fields():
    data = clean({"statusCode": 401, "Authorization": "secret", "headers": {"Set-Cookie": ["secret"]},
                  "user": {"password": "secret"}, "uri": "https://user:secret@example.test/x?token=secret&q=test"})
    assert "secret" not in json.dumps(data)
    assert data["statusCode"] == 401
    assert "q=test" in data["uri"]
    assert "user:" not in data["uri"]


def test_body_previews_redact_nested_json_and_report_limits():
    raw = list(json.dumps({"ok": False, "accessToken": "secret", "nested": [{"password": "secret"}]}).encode())
    preview = body_preview(raw, {"content-type": ["application/json"]})
    assert "secret" not in preview["text"] and "false" in preview["text"]
    assert json.loads(preview["text"])["accessToken"] == "<redacted>"
    assert body_preview([1, 2], {"content-type": ["image/png"]})["omitted"]
    assert body_preview([65] * 33000, {})["truncated"]
    assert body_preview([65] * 33000, {})["omitted"]


def test_vm_auth_codes_in_console_startup_urls_are_redacted():
    text = 'VM: http://127.0.0.1:5000/authCODE123=/ and DevTools ?uri=ws://localhost:5000/authCODE123=/ws'
    result = clean_text(text)
    assert 'authCODE123' not in result and result.count('<vm-token>') == 2


async def test_console_stdout_logging_and_flutter_errors_without_app_collector():
    capture = Capture("console", URI, 1800, FakeVM())
    await capture.console_event({"streamId": "Stdout", "event": {"kind": "WriteEvent", "timestamp": 123,
        "bytes": base64.b64encode("Olá password=secret\n".encode()).decode()}})
    await capture.console_event({"streamId": "Logging", "event": {"isolate": {"id": "i1"}, "logRecord": {
        "level": 1000, "message": {"valueAsString": "Failed to load"}, "error": {"valueAsString": "bad response"},
        "stackTrace": {"id": "objects/1", "valueAsStringIsTruncated": True}}}})
    await capture.console_event({"streamId": "Extension", "event": {"extensionKind": "Flutter.Error", "extensionData": {"description": "layout error"}}})
    await capture.console_event({"streamId": "Extension", "event": {"extensionKind": "unrelated", "extensionData": {"secret": "ignored"}}})
    result = capture.read(limit=1)
    assert "Olá" in result["items"][0]["message"]
    assert "secret" not in json.dumps(result)
    assert result["has_more"]
    next_page = capture.read(after_cursor=result["next_cursor"])
    assert len(next_page["items"]) == 2
    assert next_page["items"][0]["stack_trace"] == "resolved stack trace"
    assert len(capture.read(min_level=1000)["items"]) == 2
    assert len(capture.read(source="Stdout")["items"]) == 1


def test_bounded_console_history_and_non_consuming_cursors(monkeypatch):
    monkeypatch.setattr("jev_e2e.evidence.MAX_ITEMS", 2)
    capture = Capture("console", URI, 1800, FakeVM())
    for i in range(4):
        capture.store(str(i), {"message": str(i)})
    result = capture.read()
    assert len(result["items"]) == 2
    assert result["evicted"] == 2 and result["history_truncated"]
    assert capture.read() == result
    assert capture.read(after_cursor=result["next_cursor"])["items"] == []
    with pytest.raises(ValueError, match="Cursor"):
        capture.read(after_cursor=100)


async def test_network_incremental_updates_and_full_response_duration():
    vm = FakeVM()
    vm.requests = [request(startTime=10)]  # Before capture, must not import history.
    capture = Capture("network", URI, 1800, vm)
    await capture.poll_network()
    assert vm.enabled["i1"] and capture.read()["items"] == []
    vm.requests = [request()]
    vm.timestamp = 4000
    await capture.poll_network()
    pending = capture.read()
    assert pending["items"][0]["state"] == "pending"
    assert pending["items"][0]["duration_ms"] is None  # Upload end isn't response end.
    vm.requests = [request(response={"statusCode": 500, "startTime": 4000, "endTime": 7000})]
    vm.timestamp = 8000
    await capture.poll_network()
    completed = capture.read(after_cursor=pending["next_cursor"], errors_only=True)
    assert completed["items"][0]["duration_ms"] == 5
    assert completed["items"][0]["status_code"] == 500
    assert "private" not in completed["items"][0]["url"]
    assert len(capture.items) == 1
    before = capture.sequence
    await capture.poll_network()
    assert capture.sequence == before  # Same poll doesn't invent changes.
    await capture.close()
    assert not vm.enabled["i1"]
    assert not any(m == "ext.dart.io.clearHttpProfile" for m, _ in vm.calls)


async def test_connection_error_is_a_failed_request_without_http_status():
    capture = Capture("network", URI, 1800, FakeVM())
    capture.record_request("i1", request(request={"error": "Connection refused"}))
    item = capture.read(errors_only=True)["items"][0]
    assert item["state"] == "failed" and item["status_code"] is None
    assert item["duration_ms"] == 1


async def test_hot_restart_discovers_new_isolate_and_preserves_existing_profiler():
    vm = FakeVM()
    vm.enabled["i1"] = True
    capture = Capture("network", URI, 1800, vm)
    await capture.poll_network()
    vm.live = ["i2"]
    await capture.poll_network()
    assert capture.isolates == {"i1": "exited", "i2": "capturing"}
    assert vm.enabled["i2"]
    await capture.close()
    assert vm.enabled["i1"] and not vm.enabled["i2"]


async def test_unsupported_network_is_explicit_not_success_evidence():
    vm = FakeVM()
    vm.extensions = False
    capture = Capture("network", URI, 1800, vm)
    await capture.poll_network()
    assert capture.info()["isolates"]["i1"] == "http_profiling_unavailable"
    assert not vm.enabled["i1"]
    vm.extensions = True
    await capture.poll_network()
    assert capture.info()["isolates"]["i1"] == "capturing"
    await capture.close()


async def test_network_details_are_opt_in_and_stop_keeps_metadata():
    vm = FakeVM()
    capture = Capture("network", URI, 1800, vm)
    capture.status = "capturing"
    capture.record_request("i1", request())
    vm.detail = {"request": {"headers": {"Authorization": "secret"}},
                 "response": {"headers": {"content-type": ["application/json"]}},
                 "responseBody": list(b'{"token":"secret","error":"invalid email"}')}
    result = await capture.request_details("i1:r1")
    assert "response_body" not in result and "secret" not in json.dumps(result)
    result = await capture.request_details("i1:r1", True)
    assert "invalid email" in result["response_body"]["text"]
    assert "secret" not in json.dumps(result)
    await capture.close()
    result = await capture.request_details("i1:r1", True)
    assert result["details_available"] is False
    assert capture.read()["items"]


async def test_manager_reuses_same_kind_but_console_and_network_are_independent(monkeypatch):
    monkeypatch.setattr("jev_e2e.evidence.VMConnection", FakeVM)
    manager = EvidenceManager()
    try:
        console = await manager.start("console", URI)
        repeated = await manager.start("console", URI)
        network = await manager.start("network", URI)
        assert repeated["capture_id"] == console["capture_id"] and repeated["reused"]
        assert network["capture_id"] != console["capture_id"]
        await manager.stop(console["capture_id"])
        assert manager.get(network["capture_id"]).status == "capturing"
        with pytest.raises(ValueError):
            manager.get(network["capture_id"], "console")
    finally:
        await manager.close()


async def test_ttl_expires_and_cleans_up_connection(monkeypatch):
    monkeypatch.setattr("jev_e2e.evidence.VMConnection", FakeVM)
    manager = EvidenceManager()
    result = await manager.start("console", URI, ttl_seconds=0.02)
    capture = manager.get(result["capture_id"])
    await asyncio.wait_for(capture.expiry, 1)
    assert capture.status == "expired" and not capture.connection.connected
    await manager.close()


async def test_cancelled_start_restores_profiler_and_does_not_leave_capture(monkeypatch):
    enabled = asyncio.Event()
    class SlowVM(FakeVM):
        async def call(self, method, **params):
            if method == "ext.dart.io.getHttpProfile":
                enabled.set()
                await asyncio.Future()
            return await super().call(method, **params)
    vm = SlowVM()
    monkeypatch.setattr("jev_e2e.evidence.VMConnection", lambda: vm)
    manager = EvidenceManager()
    task = asyncio.create_task(manager.start("network", URI))
    await asyncio.wait_for(enabled.wait(), 1)
    assert vm.enabled["i1"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not vm.enabled["i1"] and not vm.connected
    assert not manager.captures


async def test_actual_websocket_rpc_demultiplexes_events_and_out_of_order_responses():
    async def handler(socket):
        first, second = json.loads(await socket.recv()), json.loads(await socket.recv())
        await socket.send(json.dumps({"jsonrpc": "2.0", "method": "streamNotify", "params": {"streamId": "Stdout", "event": {"bytes": "aGk="}}}))
        await socket.send(json.dumps({"jsonrpc": "2.0", "id": second["id"], "result": {"value": 2}}))
        await socket.send(json.dumps({"jsonrpc": "2.0", "id": first["id"], "result": {"value": 1}}))
        third = json.loads(await socket.recv())
        await socket.send(json.dumps({"jsonrpc": "2.0", "id": third["id"], "error": {"code": 123, "message": "secret raw failure"}}))
        await socket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        vm = VMConnection()
        try:
            await vm.open(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/ws")
            results = await asyncio.gather(vm.call("one"), vm.call("two"))
            assert results == [{"value": 1}, {"value": 2}]
            assert (await vm.events.get())["streamId"] == "Stdout"
            with pytest.raises(VMError) as error:
                await vm.call("fail")
            assert error.value.code == 123 and "secret" not in str(error.value)
        finally:
            await vm.close()


async def test_disconnection_fails_pending_calls_without_hanging():
    async def handler(socket):
        await socket.recv()
        await socket.close()
    async with serve(handler, "127.0.0.1", 0) as server:
        vm = VMConnection()
        await vm.open(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/ws")
        try:
            with pytest.raises(VMError):
                await asyncio.wait_for(vm.call("getVM"), 1)
            assert not vm.connected
        finally:
            await vm.close()
