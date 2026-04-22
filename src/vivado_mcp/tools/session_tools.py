"""Session management tools."""

import json

from mcp.server.fastmcp import Context

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
        return f"[ERROR] Failed to start session '{session_id}': {exc}"


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
