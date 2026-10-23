import asyncio
import math
from time import perf_counter

from .semantics import RunStopped, fingerprint, validate_snapshot
from .task import TaskValues, UITask, action_candidates, evaluate


class UIRunner:
    def __init__(self, driver, policy, task: UITask, values: TaskValues, report: dict):
        self.driver, self.policy, self.task, self.values = driver, policy, task, values
        self.report = report
        self.report["min_confidence"] = task.min_confidence
        self.events = report.setdefault("events", [])
        self.filled = {}

    async def timed(self, phase, operation):
        started = perf_counter()
        try:
            return await operation
        finally:
            self.events.append(
                {"phase": phase, "ms": round((perf_counter() - started) * 1000, 2)}
            )

    async def observe(self):
        started = perf_counter()
        while True:
            snapshot = await self.timed("snapshot", self.driver.snapshot())
            validate_snapshot(snapshot)
            self.events.append({"snapshot": self.values.redact(snapshot)})
            if snapshot["nodes"]:
                return snapshot
            # Flutter route transitions can temporarily hide both routes from
            # accessibility. Waiting here avoids an inference over an empty UI.
            if perf_counter() - started >= 3:
                raise RunStopped(
                    "No identified semantic nodes became available within 3 seconds."
                )
            await asyncio.sleep(0.05)

    def checks(self, snapshot, baseline):
        checks = evaluate(self.task, snapshot, baseline, self.values)
        self.report["assertions"] = self.values.redact(checks)
        return checks

    async def run(self):
        snapshot = baseline = await self.observe()
        checks = self.checks(snapshot, baseline)
        self.report.update(actions=0, goal=self.values.redact(self.task.goal))
        if all(c["passed"] for c in checks):
            self.report.update(
                status="already_satisfied",
                reason="Conditions already held before any action; no test journey was executed.",
            )
            return
        for step in range(self.task.max_steps):
            candidates = action_candidates(
                self.task, snapshot, self.values, self.filled
            )
            waiting_since = perf_counter()
            while len(candidates) == 2:
                # Route transitions may leave outgoing nodes in the tree with
                # all gestures disabled before the destination becomes visible.
                # No inference is needed when there is no executable UI action.
                if perf_counter() - waiting_since >= 3:
                    raise RunStopped(
                        "No executable UI action became available within 3 seconds."
                    )
                await asyncio.sleep(0.05)
                snapshot = await self.observe()
                checks = self.checks(snapshot, baseline)
                if all(c["passed"] for c in checks):
                    self.report.update(
                        status="passed", reason="All UI assertions hold."
                    )
                    return
                candidates = action_candidates(
                    self.task, snapshot, self.values, self.filled
                )
            state = self.values.redact(
                {
                    "goal": self.task.goal,
                    "ui": snapshot,
                    "success_conditions": checks,
                    "inputs": [
                        {
                            "name": item.name,
                            "description": item.description,
                            "target": item.target,
                        }
                        for item in self.task.inputs
                    ],
                    "verified_transitions": [
                        e["transition"] for e in self.events if "transition" in e
                    ][-5:],
                }
            )
            decision = await self.timed(
                self.report.get("policy", "jev"),
                self.policy.choose(state, self.values.redact(candidates)),
            )
            selected = decision.get("action")
            confidence = decision.get("confidence")
            if not isinstance(selected, str) or selected not in candidates:
                raise RunStopped(
                    "Policy selected an action outside the observed candidates."
                )
            action = candidates[selected]
            self.events.append(
                {
                    "step": step,
                    "decision": self.values.redact(decision),
                    "action": self.values.redact(action),
                }
            )
            if (
                type(confidence) not in {int, float}
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise RunStopped("Policy returned invalid confidence.")
            if confidence < self.task.min_confidence:
                raise RunStopped(
                    f"Policy confidence {confidence} below configured "
                    f"min_confidence {self.task.min_confidence}."
                )
            if action["operation"] == "blocked":
                raise RunStopped(
                    "No useful action identified; return evidence to the calling agent."
                )
            if action["operation"] == "wait":
                await asyncio.sleep(0.15)
                snapshot = await self.observe()
            else:
                fresh = await self.observe()
                if fingerprint(fresh) != fingerprint(snapshot):
                    self.events.append({"discarded": "UI changed during inference"})
                    snapshot = fresh
                    checks = self.checks(snapshot, baseline)
                    if all(c["passed"] for c in checks):
                        self.report.update(
                            status="passed", reason="All UI assertions hold."
                        )
                        return
                    continue
                if action["operation"] == "tap":
                    await self.timed("tap", self.driver.tap(action["target"]))
                else:
                    await self.timed(
                        "fill",
                        self.driver.fill(
                            action["target"], self.values.values[action["input"]]
                        ),
                    )
                    self.filled[action["target"]] = action["input"]
                self.report["actions"] += 1
                started = perf_counter()
                while True:
                    updated = await self.observe()
                    if fingerprint(updated) != fingerprint(snapshot):
                        break
                    if perf_counter() - started > 3:
                        raise RunStopped(
                            "No semantic change after action; not retrying an ambiguous interaction."
                        )
                    await asyncio.sleep(0.08)
                snapshot = updated
                self.events.append(
                    {
                        "transition": self.values.redact(
                            {"action": action, "semantic_change": True}
                        )
                    }
                )
            checks = self.checks(snapshot, baseline)
            if all(c["passed"] for c in checks):
                self.report.update(status="passed", reason="All UI assertions hold.")
                return
        raise RunStopped("Step budget exhausted before all assertions passed.")
