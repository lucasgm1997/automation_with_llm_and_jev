import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

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
