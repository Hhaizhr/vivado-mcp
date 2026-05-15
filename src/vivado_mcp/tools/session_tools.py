"""Session management tools."""

import json
import os
import socket
import subprocess
from pathlib import Path

from mcp.server.fastmcp import Context

from vivado_mcp.config import load_auth_token
from vivado_mcp.server import _get_manager, mcp


@mcp.tool()
async def start_session(
    session_id: str = "default",
    mode: str = "gui",
    port: int = 9999,
    vivado_path: str = "",
    auth_token: str = "",
    timeout: int = 120,
    ctx: Context = None,
) -> str:
    """Start a new Vivado session.

    Args:
        session_id: Session identifier.
        mode: One of "gui", "tcl", or "attach".
        port: Preferred TCP port for GUI/attach mode.
        vivado_path: Optional explicit Vivado executable path.
        auth_token: Optional auth token for GUI/attach mode. If omitted, attach mode
            falls back to VMCP_AUTH_TOKEN or the saved token file from `vivado-mcp install`.
        timeout: Startup timeout in seconds.
    """
    manager = _get_manager(ctx)

    path = vivado_path if vivado_path else None
    token = auth_token if auth_token else None
    try:
        session, banner = await manager.start_session(
            session_id=session_id,
            vivado_path=path,
            timeout=float(timeout),
            mode=mode,
            port=int(port),
            auth_token=token,
        )
        status = session.status_dict()
        return (
            f"Session '{session_id}' is ready (mode={status['mode']}).\n"
            f"Vivado: {status['vivado_path']}\n"
            f"State: {status['state']}\n\n"
            f"--- Startup Info ---\n{banner}"
        )
    except ValueError as exc:
        return f"[ERROR] {exc}"
    except Exception as exc:
        hint = ""
        if mode == "gui":
            hint = (
                "\n\nHint: GUI startup can fail inside sandboxed agents. "
                "Start Vivado on the desktop, let Vivado_init.tcl load the bridge, "
                "then call start_session(mode='attach', port=9999)."
            )
        elif mode == "attach":
            hint = (
                "\n\nHint: Check that Vivado is already open, the bridge banner is visible, "
                "and try ports 9999-10003. diagnose_local_sessions can inspect common causes."
            )
        return f"[ERROR] Failed to start session '{session_id}': {exc}{hint}"


@mcp.tool()
async def stop_session(
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    manager = _get_manager(ctx)
    return await manager.stop_session(session_id)


@mcp.tool()
async def list_sessions(ctx: Context = None) -> str:
    manager = _get_manager(ctx)
    sessions = manager.list_sessions()

    if not sessions:
        return "There are no active Vivado sessions. Use start_session to create one."

    return json.dumps(sessions, indent=2, ensure_ascii=False)


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _tasklist_count(image_name: str) -> int | str:
    if os.name != "nt":
        return "unsupported"
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return f"error: {exc}"
    return sum(
        1
        for line in proc.stdout.splitlines()
        if line.lower().startswith(image_name.lower())
    )


def _taskkill_image(image_name: str) -> str:
    if os.name != "nt":
        return "unsupported on non-Windows hosts"
    try:
        proc = subprocess.run(
            ["taskkill", "/F", "/IM", image_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return f"error: {exc}"
    text = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 128 and "not found" in text.lower():
        return "not running"
    return text or f"taskkill exited with rc={proc.returncode}"


@mcp.tool()
async def diagnose_local_sessions(
    port_start: int = 9999,
    port_count: int = 5,
    ctx: Context = None,
) -> str:
    """Diagnose local Vivado MCP session state and common stale-process issues."""
    manager = _get_manager(ctx)
    sessions = manager.list_sessions()
    ports = list(range(int(port_start), int(port_start) + int(port_count)))
    port_lines = [f"  {port}: {'open' if _port_open(port) else 'closed'}" for port in ports]

    token = load_auth_token()
    token_state = "present" if token else "missing"
    home_dir = Path.home() / ".vivado-mcp"

    return "\n".join(
        [
            "--- Vivado MCP local diagnostics ---",
            f"active MCP sessions: {len(sessions)}",
            json.dumps(sessions, indent=2, ensure_ascii=False) if sessions else "[]",
            "",
            "bridge ports:",
            *port_lines,
            "",
            f"auth token: {token_state} ({home_dir / 'auth_token.txt'})",
            f"vivado.exe processes: {_tasklist_count('vivado.exe')}",
            f"xsimk.exe processes: {_tasklist_count('xsimk.exe')}",
            "",
            "Typical recovery:",
            "  1. If a port is open, try start_session(mode='attach', port=<open port>).",
            "  2. If xsimk.exe remains after a bad simulation, close it before rerunning.",
            "  3. Run cleanup_local_processes(kill_xsim=True) for stale simulations.",
            "  4. If no bridge port is open, launch Vivado GUI and attach again.",
        ]
    )


@mcp.tool()
async def cleanup_local_processes(
    kill_xsim: bool = True,
    kill_vivado: bool = False,
    ctx: Context = None,
) -> str:
    """Clean up stale local Vivado-related processes.

    By default this only terminates xsimk.exe, because stale xsim processes are
    common after accidental open-ended simulations. Vivado itself is never killed
    unless kill_vivado=True is explicitly passed.
    """
    before = {
        "vivado.exe": _tasklist_count("vivado.exe"),
        "xsimk.exe": _tasklist_count("xsimk.exe"),
    }
    actions: list[str] = []
    if kill_xsim:
        actions.append(f"xsimk.exe: {_taskkill_image('xsimk.exe')}")
    if kill_vivado:
        actions.append(f"vivado.exe: {_taskkill_image('vivado.exe')}")

    after = {
        "vivado.exe": _tasklist_count("vivado.exe"),
        "xsimk.exe": _tasklist_count("xsimk.exe"),
    }
    return "\n".join(
        [
            "--- Vivado local process cleanup ---",
            f"before: {json.dumps(before, ensure_ascii=False)}",
            "actions:",
            *(f"  - {action}" for action in actions),
            f"after: {json.dumps(after, ensure_ascii=False)}",
        ]
    )
