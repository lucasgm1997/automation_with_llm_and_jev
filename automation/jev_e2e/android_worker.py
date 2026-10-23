"""One UI Automator service per run; isolated so cancellation stops pending work."""

import contextlib
import json
import logging
import sys

from .android_ui import parse_hierarchy
from .semantics import RunStopped


class AndroidSession:
    def __init__(self, device_id: str, app_id: str):
        import adbutils
        import uiautomator2

        self.app_id = app_id
        self.selectors = {}
        self.nodes = {}
        device = adbutils.AdbClient(socket_timeout=5).device(serial=device_id)
        self.device = uiautomator2.connect(device)

    def rpc(self, method, *params):
        # Pinned uiautomator2 version: its public RPC retries after a transport
        # error, which could repeat a successful tap. This primitive never retries.
        from uiautomator2.core import _jsonrpc_call

        return _jsonrpc_call(self.device.adb_device, 9008, method, params, 5, False)

    def snapshot(self):
        snapshot, self.selectors = parse_hierarchy(
            self.rpc("dumpWindowHierarchy", False, 50), self.app_id,
        )
        self.nodes = {node["id"]: node for node in snapshot["nodes"]}
        return snapshot

    def act(self, operation, identifier, value=None):
        from uiautomator2._selector import Selector

        node = self.nodes.get(identifier, {})
        if operation not in node.get("actions", []) or identifier not in self.selectors:
            raise RunStopped("Android target is missing, disabled or does not support this action.")
        if self.rpc("deviceInfo").get("currentPackageName") != self.app_id:
            raise RunStopped("The requested Android app is no longer in the foreground.")
        selector = Selector(**self.selectors[identifier])
        if self.rpc("count", selector) != 1:
            raise RunStopped("Android target is missing or ambiguous; no action performed.")
        info = self.rpc("objInfo", selector)
        if not info.get("enabled"):
            raise RunStopped("Android target became disabled; no action performed.")
        if operation == "fill":
            result = self.rpc("setText", selector, value)
        else:
            b = info.get("visibleBounds") or info.get("bounds") or {}
            if not all(k in b for k in ("left", "top", "right", "bottom")) or b["right"] <= b["left"] or b["bottom"] <= b["top"]:
                raise RunStopped("Android target has no visible tappable bounds.")
            result = self.rpc("click", (b["left"] + b["right"]) // 2, (b["top"] + b["bottom"]) // 2)
        if result is not True:
            raise RunStopped("Android action was not acknowledged; inspect state before retrying.")
        return {"performed": True}

    def close(self):
        self.device.stop_uiautomator(wait=False)


def main():
    output = sys.stdout
    logging.disable(logging.CRITICAL)  # Transport logs may contain field values.
    session = None
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                with contextlib.redirect_stdout(sys.stderr):
                    operation = request["operation"]
                    if operation == "open":
                        session = AndroidSession(request["device_id"], request["app_id"])
                        result = {"ready": True}
                    elif operation == "snapshot":
                        result = session.snapshot()
                    elif operation in {"tap", "fill"}:
                        result = session.act(operation, request["target"], request.get("value"))
                    elif operation == "close":
                        break
                    else:
                        raise RunStopped("Unsupported Android operation.")
                response = {"result": result}
            except RunStopped as exc:
                response = {"blocked": str(exc)}
            except ImportError:
                response = {"error": "Install the android extra: uv sync --extra android --frozen."}
            except Exception as exc:
                response = {"error": f"Android transport failure ({type(exc).__name__}); inspect state before retrying."}
            output.write(json.dumps(response, ensure_ascii=False) + "\n")
            output.flush()
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    main()
