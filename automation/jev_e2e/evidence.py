"""Independent, bounded Console and Network captures; no UI-run dependency."""

import asyncio
import base64
import json
import time
from collections import OrderedDict
from contextlib import suppress
from uuid import uuid4

from .driver import websocket_uri
from .evidence_redaction import body_preview, clean, clean_text, clean_url
from .vm_service import VMConnection, VMError

MAX_ITEMS = 500


class Capture:
    def __init__(self, kind, uri, ttl_seconds, connection=None):
        self.id = uuid4().hex[:12]
        self.kind, self.uri = kind, websocket_uri(uri)
        self.connection = connection or VMConnection()
        self.status = "starting"
        self.started_at_ms = int(time.time() * 1000)
        self.ttl_seconds = ttl_seconds
        self.sequence = self.evicted = 0
        self.items = OrderedDict()
        self.worker = self.expiry = None
        self.close_lock = asyncio.Lock()
        self.streams = {}
        self.isolates = {}
        self.profiling = {}  # isolate -> original shared profiler state
        self.cursors = {}
        self.floors = {}
        self.last_error = None

    def info(self):
        return {
            "capture_id": self.id, "kind": self.kind, "status": self.status,
            "connected": self.connection.connected, "started_at_ms": self.started_at_ms,
            "ttl_seconds": self.ttl_seconds, "retained": len(self.items),
            "evicted": self.evicted, "events_dropped": self.connection.events_dropped,
            "last_cursor": self.sequence, "last_error": self.last_error,
            **({"streams": self.streams} if self.kind == "console" else {"isolates": self.isolates}),
        }

    def store(self, key, item):
        previous = self.items.get(key)
        if previous is not None and {k: v for k, v in previous.items() if k != "cursor"} == item:
            return
        self.sequence += 1
        self.items[key] = {**item, "cursor": self.sequence}
        self.items.move_to_end(key)
        while len(self.items) > MAX_ITEMS:
            self.items.popitem(last=False)
            self.evicted += 1

    async def start(self):
        try:
            await self.connection.open(self.uri)
            if self.kind == "console":
                for stream in ("Stdout", "Stderr", "Logging", "Extension"):
                    try:
                        await self.connection.call("streamListen", streamId=stream)
                        self.streams[stream] = True
                    except VMError:
                        if not self.connection.connected:
                            raise
                        self.streams[stream] = False
                if not any(self.streams.values()):
                    raise VMError("The VM does not expose any supported console stream.")
            else:
                await self.poll_network()
            self.status = "capturing"
            self.worker = asyncio.create_task(self.run())
            self.expiry = asyncio.create_task(self.expire())
        except BaseException:
            await self.close("failed")
            raise

    async def expire(self):
        await asyncio.sleep(self.ttl_seconds)
        if self.status == "capturing":
            await self.close("expired")

    async def run(self):
        try:
            while self.connection.connected:
                if self.kind == "console":
                    try:
                        event = await asyncio.wait_for(self.connection.events.get(), 1)
                    except TimeoutError:
                        continue
                    await self.console_event(event)
                else:
                    await asyncio.sleep(1)
                    await self.poll_network()
            raise VMError("VM disconnected. Existing evidence is retained; start a new capture after reconnecting.")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.last_error = "Collection interrupted; evidence may be incomplete. Start a new capture with the current VM URI."
            await self.close("disconnected")

    async def resolve_string(self, ref, isolate):
        if not isinstance(ref, dict):
            return clean_text(ref) if ref is not None else None
        if ref.get("kind") == "Null":
            return None
        value = ref.get("valueAsString")
        if ref.get("id") and (value is None or ref.get("valueAsStringIsTruncated")) and isolate:
            try:
                obj = await self.connection.call("getObject", isolateId=isolate, objectId=ref["id"], offset=0, count=8192)
                value = obj.get("valueAsString", value)
            except VMError:
                pass
        return clean_text(value if value is not None else "<object unavailable>")

    async def console_event(self, params):
        stream, event = params.get("streamId"), params.get("event", {})
        isolate = event.get("isolate", {}).get("id")
        item = {"source": stream, "timestamp_ms": event.get("timestamp"), "isolate_id": isolate}
        if stream in {"Stdout", "Stderr"} and event.get("kind") == "WriteEvent":
            try:
                text = base64.b64decode(event.get("bytes", ""), validate=True).decode("utf-8", errors="replace")
            except ValueError:
                text = "<invalid console encoding>"
            item["message"] = clean_text(text)
        elif stream == "Logging":
            record = event.get("logRecord", {})
            item.update(level=record.get("level"), logger=await self.resolve_string(record.get("loggerName"), isolate),
                        message=await self.resolve_string(record.get("message"), isolate),
                        error=await self.resolve_string(record.get("error"), isolate),
                        stack_trace=await self.resolve_string(record.get("stackTrace"), isolate))
        elif stream == "Extension" and event.get("extensionKind") == "Flutter.Error":
            item.update(source="Flutter.Error", level=1000,
                        details=clean(event.get("extensionData", {})))
            # A large structured error tree shouldn't fill the agent's context.
            item["details"] = clean_text(json.dumps(item["details"], ensure_ascii=False))
        else:
            return
        self.store(str(self.sequence + 1), item)

    async def poll_network(self):
        vm = await self.connection.call("getVM")
        live = {i["id"] for i in vm.get("isolates", []) if not i.get("isSystemIsolate", False)}
        for old in set(self.isolates) - live:
            self.isolates[old] = "exited"
            self.profiling.pop(old, None)
            self.cursors.pop(old, None)
            self.floors.pop(old, None)
        for isolate in sorted(live):
            try:
                if isolate not in self.cursors:
                    details = await self.connection.call("getIsolate", isolateId=isolate)
                    extensions = details.get("extensionRPCs", [])
                    if "ext.dart.io.getHttpProfile" not in extensions or "ext.dart.io.httpEnableTimelineLogging" not in extensions:
                        self.isolates[isolate] = "http_profiling_unavailable"
                        continue
                    state = await self.connection.call("ext.dart.io.httpEnableTimelineLogging", isolateId=isolate)
                    self.profiling.setdefault(isolate, bool(state.get("enabled")))
                    if not state.get("enabled"):
                        await self.connection.call("ext.dart.io.httpEnableTimelineLogging", isolateId=isolate, enabled="true")
                    baseline = await self.connection.call("ext.dart.io.getHttpProfile", isolateId=isolate)
                    self.cursors[isolate] = baseline["timestamp"]
                    self.floors[isolate] = baseline["timestamp"]
                    self.isolates[isolate] = "capturing"
                    continue
                profile = await self.connection.call("ext.dart.io.getHttpProfile", isolateId=isolate,
                                                     updatedSince=str(self.cursors[isolate]))
                for request in profile.get("requests", []):
                    if request.get("startTime", 0) >= self.floors[isolate]:
                        self.record_request(isolate, request)
                self.cursors[isolate] = profile["timestamp"]
                self.isolates[isolate] = "capturing"
            except VMError:
                if not self.connection.connected:
                    raise
                self.isolates[isolate] = "read_failed"
                # Isolate may disappear during hot restart. Other isolates keep
                # collecting; the next poll refreshes discovery and capabilities.
        if len(self.isolates) > 100:
            self.isolates = {k: v for k, v in self.isolates.items() if k in live}

    def record_request(self, isolate, request):
        response = request.get("response") or {}
        sent = request.get("request") or {}
        error = sent.get("error") or response.get("error")
        start = request.get("startTime")
        end = response.get("endTime") or (request.get("endTime") if error else None)
        key = isolate + ":" + request["id"]
        item = {
            "request_id": key, "isolate_id": isolate, "vm_request_id": request["id"],
            "method": request.get("method"), "url": clean_url(request.get("uri", "")),
            "status_code": response.get("statusCode"), "start_time_us": start,
            "end_time_us": end, "duration_ms": round((end - start) / 1000, 3) if start is not None and end is not None else None,
            "state": "failed" if error else "completed" if end is not None else "pending",
            "error": clean_text(error) if error else None,
            "request_bytes": sent.get("contentLength"), "response_bytes": response.get("contentLength"),
        }
        self.store(key, item)

    async def request_details(self, request_id, include_bodies=False):
        item = self.items.get(request_id)
        if item is None:
            raise ValueError("Request not retained in this capture; consult list_network_requests.")
        if not self.connection.connected or self.status != "capturing":
            return {**self.info(), "request": item, "details_available": False,
                    "reason": "Capture is not connected; only retained metadata is available."}
        try:
            result = await self.connection.call("ext.dart.io.getHttpProfileRequest", isolateId=item["isolate_id"], id=item["vm_request_id"])
        except VMError:
            return {**self.info(), "request": item, "details_available": False,
                    "reason": "Request details expired, isolate exited, or response exceeds the transport budget."}
        request = result.get("request") or {}
        response = result.get("response") or {}
        if result.get("id"):
            self.record_request(item["isolate_id"], result)
            item = self.items[request_id]
        detail = {"request_headers": clean(request.get("headers", {})),
                  "response_headers": clean(response.get("headers", {})),
                  "events": clean(result.get("events", []))}
        if include_bodies:
            detail.update(request_body=body_preview(result.get("requestBody"), request.get("headers")),
                          response_body=body_preview(result.get("responseBody"), response.get("headers")))
        return {**self.info(), "request": item, "details_available": True, **detail}

    def read(self, after_cursor=0, limit=50, contains=None, source=None, min_level=None, errors_only=False):
        if after_cursor > self.sequence:
            raise ValueError("Cursor is ahead of this capture; use a cursor returned by the same capture.")
        rows = [r for r in self.items.values() if r["cursor"] > after_cursor]
        if contains:
            rows = [r for r in rows if contains.casefold() in json.dumps(r, ensure_ascii=False).casefold()]
        if source:
            rows = [r for r in rows if r.get("source") == source]
        if min_level is not None:
            rows = [r for r in rows if isinstance(r.get("level"), int) and r["level"] >= min_level]
        if errors_only:
            rows = [r for r in rows if r.get("error") or (r.get("status_code") or 0) >= 400]
        more = len(rows) > limit
        rows = rows[:limit]
        return {**self.info(), "items": rows, "has_more": more,
                "next_cursor": rows[-1]["cursor"] if more else self.sequence,
                "history_truncated": self.evicted > 0 or self.connection.events_dropped > 0}

    async def close(self, status="stopped"):
        async with self.close_lock:
            self.status = status
            for task in (self.worker, self.expiry):
                if task is not None and task is not asyncio.current_task():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            if self.kind == "console":
                self.connection.events_dropped += self.connection.events.qsize()
                while not self.connection.events.empty():
                    self.connection.events.get_nowait()
            for isolate in self.isolates:
                if self.isolates[isolate] == "capturing":
                    self.isolates[isolate] = status
            try:
                # Restore only flags this collector enabled. Never clear VM data.
                async with asyncio.timeout(6):
                    if self.kind == "network" and self.connection.connected:
                        for isolate, was_enabled in self.profiling.items():
                            if not was_enabled:
                                try:
                                    await self.connection.call("ext.dart.io.httpEnableTimelineLogging", isolateId=isolate, enabled="false")
                                except VMError:
                                    self.last_error = "Could not restore HTTP profiling state for an isolate."
            except TimeoutError:
                self.last_error = "Timed out restoring HTTP profiling state."
            finally:
                await self.connection.close()


