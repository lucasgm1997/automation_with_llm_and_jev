"""Prepare an installed Android debug app without flutter run or a debugger."""

import asyncio
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
REQUIRED_EXTENSIONS = {"ext.flutter.e2e_snapshot", "ext.flutter.e2e_action"}
SERVICE_URI = re.compile(
    r"(?:Dart VM service|Observatory).*?listening on (http://[^\s]+)", re.I
)


class PreparationError(RuntimeError):
    pass


def sdk_binary(name: str) -> str:
    config = {**dotenv_values(Path(__file__).resolve().parents[1] / ".env"), **os.environ}
    explicit = config.get(f"{name.upper()}_BIN")
    if explicit:
        return str(Path(explicit).expanduser())
    on_path = shutil.which(name)
    if on_path:
        return on_path
    roots = [config.get("ANDROID_HOME"), config.get("ANDROID_SDK_ROOT")]
    roots += [str(Path.home() / "Library/Android/sdk"), str(Path.home() / "Android/Sdk")]
    for root in filter(None, roots):
        candidate = Path(root).expanduser() / ("platform-tools" if name == "adb" else name) / name
        if candidate.is_file():
            return str(candidate)
    raise PreparationError(f"{name} not found; configure {name.upper()}_BIN or ANDROID_HOME.")


