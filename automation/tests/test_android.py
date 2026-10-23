import asyncio
from types import SimpleNamespace

import httpx
import pytest

from jev_e2e import android


APP = "com.example.demo"
DEVICE = "emulator-5556"


@pytest.fixture
def device(monkeypatch, tmp_path):
    state = SimpleNamespace(
        connected=True, installed=True, debug=True, booted=True, launched=False,
        logs="The Dart VM service is listening on http://127.0.0.1:44037/fresh=/",
        calls=[], forwards=0, spawn=[], missing_extensions=False, launcher_error=False,
        rpc=[],
    )

    async def command(*args, check=True):
        state.calls.append(args)
        if args == ("emulator", "-list-avds"):
            return "Test_AVD"
        if args == ("adb", "devices"):
            return "List of devices attached\n" + (f"{DEVICE}\tdevice" if state.connected else "")
        assert args[:3] == ("adb", "-s", DEVICE)
        action = args[3:]
        if action == ("shell", "getprop", "sys.boot_completed"):
            return "1" if state.booted else "0"
        if action == ("emu", "avd", "name"):
            return "Test_AVD\nOK"
        if action == ("shell", "pm", "path", APP):
            return "package:/data/app/demo/base.apk" if state.installed else ""
        if action == ("shell", "dumpsys", "package", APP):
            return "flags=[ HAS_CODE DEBUGGABLE ]" if state.debug else "flags=[ HAS_CODE ]"
        if action[:4] == ("shell", "cmd", "package", "resolve-activity"):
            return APP + "/.MainActivity"
        if action[:3] == ("shell", "am", "start"):
            state.launched = True
            return "Error: activity not found" if state.launcher_error else "Status: ok"
        if action == ("shell", "pidof", APP):
            return "7779"
        if action[:1] == ("logcat",):
            assert action[2:4] == ("--pid", "7779")
            return state.logs
        if action[:2] == ("forward", "tcp:0"):
            state.forwards += 1
            return str(51000 + state.forwards)
        if action[:2] == ("forward", "--remove"):
            return ""
        pytest.fail(f"Unexpected SDK command: {args}")

    def spawn(args, **kwargs):
        state.spawn.append(args)
        assert kwargs["start_new_session"] is True
        state.connected = True
        return SimpleNamespace(poll=lambda: None)

    def handler(request):
        state.rpc.append(request)
        if request.url.path.endswith("/getVM"):
            pid = 1234 if "stale" in request.url.path else 7779
            return httpx.Response(200, json={"result": {"pid": pid, "isolates": [{"id": "isolates/1"}]}})
        assert request.url.path.endswith("/getIsolate")
        assert request.url.params["isolateId"] == "isolates/1"
        extensions = [] if state.missing_extensions else sorted(android.REQUIRED_EXTENSIONS)
        return httpx.Response(200, json={"result": {"extensionRPCs": extensions}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(android, "sdk_binary", lambda name: name)
    monkeypatch.setattr(android, "command", command)
    monkeypatch.setattr(android.subprocess, "Popen", spawn)
    monkeypatch.setattr(android, "ARTIFACTS", tmp_path)
    monkeypatch.setattr(android.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return state


async def test_installed_apk_opens_without_flutter_or_reset_and_returns_host_uri(device):
    result = await android.prepare_android(DEVICE, APP)
    assert result["status"] == "ready"
    assert result["vm_uri"] == "http://127.0.0.1:51001/fresh=/"
    assert result["forward_port"] == 51001
    assert result["emulator_started"] is False
    assert device.launched
    assert all(call[0] == "adb" for call in device.calls)
    assert not any(value in {"force-stop", "clear", "install", "--remove"} for call in device.calls for value in call)


async def test_closed_emulator_starts_named_avd_and_keeps_installed_data(device):
    device.connected = False
    result = await android.prepare_android(DEVICE, APP, avd_name="Test_AVD")
    assert result["status"] == "ready"
    assert result["emulator_started"] is True
    assert device.spawn == [["emulator", "-avd", "Test_AVD", "-port", "5556"]]
    assert result["emulator_log"].endswith(".log")


async def test_stale_service_is_rejected_by_live_pid_and_its_forward_removed(device):
    device.logs += "\nThe Dart VM service is listening on http://127.0.0.1:42979/stale=/"
    result = await android.prepare_android(DEVICE, APP)
    assert result["status"] == "ready"
    assert result["vm_uri"] == "http://127.0.0.1:51002/fresh=/"
    assert ("adb", "-s", DEVICE, "forward", "--remove", "tcp:51001") in device.calls
    assert not any("stale" in str(r.url) and r.url.path.endswith("getIsolate") for r in device.rpc)


@pytest.mark.parametrize("attribute,reason", [
    ("installed", "not installed"), ("debug", "not debuggable"), ("connected", "disconnected"),
])
async def test_unavailable_targets_block_before_launch(device, attribute, reason):
    setattr(device, attribute, False)
    result = await android.prepare_android(DEVICE, APP)
    assert result["status"] == "blocked"
    assert reason in result["reason"]
    assert not device.launched
    assert not device.forwards


async def test_wrong_avd_on_existing_serial_is_not_used(device):
    result = await android.prepare_android(DEVICE, APP, avd_name="Another_AVD")
    assert result["status"] == "blocked"
    assert "different AVD" in result["reason"]
    assert not device.launched


async def test_missing_avd_is_not_created(device):
    device.connected = False
    result = await android.prepare_android(DEVICE, APP, avd_name="Missing_AVD")
    assert result["status"] == "blocked"
    assert "AVD not found" in result["reason"]
    assert not device.spawn


async def test_am_start_error_with_zero_exit_code_is_not_success(device):
    device.launcher_error = True
    result = await android.prepare_android(DEVICE, APP)
    assert result["status"] == "blocked"
    assert "could not launch" in result["reason"]
    assert not device.forwards


@pytest.mark.parametrize("attribute,phase", [("missing_extensions", "vm_service"), ("booted", "boot")])
async def test_timeout_is_not_ready_and_removes_owned_forward(device, monkeypatch, attribute, phase):
    setattr(device, attribute, attribute == "missing_extensions")
    real_timeout = asyncio.timeout
    monkeypatch.setattr(android.asyncio, "timeout", lambda _: real_timeout(0.03))
    result = await android.prepare_android(DEVICE, APP)
    assert result["status"] == "blocked"
    assert phase in result["reason"]
    assert "vm_uri" not in result
    if device.forwards:
        assert ("adb", "-s", DEVICE, "forward", "--remove", "tcp:51001") in device.calls


async def test_cancel_during_probe_removes_forward(device, monkeypatch):
    async def cancel(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(android.AndroidPreparation, "probe", cancel)
    with pytest.raises(asyncio.CancelledError):
        await android.prepare_android(DEVICE, APP)
    assert ("adb", "-s", DEVICE, "forward", "--remove", "tcp:51001") in device.calls


@pytest.mark.parametrize("device_id,app_id", [("-bad", APP), (DEVICE, "demo; echo unsafe")])
async def test_invalid_identifiers_never_reach_adb(device, device_id, app_id):
    result = await android.prepare_android(device_id, app_id)
    assert result["status"] == "blocked"
    assert not device.calls


async def test_permission_failure_is_reported_without_raw_sdk_output(monkeypatch):
    class Process:
        returncode = 1

        async def communicate(self):
            return b"", b"Operation not permitted; private log data"

    async def create(*args, **kwargs):
        return Process()

    monkeypatch.setattr(android.asyncio, "create_subprocess_exec", create)
    with pytest.raises(android.PreparationError, match="access denied") as error:
        await android.command("adb", "devices")
    assert "private" not in str(error.value)


async def test_command_cancellation_reaps_process(monkeypatch):
    class Process:
        returncode = None
        reaped = False

        async def communicate(self):
            if self.returncode is None:
                raise asyncio.CancelledError
            self.reaped = True
            return b"", b""

        def kill(self):
            self.returncode = -9

    process = Process()

    async def create(*args, **kwargs):
        return process

    monkeypatch.setattr(android.asyncio, "create_subprocess_exec", create)
    with pytest.raises(asyncio.CancelledError):
        await android.command("adb", "devices")
    assert process.reaped
