"""Android accessibility observations, independent of the app's UI framework."""

import hashlib
import re
from xml.etree import ElementTree as ET

from .semantics import RunStopped, validate_snapshot


def parse_hierarchy(xml: str, app_id: str) -> tuple[dict, dict]:
    if len(xml) > 1_000_000 or "<!DOCTYPE" in xml or "<!ENTITY" in xml:
        raise RunStopped("Android hierarchy exceeds limits or contains unsupported declarations.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise RunStopped("Invalid Android accessibility hierarchy.") from exc
    nodes, selectors = [], {}
    for element in root.iter("node"):
        a = element.attrib
        if a.get("package") != app_id or a.get("visible-to-user") == "false":
            continue
        klass = a.get("class", "")
        editable = klass.endswith("EditText")
        password = a.get("password") == "true"
        text = a.get("text", "")
        description = a.get("content-desc", "")
        hint = a.get("hint", "")
        clickable = a.get("clickable") == "true"
        if not (editable or clickable or text or description):
            continue
        identifier = a.get("resource-id", "")
        selector = {"packageName": app_id, "className": klass}
        if identifier:
            selector["resourceId"] = identifier
        elif description:
            selector["description"] = description
        elif text and not editable and not password:
            selector["text"] = text
        else:
            # No coordinate/path-only fallback: editing must retain a stable target.
            raise RunStopped("Android control has no stable resource ID, text or description.")
        if not identifier:
            identifier = "android:" + hashlib.sha256(repr(sorted(selector.items())).encode()).hexdigest()[:16]
        if identifier in selectors:
            raise RunStopped("Ambiguous Android identifier; expose unique IDs or narrow the UI.")
        bounds = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", a.get("bounds", ""))
        if not bounds:
            raise RunStopped("Android control has invalid bounds.")
        left, top, right, bottom = map(int, bounds.groups())
        if right <= left or bottom <= top:
            continue
        enabled = a.get("enabled") == "true"
        checkable = a.get("checkable") == "true"
        node = {
            "id": identifier,
            "role": "textField" if editable else "checkbox" if checkable else "button" if clickable else "text",
            "label": (description or hint) if editable else "\n".join(dict.fromkeys(v for v in (description, text) if v)),
            "enabled": enabled,
            "actions": (["fill"] if editable else ["tap"] if clickable else []) if enabled else [],
            "bounds": [left, top, right, bottom],
        }
        if editable:
            node.update(value="" if password else text, obscured=password,
                        is_empty=not text, focused=a.get("focused") == "true")
        if checkable:
            node.update(checked=a.get("checked") == "true", value="true" if a.get("checked") == "true" else "false")
        nodes.append(node)
        selectors[identifier] = selector
    snapshot = {"schema_version": 2, "nodes": nodes}
    validate_snapshot(snapshot)
    return snapshot, selectors