async def command(*args: str, check: bool = True) -> str:
    """Bound each child process and reap it on timeout/cancellation. Never use a shell."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise PreparationError(f"Cannot start {Path(args[0]).name}: {exc.strerror}.") from exc
    try:
        async with asyncio.timeout(15):
            stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if check and process.returncode:
        # Do not echo logs, URIs or other application data in diagnostic messages.
        detail = stderr.decode(errors="replace").lower()
        if "not permitted" in detail or "permission denied" in detail:
            raise PreparationError("Android SDK access denied by this environment's permissions.")
        raise PreparationError(
            f"{Path(args[0]).name} failed (exit {process.returncode}); check SDK, device access and authorization."
        )
    return stdout.decode(errors="replace").strip()


class AndroidPreparation:
    def __init__(self, device_id: str, app_id: str, avd_name: str | None):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", device_id):
            raise PreparationError("Invalid device_id; use the serial reported by adb devices.")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", app_id, re.ASCII):
            raise PreparationError("Invalid Android application ID.")
        if avd_name and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", avd_name):
            raise PreparationError("Invalid avd_name; use a name from emulator -list-avds.")
        self.adb = sdk_binary("adb")
        self.device_id, self.app_id, self.avd_name = device_id, app_id, avd_name
        self.phase = "device"
        self.emulator = None
        self.emulator_log = None
        self.forward_port = None

    async def adb_command(self, *args: str, check: bool = True) -> str:
        return await command(self.adb, "-s", self.device_id, *args, check=check)

    async def device_state(self) -> str | None:
        devices = await command(self.adb, "devices")
        for line in devices.splitlines():
            columns = line.split()
            if len(columns) >= 2 and columns[0] == self.device_id:
                return columns[1]
        return None

    async def ensure_device(self) -> None:
        state = await self.device_state()
        if state is None:
            if not self.avd_name:
                raise PreparationError("Device is disconnected. Supply avd_name to start an existing emulator.")
            serial = re.fullmatch(r"emulator-(\d+)", self.device_id)
            port = int(serial[1]) if serial else 0
            if port < 5554 or port > 5682 or port % 2:
                raise PreparationError("Starting an AVD requires an emulator-N serial with an even port from 5554 to 5682.")
            emulator = sdk_binary("emulator")
            available = (await command(emulator, "-list-avds")).splitlines()
            if self.avd_name not in available:
                raise PreparationError("AVD not found; select an existing name from emulator -list-avds.")
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            self.emulator_log = ARTIFACTS / f"emulator-{uuid4().hex[:8]}.log"
            with self.emulator_log.open("wb") as log:
                self.emulator = subprocess.Popen(
                    [emulator, "-avd", self.avd_name, "-port", str(port)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                )
        self.phase = "boot"
        while True:
            state = await self.device_state()
            if state == "unauthorized":
                raise PreparationError("Device is unauthorized; authorize this computer on the Android device.")
            if self.emulator is not None and self.emulator.poll() is not None:
                raise PreparationError("Emulator exited before becoming ready; inspect emulator_log.")
            if state == "device":
                if await self.adb_command("shell", "getprop", "sys.boot_completed") == "1":
                    break
            elif state not in {None, "offline"}:
                raise PreparationError(f"Device cannot run the app in state {state!r}.")
            await asyncio.sleep(0.5)
        if self.avd_name:
            actual = (await self.adb_command("emu", "avd", "name")).splitlines()
            if not actual or actual[0] != self.avd_name:
                raise PreparationError("device_id belongs to a different AVD; choose the intended device.")

    async def launch_app(self) -> None:
        self.phase = "launch"
        installed = await self.adb_command("shell", "pm", "path", self.app_id, check=False)
        if not installed.startswith("package:"):
            raise PreparationError("APK is not installed on this device; install the instrumented debug APK first.")
        package = await self.adb_command("shell", "dumpsys", "package", self.app_id)
        if not re.search(r"\b(?:flags|pkgFlags)=\[[^\]]*\bDEBUGGABLE\b", package):
            raise PreparationError("Installed APK is not debuggable; Jev requires a debug build with E2E extensions.")
        activity = await self.adb_command(
            "shell", "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", self.app_id,
        )
        components = [line for line in activity.splitlines() if re.fullmatch(
            re.escape(self.app_id) + r"/[A-Za-z0-9_.$]+", line,
        )]
        if len(components) != 1:
            raise PreparationError("Could not resolve a unique launcher activity for this app.")
        result = await self.adb_command(
            "shell", "am", "start", "-W", "-n", shlex.quote(components[0]),
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
        )
        if re.search(r"(?im)^\s*(Error|Exception)", result):
            raise PreparationError("Android could not launch the installed app.")

    async def remove_forward(self) -> None:
        if self.forward_port:
            await self.adb_command("forward", "--remove", f"tcp:{self.forward_port}", check=False)
            self.forward_port = None

    async def probe(self, client: httpx.AsyncClient, uri: str, pid: int) -> bool:
        """Reject stale log entries and services belonging to another process."""
        try:
            response = await client.get(uri + "getVM")
            response.raise_for_status()
            vm = response.json().get("result", {})
            if vm.get("pid") != pid:
                return False
            for isolate in vm.get("isolates", []):
                response = await client.get(uri + "getIsolate", params={"isolateId": isolate["id"]})
                response.raise_for_status()
                extensions = response.json().get("result", {}).get("extensionRPCs", [])
                if REQUIRED_EXTENSIONS.issubset(extensions):
                    return True
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            pass
        return False

    async def discover(self) -> str:
        self.phase = "vm_service"
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            while True:
                pid = await self.adb_command("shell", "pidof", self.app_id, check=False)
                if pid.isdecimal():
                    logs = await self.adb_command(
                        "logcat", "-d", "--pid", pid, "-t", "1000", "-s", "flutter:I", "*:S",
                    )
                    # Newest first; only loopback services from this app's PID.
                    for raw in dict.fromkeys(reversed(SERVICE_URI.findall(logs))):
                        parsed = urlsplit(raw)
                        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not parsed.port:
                            continue
                        port = await self.adb_command("forward", "tcp:0", f"tcp:{parsed.port}")
                        if not port.isdecimal() or not 0 < int(port) < 65536:
                            raise PreparationError("ADB did not return a valid forwarded host port.")
                        self.forward_port = port
                        uri = urlunsplit(("http", f"127.0.0.1:{port}", parsed.path.rstrip("/") + "/", "", ""))
                        if await self.probe(client, uri, int(pid)):
                            if await self.adb_command("shell", "pidof", self.app_id, check=False) == pid:
                                return uri
                        await self.remove_forward()
                await asyncio.sleep(0.5)


async def prepare_android(
    device_id: str, app_id: str, avd_name: str | None = None, timeout_seconds: int = 120,
) -> dict:
    started = perf_counter()
    preparation = None
    result = {"status": "blocked", "device_id": device_id, "app_id": app_id}
    try:
        if not 5 <= timeout_seconds <= 300:
            raise PreparationError("timeout_seconds must be between 5 and 300.")
        preparation = AndroidPreparation(device_id, app_id, avd_name)
        async with asyncio.timeout(timeout_seconds):
            await preparation.ensure_device()
            await preparation.launch_app()
            uri = await preparation.discover()
        result.update(status="ready", vm_uri=uri, forward_port=int(preparation.forward_port))
    except TimeoutError:
        result["reason"] = (
            f"Preparation timed out during {preparation.phase if preparation else 'setup'}. "
            "Check emulator boot, current app logs and debug E2E extensions."
        )
    except (PreparationError, OSError, ValueError) as exc:
        result["reason"] = str(exc)
    finally:
        if preparation:
            result["emulator_started"] = preparation.emulator is not None
            if preparation.emulator_log:
                result["emulator_log"] = str(preparation.emulator_log)
            if result["status"] != "ready":
                try:
                    await preparation.remove_forward()
                except (PreparationError, OSError, TimeoutError):
                    pass
        result["preparation_ms"] = round((perf_counter() - started) * 1000, 2)
    return result
