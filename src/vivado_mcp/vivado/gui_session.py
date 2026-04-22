from __future__ import annotations

import asyncio
import atexit
import importlib.resources
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from vivado_mcp.config import generate_auth_token, load_auth_token
from vivado_mcp.vivado.base_session import BaseSession, SessionState
from vivado_mcp.vivado.tcl_utils import TclResult, clean_output

logger = logging.getLogger(__name__)

_PORT_POOL_SIZE = 5
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_TMP_SCRIPTS: set[str] = set()


def _cleanup_tmp_scripts_atexit() -> None:
    for path in list(_TMP_SCRIPTS):
        try:
            os.unlink(path)
        except OSError:
            pass
    _TMP_SCRIPTS.clear()


atexit.register(_cleanup_tmp_scripts_atexit)


def _locate_server_script() -> Path:
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent.parent / "scripts" / "vivado_mcp_server.tcl"
    if candidate.is_file():
        return candidate

    try:
        with importlib.resources.as_file(
            importlib.resources.files("vivado_mcp").joinpath("scripts/vivado_mcp_server.tcl")
        ) as path:
            if path.is_file():
                return path
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        pass

    raise FileNotFoundError("Could not find vivado_mcp_server.tcl.")


class GuiSession(BaseSession):
    def __init__(
        self,
        vivado_path: str,
        session_id: str = "default",
        port: int = 9999,
        attach_only: bool = False,
        auth_token: str | None = None,
    ):
        super().__init__(vivado_path=vivado_path, session_id=session_id)
        self._port_preference = port
        self._attach_only = attach_only
        self._auth_token = (auth_token or "").strip()
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected_port: int | None = None
        self._lock = asyncio.Lock()
        self._tmp_script: str | None = None

    @property
    def mode(self) -> str:
        return "attach" if self._attach_only else "gui"

    @property
    def is_alive(self) -> bool:
        if self._state in (SessionState.DEAD, SessionState.STOPPED):
            return False
        if self._writer is None:
            return False
        return not self._writer.is_closing()

    async def start(self, timeout: float = 120.0) -> str:
        if self.is_alive:
            return f"Session '{self.session_id}' is already running."

        self._state = SessionState.STARTING

        if self._attach_only:
            self._auth_token = self._auth_token or (load_auth_token() or "")
            if not self._auth_token:
                self._state = SessionState.ERROR
                raise RuntimeError(
                    "Attach mode requires an auth token. Run `vivado-mcp install` first or pass auth_token explicitly."
                )
        else:
            self._auth_token = self._auth_token or generate_auth_token()
            try:
                script_path = _locate_server_script()
            except FileNotFoundError as exc:
                self._state = SessionState.ERROR
                raise RuntimeError(str(exc)) from exc

            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".tcl", delete=False, encoding="utf-8") as tmp:
                    tmp.write(f"set ::VMCP_PORT_PREF {self._port_preference}\n")
                    tmp.write(f"set ::VMCP_AUTH_TOKEN {{{self._auth_token}}}\n")
                    tmp.write(f'source "{script_path.as_posix()}"\n')
                    tmp_script = tmp.name
                self._tmp_script = tmp_script
                _TMP_SCRIPTS.add(tmp_script)

                self._proc = await asyncio.create_subprocess_exec(
                    self.vivado_path,
                    "-mode",
                    "gui",
                    "-source",
                    tmp_script,
                    "-nojournal",
                    "-nolog",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except (OSError, FileNotFoundError) as exc:
                self._state = SessionState.ERROR
                raise RuntimeError(f"Failed to launch Vivado GUI: {exc}") from exc

        ports_to_try = [self._port_preference + i for i in range(_PORT_POOL_SIZE)]
        deadline = time.time() + timeout
        connect_err: Exception | None = None

        while time.time() < deadline:
            for port in ports_to_try:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection("127.0.0.1", port),
                        timeout=2.0,
                    )
                except (ConnectionRefusedError, asyncio.TimeoutError, OSError) as exc:
                    connect_err = exc
                    continue

                if not await self._handshake(reader, writer):
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    continue

                self._reader = reader
                self._writer = writer
                self._connected_port = port
                self._state = SessionState.READY
                self._start_time = time.time()
                return f"GUI session ready: attach={self._attach_only}, port={port}"

            if self._proc is not None and self._proc.returncode is not None:
                self._state = SessionState.ERROR
                raise RuntimeError(
                    f"Vivado GUI exited early with return code {self._proc.returncode}."
                )
            await asyncio.sleep(2.0)

        self._state = SessionState.ERROR
        raise RuntimeError(
            f"Timed out connecting to Vivado GUI on ports {ports_to_try}. Last error: {connect_err}"
        )

    def _encode_command(self, command: str) -> bytes:
        payload = f"VMCP_AUTH {self._auth_token}\n{command}".encode("utf-8")
        return len(payload).to_bytes(4, "big") + payload

    async def _handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        timeout: float = 3.0,
    ) -> bool:
        try:
            writer.write(self._encode_command("puts VMCP_HANDSHAKE_ACK"))
            await writer.drain()
            resp_hdr = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
            resp_len = int.from_bytes(resp_hdr, "big")
            if resp_len < 0 or resp_len > 8192:
                return False
            body = await asyncio.wait_for(reader.readexactly(resp_len), timeout=timeout)
            obj = json.loads(body.decode("utf-8"))
            return obj.get("rc") == 0 and "VMCP_HANDSHAKE_ACK" in str(obj.get("output", ""))
        except Exception:
            return False

    async def execute(self, tcl_command: str, timeout: float = 120.0) -> TclResult:
        if not self.is_alive:
            raise RuntimeError(f"Session '{self.session_id}' is not connected. Start it first.")

        assert self._reader and self._writer

        async with self._lock:
            self._state = SessionState.BUSY
            try:
                result = await self._execute_impl(tcl_command, timeout)
                self._state = SessionState.READY
                return result
            except (ConnectionError, asyncio.IncompleteReadError) as exc:
                self._state = SessionState.DEAD
                raise RuntimeError(
                    f"GUI session disconnected unexpectedly: {exc}. Start the session again."
                ) from exc
            except Exception:
                self._state = SessionState.READY if self.is_alive else SessionState.DEAD
                raise

    async def _execute_impl(self, tcl_command: str, timeout: float) -> TclResult:
        assert self._reader and self._writer
        self._writer.write(self._encode_command(tcl_command))
        await self._writer.drain()

        try:
            resp_hdr = await asyncio.wait_for(self._reader.readexactly(4), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise asyncio.TimeoutError(f"Timed out waiting for GUI response after {timeout}s.") from exc

        resp_len = int.from_bytes(resp_hdr, "big")
        if resp_len < 0 or resp_len > _MAX_RESPONSE_BYTES:
            raise RuntimeError(f"Illegal GUI response length: {resp_len}")

        resp_body = await asyncio.wait_for(self._reader.readexactly(resp_len), timeout=timeout)
        try:
            obj = json.loads(resp_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Failed to parse GUI JSON response: {exc}") from exc

        rc = int(obj.get("rc", -1))
        output = clean_output(str(obj.get("output", "")))
        return TclResult(output=output, return_code=rc, is_error=(rc != 0))

    async def stop(self, timeout: float = 10.0) -> None:
        logger.info("Stopping GUI session '%s'", self.session_id)

        if not self._attach_only and self._writer is not None and self._state in (SessionState.READY, SessionState.BUSY):
            try:
                self._writer.write(self._encode_command("exit"))
                await self._writer.drain()
                if self._reader is not None:
                    await asyncio.wait_for(self._reader.read(4), timeout=5.0)
            except Exception:
                pass

        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        if self._proc is not None and not self._attach_only:
            if self._proc.returncode is None:
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    try:
                        if sys.platform == "win32":
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                                capture_output=True,
                                timeout=timeout,
                            )
                        else:
                            self._proc.kill()
                        await asyncio.wait_for(self._proc.wait(), timeout=timeout)
                    except Exception:
                        logger.warning("Failed to kill Vivado GUI process cleanly.")
            self._proc = None

        for pid_file in Path.cwd().glob("vivado_pid*.str"):
            try:
                pid_file.unlink()
            except OSError:
                pass

        if self._tmp_script:
            try:
                os.unlink(self._tmp_script)
            except OSError:
                pass
            _TMP_SCRIPTS.discard(self._tmp_script)
            self._tmp_script = None

        self._state = SessionState.STOPPED
