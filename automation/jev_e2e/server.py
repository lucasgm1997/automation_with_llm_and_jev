import asyncio
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .android import prepare_android
from .app import execute
from .driver import connect
from .task import (
    DEFAULT_MIN_CONFIDENCE,
    Condition,
    ConfidenceThreshold,
    InputSpec,
    UITask,
)

server = FastMCP(
    "jev-flutter-e2e",
    instructions=(
        "For installed Android debug apps without a current VM URI, call prepare_android_app "
        "with device_id and app_id; include avd_name if the emulator needs to start. "
        "Use its returned vm_uri with inspect_ui and run_ui_task. Preparation is not a test result. "
        "For natural-language UI tests, inspect_ui and/or read the app source, then call "
        "run_ui_task once with the user's goal, input fixtures and observable success_conditions. "
        "Derive real semantic IDs; do not invent them. Define assertions that prove the requested "
        "result, not merely that a button is visible. Jev owns the inner action loop. "
        "If the user specifies a confidence threshold, pass it as min_confidence; "
        "mentioning it only in goal does not configure the executor. "
        "Use input env references for credentials."
    ),
)
run_lock = asyncio.Lock()


@server.tool()
async def prepare_android_app(
    device_id: str,
    app_id: str,
    avd_name: str | None = None,
    timeout_seconds: Annotated[int, Field(ge=5, le=300)] = 120,
) -> dict[str, Any]:
    """Open an installed Android debug APK and return its current host VM URI.

    Works without flutter run, flutter attach or an attached IDE. If device_id
    is disconnected, avd_name starts that existing emulator on the requested
    emulator-N port. Never installs, clears data, force-stops or restarts an
    existing app. An existing app is brought to the foreground with its state.
    Discovers the service from the current app PID's logs, forwards a free host
    port and verifies the live PID and E2E extensions. Requires SDK/ADB access.
    ready means connected, not a passed journey: next inspect_ui then run_ui_task.
    Preparation has its own timeout; it does not consume the 40-second test budget.
    Leaves the app, emulator and successful port forwarding available for testing.
    """
    if run_lock.locked():
        return {"status": "busy"}
    async with run_lock:
        return await prepare_android(device_id, app_id, avd_name, timeout_seconds)


@server.tool()
async def inspect_ui(vm_uri: str) -> dict[str, Any]:
    """Read the current identified semantics to prepare a UI task.

    Returns IDs, labels, supported actions and field state. Omits text-field
    values; read the app source to identify destination nodes for assertions.
    The app must be running in debug with e2e_snapshot v2 installed.
    """
    if run_lock.locked():
        return {"status": "busy"}
    async with run_lock, asyncio.timeout(20), connect(vm_uri) as driver:
        snapshot = await driver.snapshot()
        for node in snapshot["nodes"]:
            if node.get("role") == "textField":
                node["value"] = "<redacted>"
        return snapshot


@server.tool()
async def run_ui_task(
    vm_uri: str,
    goal: str,
    success_conditions: list[Condition],
    inputs: list[InputSpec] | None = None,
    allowed_targets: list[str] | None = None,
    max_steps: int = 30,
    model: str = "jev-latest",
    min_confidence: ConfidenceThreshold = DEFAULT_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Run an arbitrary UI goal using semantic tap/fill actions chosen by Jev.

    Requires debug extensions e2e_snapshot v2 and e2e_action. Controls need
    unique Semantics.identifier values, not widget keys. Taps use accessibility
    actions; this mode does not validate physical pointer hit testing.

    Interpret the user's natural-language request into goal, input fixtures,
    and observable success_conditions after inspecting UI/source. No per-journey
    Python code is required. Inputs have name, description and either value or
    env; optional target binds one to a semantic field. Examples of conditions:
    {target: 'products.title', check: 'exists'} or
    {target: 'products.list', check: 'label_contains', input_ref: 'product_name'}.
    These are examples: use IDs actually present in this app. Credentials should
    be env references, not embedded in goal. No model-generated free-text input.
    min_confidence is the inclusive local acceptance threshold (0 to 1, default
    0.6). Map a user request such as "use confidence 0.6" to min_confidence=0.6,
    not just goal text. Below it, stop as blocked before acting. This does not
    change Jev's returned confidence or bypass independent UI assertions.
    Returns assertions and evidence; blocked means the test did not pass.
    """
    task = UITask(
        goal=goal,
        inputs=inputs or [],
        success_conditions=success_conditions,
        allowed_targets=allowed_targets,
        max_steps=max_steps,
        min_confidence=min_confidence,
    )
    if run_lock.locked():
        return {"status": "busy"}
    async with run_lock:
        return await execute(vm_uri, model=model, task=task)


def main():
    server.run(transport="stdio")
