"""Shared validation for semantic observations used by the driver and UI runner."""

import hashlib
import json


class RunStopped(Exception):
    """A controlled stop that must not be mistaken for an assertion pass."""


def validate_snapshot(snapshot: dict) -> dict:
    if snapshot.get("schema_version") != 2:
        raise RunStopped(
            "Expected semantic snapshot v2; update the Flutter instrumentation and hot restart."
        )
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
