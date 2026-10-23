"""Small, persistent JSON-RPC client for read-only Dart runtime diagnostics."""

import asyncio
import json
import logging
from contextlib import suppress

from websockets.asyncio.client import connect

from .driver import websocket_uri


class VMError(RuntimeError):
    def __init__(self, message="VM service request failed.", code=None):
        super().__init__(message)
        self.code = code


class VMConnection:
    def __init__(self):
        self.socket = None
        self.reader = None
        self.pending = {}
        self.events = asyncio.Queue(maxsize=1000)
        self.events_dropped = 0
        self.sequence = 0
        self.connected = False

    async def open(self, uri):
        # No environment proxy: VM URLs contain authentication tokens.
        logger = logging.getLogger("jev_e2e.vm_transport")
        logger.disabled = True
        try:
            self.socket = await connect(
                websocket_uri(uri), proxy=None, open_timeout=5, close_timeout=1,
                max_size=8 * 1024 * 1024, logger=logger,
            )
        except Exception as exc:
            raise VMError("Cannot connect to Dart VM Service. Check the current URI/forwarding; in Docker, use a reachable host or DDS URI.") from exc
        self.connected = True
        self.reader = asyncio.create_task(self._receive())

    async def _receive(self):
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                if "id" in message:
                    future = self.pending.get(str(message["id"]))
                    if future is not None and not future.done():
                        if "error" in message:
                            future.set_exception(VMError(code=message["error"].get("code")))
                        else:
                            future.set_result(message.get("result", {}))
                elif message.get("method") == "streamNotify":
                    if self.events.full():
                        self.events.get_nowait()
                        self.events_dropped += 1
                    self.events.put_nowait(message.get("params", {}))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # Never echo response bodies or authentication URLs.
        finally:
            self.connected = False
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(VMError("VM connection closed; start a new capture with the current URI."))

    async def call(self, method, **params):
        if not self.connected:
            raise VMError("VM connection is closed.")
        self.sequence += 1
        identifier = str(self.sequence)
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            async with asyncio.timeout(5):
                await self.socket.send(json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}))
                result = await future
                if result.get("type") == "Sentinel":
                    raise VMError("VM object or isolate is no longer available.", code=105)
                return result
        except TimeoutError as exc:
            raise VMError("VM service request timed out; capture may be incomplete.") from exc
        except VMError:
            raise
        except Exception as exc:
            raise VMError("VM service transport or response failed.") from exc
        finally:
            self.pending.pop(identifier, None)
            if not future.done():
                future.cancel()

    async def close(self):
        if self.socket is not None:
            await self.socket.close()
        if self.reader is not None:
            self.reader.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader
        self.connected = False
