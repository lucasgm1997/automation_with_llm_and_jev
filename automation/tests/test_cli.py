import json

import pytest

from jev_e2e import __main__ as cli


@pytest.mark.parametrize("args,expected", [
    ([], {"transport": "stdio", "host": "127.0.0.1", "port": 8765}),
    (["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8766"],
     {"transport": "streamable-http", "host": "0.0.0.0", "port": 8766}),
])
def test_serve_cli_selects_transport(monkeypatch, args, expected):
    calls = []
    monkeypatch.setattr("jev_e2e.server.main", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr("sys.argv", ["jev_e2e", "serve", *args])
    cli.main()
    assert calls == [expected]


@pytest.mark.parametrize("port", ["0", "65536"])
def test_serve_cli_rejects_invalid_port(monkeypatch, port):
    monkeypatch.setattr("sys.argv", ["jev_e2e", "serve", "--port", port])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 2


@pytest.mark.parametrize("status,exit_code", [("passed", 0), ("blocked", 1)])
def test_task_cli_passes_spec_to_executor_and_returns_status(
    monkeypatch, tmp_path, capsys, status, exit_code,
):
    spec = tmp_path / "journey.json"
    spec.write_text(json.dumps({
        "goal": "Open the account page",
        "success_conditions": [{"target": "account.home", "check": "exists"}],
        "min_confidence": 0.8,
    }))

    async def fake_execute(vm_uri, *, task, model, provider):
        assert vm_uri == "unused"
        assert provider == "jev"
        assert model == "jev-test"
        assert task.min_confidence == 0.8
        assert task.success_conditions[0].target == "account.home"
        return {"status": status}

    monkeypatch.setattr(cli, "execute", fake_execute)
    monkeypatch.setattr("sys.argv", [
        "jev_e2e", "task", "--vm-uri", "unused", "--spec", str(spec),
        "--model", "jev-test",
    ])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == exit_code
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_cli_selects_openai_and_overrides_threshold_without_changing_spec(monkeypatch, tmp_path):
    spec = tmp_path / "journey.json"
    content = json.dumps({
        "goal": "Open the account page",
        "success_conditions": [{"target": "account.home", "check": "exists"}],
        "max_steps": 60,
        "min_confidence": 0.8,
    })
    spec.write_text(content)

    async def fake_execute(vm_uri, *, task, model, provider):
        assert provider == "openai"
        assert model is None  # The executor resolves the provider's default.
        assert task.min_confidence == 0.55
        assert task.max_steps == 60
        return {"status": "passed"}

    monkeypatch.setattr(cli, "execute", fake_execute)
    monkeypatch.setattr("sys.argv", [
        "jev_e2e", "task", "--vm-uri", "unused", "--spec", str(spec),
        "--provider", "openai", "--min-confidence", "0.55",
    ])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    assert spec.read_text() == content


@pytest.mark.parametrize("status,exit_code", [("ready", 0), ("blocked", 1)])
def test_prepare_cli_reports_connection_status(monkeypatch, capsys, status, exit_code):
    async def prepare(device_id, app_id, avd_name, timeout_seconds):
        assert (device_id, app_id, avd_name, timeout_seconds) == (
            "emulator-5556", "com.example.demo", "Test_AVD", 150,
        )
        return {"status": status}

    monkeypatch.setattr(cli, "prepare_android", prepare)
    monkeypatch.setattr("sys.argv", [
        "jev_e2e", "prepare-android", "--device-id", "emulator-5556",
        "--app-id", "com.example.demo", "--avd-name", "Test_AVD", "--timeout-seconds", "150",
    ])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == exit_code
    assert json.loads(capsys.readouterr().out)["status"] == status
