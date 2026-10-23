import asyncio
import json
from contextlib import asynccontextmanager
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from jev_e2e.android_driver import connect_android
from jev_e2e.android_ui import parse_hierarchy
from jev_e2e.android_worker import AndroidSession
from jev_e2e.driver import connect
from jev_e2e.semantics import RunStopped

APP = "com.example.demo"


def hierarchy(*items):
    root = Element("hierarchy")
    for item in items:
        SubElement(root, "node", {
            "package": APP, "class": "android.widget.Button", "resource-id": "next",
            "bounds": "[10,20][100,200]", "visible-to-user": "true", "enabled": "true",
            "clickable": "true", **item,
        })
    return tostring(root, encoding="unicode")


def test_native_fields_unicode_checkboxes_and_package_filter():
    xml = hierarchy(
        {"resource-id": "name", "class": "android.widget.EditText", "hint": "Nome", "text": "São Paulo"},
        {"resource-id": "terms", "class": "android.widget.CheckBox", "content-desc": "Aceito", "checkable": "true", "checked": "true"},
        {"resource-id": "foreign", "package": "another.app"},
        {"resource-id": "hidden", "visible-to-user": "false"},
    )
    snapshot, selectors = parse_hierarchy(xml, APP)
    field, checkbox = snapshot["nodes"]
    assert field["value"] == "São Paulo"
    assert field["label"] == "Nome"
    assert field["actions"] == ["fill"]
    assert checkbox["checked"] is True
    assert checkbox["value"] == "true"
    assert set(selectors) == {"name", "terms"}
    assert selectors["name"]["packageName"] == APP


def test_password_never_appears_in_snapshot_or_selector():
    snapshot, selectors = parse_hierarchy(hierarchy({
        "class": "android.widget.EditText", "password": "true", "text": "secret",
    }), APP)
    assert "secret" not in json.dumps([snapshot, selectors])
    assert snapshot["nodes"][0]["is_empty"] is False
    assert snapshot["nodes"][0]["obscured"] is True


def test_disabled_nodes_have_no_actions_and_non_id_text_has_stable_identity():
    first, selectors = parse_hierarchy(hierarchy({"resource-id": "", "text": "Continuar", "enabled": "false"}), APP)
    second, _ = parse_hierarchy(hierarchy({"resource-id": "", "text": "Continuar", "enabled": "true"}), APP)
    assert first["nodes"][0]["id"] == second["nodes"][0]["id"]
    assert first["nodes"][0]["actions"] == []
    assert next(iter(selectors.values()))["text"] == "Continuar"


@pytest.mark.parametrize("xml,reason", [
    (hierarchy({}, {}), "Ambiguous"),
    (hierarchy({"resource-id": ""}), "stable"),
    (hierarchy({"bounds": "bad"}), "bounds"),
    ("<!DOCTYPE x><hierarchy/>", "declarations"),
    ("<broken", "Invalid"),
])
def test_unreliable_hierarchies_fail_closed(xml, reason):
    with pytest.raises(RunStopped, match=reason):
        parse_hierarchy(xml, APP)


@pytest.mark.parametrize("info,count,foreground", [
    ({"enabled": True}, 2, APP),
    ({"enabled": False}, 1, APP),
    ({"enabled": True}, 1, "other.app"),
])
def test_action_rechecks_target_before_any_mutation(info, count, foreground):
    pytest.importorskip("uiautomator2")
    session = AndroidSession.__new__(AndroidSession)
    session.app_id = APP
    session.nodes = {"next": {"actions": ["tap"]}}
    session.selectors = {"next": {"resourceId": "next", "packageName": APP}}
    calls = []
    def rpc(method, *args):
        calls.append(method)
        return {"deviceInfo": {"currentPackageName": foreground}, "count": count, "objInfo": info}[method]
    session.rpc = rpc
    with pytest.raises(RunStopped):
        session.act("tap", "next")
    assert "click" not in calls


def test_uncertain_mutation_is_not_retried():
    pytest.importorskip("uiautomator2")
    session = AndroidSession.__new__(AndroidSession)
    session.app_id = APP
    session.nodes = {"next": {"actions": ["tap"]}}
    session.selectors = {"next": {"resourceId": "next", "packageName": APP}}
    calls = []
    def rpc(method, *args):
        calls.append(method)
        if method == "click":
            raise OSError("Connection lost after sending")
        return {"deviceInfo": {"currentPackageName": APP}, "count": 1,
                "objInfo": {"enabled": True, "bounds": {"left": 0, "top": 0, "right": 50, "bottom": 50}}}[method]
    session.rpc = rpc
    with pytest.raises(OSError):
        session.act("tap", "next")
    assert calls.count("click") == 1


async def test_cancelled_worker_is_killed_before_scope_exits(monkeypatch):
    class Pipe:
        def write(self, value):
            pass
        async def drain(self):
            pass
        async def readline(self):
            return b'{"result":{"ready":true}}\n'
    class Process:
        stdin = stdout = Pipe()
        returncode = None
        killed = False
        def kill(self):
            self.killed = True
            self.returncode = -9
        async def wait(self):
            return self.returncode
    process = Process()
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(asyncio.CancelledError):
        async with connect_android("emulator-5556", APP):
            raise asyncio.CancelledError
    assert process.killed


@pytest.mark.parametrize("options", [
    {"backend": "invalid"},
    {"backend": "uiautomator2"},
    {"backend": "uiautomator2", "uri": "http://localhost:1/token"},
    {"backend": "marionette"},
])
async def test_bad_backend_config_never_starts_worker(monkeypatch, options):
    async def spawn(*args, **kwargs):
        pytest.fail("Invalid config must not start a worker")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ValueError):
        async with connect(**options):
            pytest.fail("Invalid config must not yield a driver")


async def test_mcp_android_arguments_and_inspection_redaction(monkeypatch):
    from jev_e2e import server
    from jev_e2e.task import Condition

    @asynccontextmanager
    async def connection(uri, **options):
        assert uri is None
        assert options == {"backend": "uiautomator2", "device_id": "emulator-5556", "app_id": APP}
        class Driver:
            async def snapshot(self):
                return {"schema_version": 2, "nodes": [{"id": "field", "role": "textField", "value": "secret"}]}
        yield Driver()
    async def execute(uri, **options):
        assert uri is None
        assert options["backend"] == "uiautomator2"
        assert options["device_id"] == "emulator-5556"
        assert options["app_id"] == APP
        assert options["task"].min_confidence == 0.55
        assert options["task"].max_steps == 60
        return {"status": "blocked"}
    monkeypatch.setattr(server, "connect", connection)
    monkeypatch.setattr(server, "execute", execute)
    args = {"backend": "uiautomator2", "device_id": "emulator-5556", "app_id": APP}
    result = await server.inspect_ui(**args)
    assert result["nodes"][0]["value"] == "<redacted>"
    result = await server.run_ui_task(
        **args, goal="Finish test journey", success_conditions=[Condition(target="result", check="exists")],
        min_confidence=0.55, max_steps=60,
    )
    assert result["status"] == "blocked"
