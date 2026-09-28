import asyncio
import hashlib
import json
import math
from time import perf_counter


class RunStopped(Exception):
    """A controlled stop that must not be mistaken for an assertion pass."""


def validate_snapshot(snapshot: dict) -> dict:
    if snapshot.get("schema_version") != 1:
        raise RunStopped("Unsupported semantic snapshot version.")
    nodes = snapshot.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 200:
        raise RunStopped("Expected at most 200 identified semantic nodes.")
    by_id = {}
    for node in nodes:
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in by_id:
            raise RunStopped("Missing or duplicate semantic identifier.")
        by_id[identifier] = node
    if len(json.dumps(snapshot)) > 16000:
        raise RunStopped(
            "Snapshot exceeds the MVP context budget; narrow the semantic contract."
        )
    return by_id


def fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def counter_value(snapshot: dict) -> int:
    nodes = validate_snapshot(snapshot)
    try:
        return int(nodes["counter.value"]["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RunStopped(
            "counter.value must expose an integer semantic value."
        ) from exc


def allowed_actions(snapshot: dict) -> dict:
    # Per-scenario allowlist. A newly appearing control is never automatically
    # permission to click it, even if the policy selects its identifier.
    nodes = validate_snapshot(snapshot)
    actions = {
        "wait": "Wait briefly if the app is in a transient state.",
        "blocked": "Stop and return evidence when no allowed action can advance the goal.",
    }
    node = nodes.get("counter.increment", {})
    if (
        node.get("enabled") is True
        and node.get("key_count") == 1
        and "tap" in node.get("actions", [])
    ):
        actions["tap:counter.increment"] = {
            "operation": "tap",
            "target": "counter.increment",
            "label": node.get("label", ""),
        }
    return actions


class CounterRunner:
    def __init__(
        self,
        driver,
        policy,
        report: dict,
        *,
        max_steps: int = 12,
        min_confidence: float = 0.7,
    ):
        self.driver = driver
        self.policy = policy
        self.report = report
        self.max_steps = max_steps
        self.min_confidence = min_confidence
        self.events = report.setdefault("events", [])

    async def timed(self, name, operation):
        start = perf_counter()
        try:
            return await operation
        finally:
            self.events.append(
                {"phase": name, "ms": round((perf_counter() - start) * 1000, 2)}
            )

    async def observe(self):
        state = await self.timed("snapshot", self.driver.snapshot())
        validate_snapshot(state)
        self.events.append({"snapshot": state, "fingerprint": fingerprint(state)})
        return state

    async def run(self, increments: int):
        if not 1 <= increments <= 10:
            raise RunStopped("increments must be between 1 and 10.")
        snapshot = await self.observe()
        initial = counter_value(snapshot)
        target = initial + increments
        self.report.update(initial=initial, expected=target, observed=initial, taps=0)
        for step in range(self.max_steps):
            observed = counter_value(snapshot)
            self.report["observed"] = observed
            if observed == target:
                self.report.update(
                    status="passed",
                    reason="Semantic value equals the independently computed target.",
                )
                return
            if observed < initial or observed > target:
                raise RunStopped("Counter moved outside the expected range.")
            actions = allowed_actions(snapshot)
            state = {
                "goal": "Increase the counter using the UI until remaining_increments is zero.",
                "remaining_increments": target - observed,
                "expected_value": target,
                "ui": snapshot,
                "verified_transitions": [
                    e["transition"] for e in self.events if "transition" in e
                ][-5:],
            }
            decision = await self.timed(
                "jev"
                if self.policy.actual_model != "scripted-no-model"
                else "scripted",
                self.policy.choose(state, actions),
            )
            action = decision.get("action")
            confidence = decision.get("confidence")
            if not isinstance(action, str) or action not in actions:
                raise RunStopped(
                    "Policy selected an action outside the current allowlist."
                )
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise RunStopped("Policy returned invalid confidence.")
            self.events.append({"step": step, "decision": decision})
            if confidence < self.min_confidence:
                raise RunStopped("Policy confidence below the configured threshold.")
            if action == "blocked":
                raise RunStopped(
                    "Policy could not find an allowed action to advance the goal."
                )
            if action == "wait":
                await asyncio.sleep(0.15)
                snapshot = await self.observe()
                continue

            # Re-read after inference. Discard a decision made against old UI.
            fresh = await self.observe()
            if fingerprint(fresh) != fingerprint(snapshot):
                self.events.append({"discarded": "UI changed during inference"})
                snapshot = fresh
                continue
            await self.timed("tap", self.driver.tap("counter.increment"))
            self.report["taps"] += 1

            # Poll for a real postcondition, not a fixed one-second sleep.
            # Never repeat a non-idempotent tap after an ambiguous result.
            started = perf_counter()
            while True:
                snapshot = await self.observe()
                current = counter_value(snapshot)
                self.report["observed"] = current
                if current != observed:
                    if current != observed + 1:
                        raise RunStopped(
                            "One tap did not increment the semantic counter by exactly one."
                        )
                    self.events.append(
                        {
                            "transition": {
                                "action": action,
                                "before": observed,
                                "after": current,
                            }
                        }
                    )
                    break
                if perf_counter() - started >= 2:
                    raise RunStopped(
                        "Tap produced no observed change within 2 seconds; no automatic retry."
                    )
                await asyncio.sleep(0.05)
            # The last permitted action is allowed to satisfy the goal.
            if current == target:
                self.report.update(
                    status="passed",
                    reason="Semantic value equals the independently computed target.",
                )
                return
        raise RunStopped("Step budget exhausted before the assertion passed.")
