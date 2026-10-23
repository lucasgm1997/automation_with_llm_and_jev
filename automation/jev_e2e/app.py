import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
from dotenv import dotenv_values

from .driver import connect
from .policy import JevPolicy
from .semantics import RunStopped
from .task import TaskValues, UITask
from .ui_runner import UIRunner

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


async def execute(
    vm_uri: str,
    *,
    task: UITask,
    model: str = "jev-latest",
) -> dict:
    # Re-read per run without mutating the persistent MCP server environment.
    config = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.environ.get("TYPESAFE_API_KEY") or config.get("TYPESAFE_API_KEY")
    dart = os.environ.get("DART_BIN") or config.get("DART_BIN")
    report = {
        "scenario": "ui_task",
        "policy": "jev",
        "status": "failed",
        "min_confidence": task.min_confidence,
        "events": [],
    }
    started = perf_counter()
    selected = None
    values = None
    try:
        values = TaskValues(task, {**config, **os.environ})
        # Includes process startup, connection, inference and UI interactions.
        async with asyncio.timeout(40):
            async with httpx.AsyncClient(http2=True, timeout=10) as client:
                selected = JevPolicy(client, model, api_key)
                async with connect(vm_uri, dart) as driver:
                    report["setup_ms"] = round((perf_counter() - started) * 1000, 2)
                    try:
                        await UIRunner(driver, selected, task, values, report).run()
                    except RunStopped as exc:
                        report.update(status="blocked", reason=str(exc))
                    except (RuntimeError, ValueError) as exc:
                        report.update(status="failed", reason=str(exc))
    except RunStopped as exc:
        report.update(status="blocked", reason=str(exc))
    except TimeoutError:
        report.update(
            status="timeout",
            reason="40-second run budget exhausted; inspect state before retrying.",
        )
    except asyncio.CancelledError:
        report.update(
            status="cancelled",
            reason="Caller cancelled the run; inspect state before retrying.",
        )
        raise
    except (ValueError, RuntimeError) as exc:
        # These are our explicit configuration/API errors, without response bodies.
        report.update(status="failed", reason=str(exc))
    except Exception as exc:  # noqa: BLE001 -- Always return a failed run with an artifact.
        # MCP context managers may wrap transport errors in ExceptionGroup.
        report.update(
            status="failed",
            reason=f"Transport or response failure ({type(exc).__name__}); verify the VM URI, Dart SDK and debug extension.",
        )
    finally:
        if values is not None:
            report = values.redact(report)
        report["total_ms"] = round((perf_counter() - started) * 1000, 2)
        report["model"] = selected.actual_model if selected else model
        timings = {}
        for event in report["events"]:
            if "phase" in event:
                timings.setdefault(event["phase"], []).append(event["ms"])
        report["timings"] = {
            name: {
                "calls": len(values),
                "total_ms": round(sum(values), 2),
                "mean_ms": round(sum(values) / len(values), 2),
            }
            for name, values in timings.items()
        }
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = ARTIFACTS / f"{stamp}-{uuid4().hex[:8]}.json"
        report["artifact"] = str(path)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return {key: value for key, value in report.items() if key != "events"}
