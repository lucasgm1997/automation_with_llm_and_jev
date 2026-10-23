"""Scenario data and assertions supplied by the caller, never scenario code."""

import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .semantics import RunStopped, validate_snapshot


DEFAULT_MIN_CONFIDENCE = 0.6
ConfidenceThreshold = Annotated[
    float,
    Field(
        strict=True,
        ge=0,
        le=1,
        allow_inf_nan=False,
        description="Minimum returned Jev confidence accepted by the local executor (inclusive).",
    ),
]


class InputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    description: str = Field(min_length=1, max_length=300)
    value: str | None = Field(default=None, repr=False, max_length=2000)
    env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    target: str | None = Field(
        default=None, description="Optional exact semantic field ID"
    )

    @model_validator(mode="after")
    def source(self):
        if (self.value is None) == (self.env is None):
            raise ValueError("Each input needs exactly one of value or env.")
        return self


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1)
    check: Literal[
        "exists", "absent", "value_equals", "label_contains", "value_increased_by"
    ]
    expected: str | int | None = None
    input_ref: str | None = None

    @model_validator(mode="after")
    def operands(self):
        if self.check in {"exists", "absent"}:
            if self.expected is not None or self.input_ref is not None:
                raise ValueError("exists/absent do not take operands")
        elif self.check == "value_increased_by":
            if type(self.expected) is not int or self.input_ref is not None:
                raise ValueError("value_increased_by needs an integer expected delta")
        elif (self.expected is None) == (self.input_ref is None):
            raise ValueError("Supply exactly one of expected or input_ref")
        if self.check == "label_contains" and self.expected == "":
            raise ValueError("An empty contains assertion cannot verify a result")
        return self


class UITask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=3, max_length=4000)
    inputs: list[InputSpec] = Field(default_factory=list, max_length=20)
    success_conditions: list[Condition] = Field(min_length=1, max_length=20)
    allowed_targets: list[str] | None = None
    max_steps: int = Field(default=30, ge=1, le=60)
    min_confidence: ConfidenceThreshold = DEFAULT_MIN_CONFIDENCE

    @model_validator(mode="after")
    def names(self):
        names = [item.name for item in self.inputs]
        if len(set(names)) != len(names):
            raise ValueError("Input names must be unique")
        if any(
            c.input_ref and c.input_ref not in names for c in self.success_conditions
        ):
            raise ValueError("Assertion references an unknown input")
        return self


class TaskValues:
    def __init__(self, task: UITask, environment: dict):
        self.values = {}
        for item in task.inputs:
            value = item.value if item.value is not None else environment.get(item.env)
            if value is None:
                raise RunStopped(
                    f"Missing local environment variable for input {item.name!r}."
                )
            self.values[item.name] = value
        self.replacements = {
            raw: f"<input:{name}>" for name, raw in self.values.items() if raw
        }
        self.pattern = (
            re.compile(
                "|".join(
                    re.escape(raw)
                    for raw in sorted(self.replacements, key=len, reverse=True)
                )
            )
            if self.replacements
            else None
        )

    def redact(self, value):
        if isinstance(value, str):
            if self.pattern is None:
                return value
            # Preserve existing markers when sanitizing an already-clean trace.
            parts = re.split(r"(<input:[a-zA-Z][a-zA-Z0-9_]*>)", value)
            return "".join(
                part
                if index % 2
                else self.pattern.sub(
                    lambda match: self.replacements[match.group()], part
                )
                for index, part in enumerate(parts)
            )
        if isinstance(value, dict):
            structural = {
                "id",
                "parent",
                "target",
                "role",
                "operation",
                "input",
                "name",
                "check",
                "action",
                "model",
                "phase",
                "status",
            }
            return {
                key: item if key in structural else self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value


def evaluate(
    task: UITask, snapshot: dict, baseline: dict, values: TaskValues
) -> list[dict]:
    nodes = validate_snapshot(snapshot)
    initial_nodes = validate_snapshot(baseline)
    checks = []
    for condition in task.success_conditions:
        node = nodes.get(condition.target)
        expected = (
            values.values[condition.input_ref]
            if condition.input_ref
            else condition.expected
        )
        observed = None
        if condition.check in {"exists", "absent"}:
            observed = node is not None
            passed = observed == (condition.check == "exists")
        elif condition.check == "label_contains":
            observed = node.get("label", "") if node else None
            passed = (
                bool(expected) and observed is not None and str(expected) in observed
            )
        elif condition.check == "value_equals":
            observed = node.get("value") if node else None
            passed = (
                node is not None
                and not node.get("obscured", False)
                and observed == str(expected)
            )
        else:
            try:
                initial = int(initial_nodes[condition.target]["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RunStopped(
                    "A delta assertion requires a numeric value in the initial UI."
                ) from exc
            expected = initial + int(expected)
            observed = node.get("value") if node else None
            passed = observed == str(expected)
        checks.append(
            {
                "target": condition.target,
                "check": condition.check,
                "expected": expected,
                "observed": observed,
                "passed": passed,
            }
        )
    return checks


def action_candidates(
    task: UITask, snapshot: dict, values: TaskValues, filled: dict
) -> dict:
    candidates = {
        "wait": {
            "operation": "wait",
            "description": "UI is visibly loading or transitioning; wait for it to become actionable.",
        },
        "blocked": {
            "operation": "blocked",
            "description": "No visible action or navigation can advance the unmet goal; return evidence.",
        },
    }
    for node in validate_snapshot(snapshot).values():
        target = node["id"]
        if task.allowed_targets is not None and target not in task.allowed_targets:
            continue
        if node.get("enabled") is not True:
            continue
        if "fill" in node.get("actions", []):
            for item in task.inputs:
                if item.target is not None and item.target != target:
                    continue
                raw = values.values[item.name]
                already_filled = (
                    node.get("value") == raw
                    if not node.get("obscured")
                    else filled.get(target) == item.name
                    and not node.get("is_empty", True)
                )
                if already_filled:
                    continue
                candidates[f"a{len(candidates)}"] = {
                    "operation": "fill",
                    "target": target,
                    "label": node.get("label", ""),
                    "input": item.name,
                    "description": item.description,
                }
        # A fill already focuses its field. Don't offer redundant focus taps.
        elif "tap" in node.get("actions", []):
            candidates[f"a{len(candidates)}"] = {
                "operation": "tap",
                "target": target,
                "label": node.get("label", ""),
            }
    if len(candidates) > 255 or len(json.dumps(candidates)) > 20000:
        raise RunStopped(
            "Too many candidate actions; scope allowed_targets or bind inputs to fields."
        )
    return candidates
