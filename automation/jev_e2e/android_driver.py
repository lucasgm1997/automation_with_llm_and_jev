"""Async UI Automator driver, using a cancellable, persistent worker process."""

import asyncio
import json
import re
import sys
from contextlib import asynccontextmanager

from .semantics import RunStopped


def validate_android_target(device_id, app_id):
    if not device_id or not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]+", device_id):
        raise ValueError("uiautomator2 requires an explicit valid device_id.")
    if not app_id or not re.fullmatch(r"[A-Za-z][\w]*(?:\.[A-Za-z][\w]*)+", app_id):
        raise ValueError("uiautomator2 requires an explicit Android app_id.")


class AndroidDriver:
    def __init__(self, process):
        self.process = process

    async def call(self, operation, **arguments):
        self.process.stdin.write((json.dumps({"operation": operation, **arguments}) + "\n").encode())
        await self.process.stdin.drain()
        raw = await self.process.stdout.readline()
        if not raw:
            raise RuntimeError("Android worker exited; inspect device and ADB connection.")
        response = json.loads(raw)
        if "blocked" in response:
            raise RunStopped(response["blocked"])
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    async def snapshot(self):
        return await self.call("snapshot")

    async def tap(self, identifier):
        await self.call("tap", target=identifier)

    async def fill(self, identifier, value):
        await self.call("fill", target=identifier, value=value)


@asynccontextmanager
async def connect_android(device_id: str, app_id: str):
    validate_android_target(device_id, app_id)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "jev_e2e.android_worker",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=1_100_000,
    )
    driver = AndroidDriver(process)
    interrupted = True
    try:
        await driver.call("open", device_id=device_id, app_id=app_id)
        yield driver
        interrupted = False
    finally:
        if process.returncode is None:
            if interrupted:
                # Never let a timed-out worker proceed to a subsequent gesture.
                process.kill()
            else:
                process.stdin.write(b'{"operation":"close"}\n')
                await process.stdin.drain()
            try:
                await asyncio.wait_for(process.wait(), 1)
            except TimeoutError:
                process.kill()
                await process.wait()