class EvidenceManager:
    def __init__(self):
        self.captures = OrderedDict()
        self.lock = asyncio.Lock()

    async def start(self, kind, uri, ttl_seconds=1800):
        canonical = websocket_uri(uri)
        async with self.lock:
            for capture in self.captures.values():
                if capture.kind == kind and capture.uri == canonical and capture.status == "capturing":
                    return {**capture.info(), "reused": True}
            while len(self.captures) >= 8:
                terminal = next((k for k, c in self.captures.items() if c.status != "capturing"), None)
                if terminal is None:
                    raise ValueError("Eight captures are active. Stop one before opening another.")
                del self.captures[terminal]
            capture = Capture(kind, canonical, ttl_seconds)
            try:
                async with asyncio.timeout(20):
                    await capture.start()
            except TimeoutError as exc:
                raise VMError("Capture startup timed out; check VM connectivity and available isolates.") from exc
            self.captures[capture.id] = capture
            return capture.info()

    def get(self, capture_id, kind=None):
        capture = self.captures.get(capture_id)
        if capture is None or (kind is not None and capture.kind != kind):
            raise ValueError("Capture not found for this tool; start the appropriate capture on this MCP server.")
        return capture

    async def stop(self, capture_id):
        capture = self.get(capture_id)
        if capture.status == "capturing":
            await capture.close()
        return capture.info()

    async def close(self):
        await asyncio.gather(*(c.close() for c in self.captures.values()), return_exceptions=True)
        self.captures.clear()
