import json

import pytest

from jev_e2e import __main__ as cli


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

    async def fake_execute(vm_uri, *, task, model):
        assert vm_uri == "unused"
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
