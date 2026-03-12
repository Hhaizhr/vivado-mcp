"""会话管理工具：start_session / stop_session / list_sessions。"""

import json

from mcp.server.fastmcp import Context

from vivado_mcp.server import _get_manager, mcp


@mcp.tool()
async def start_session(
    session_id: str = "default",
    vivado_path: str = "",
    timeout: int = 60,
    ctx: Context = None,
) -> str:
    """启动一个新的 Vivado TCL 交互会话。

    每个 session_id 对应一个独立的 Vivado 进程，支持多实例并行操作。

    Args:
        session_id: 会话标识符，默认 "default"。不同 session_id 启动独立进程。
        vivado_path: 可选，自定义 Vivado 可执行文件路径。留空则使用自动检测的路径。
        timeout: Vivado 启动超时秒数，默认 60。
    """
    manager = _get_manager(ctx)

    path = vivado_path if vivado_path else None
    try:
        session, banner = await manager.start_session(
            session_id=session_id,
            vivado_path=path,
            timeout=float(timeout),
        )
        status = session.status_dict()
        return (
            f"会话 '{session_id}' 已就绪。\n"
            f"Vivado: {status['vivado_path']}\n"
            f"状态: {status['state']}\n\n"
            f"--- 启动信息 ---\n{banner}"
        )
    except ValueError as e:
        return f"[ERROR] {e}"
    except Exception as e:
        return f"[ERROR] 启动会话 '{session_id}' 失败: {e}"


@mcp.tool()
async def stop_session(
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """关闭指定的 Vivado 会话。

    Args:
        session_id: 要关闭的会话标识符。
    """
    manager = _get_manager(ctx)
    return await manager.stop_session(session_id)


@mcp.tool()
async def list_sessions(ctx: Context = None) -> str:
    """列出所有活跃的 Vivado 会话及其状态。"""
    manager = _get_manager(ctx)
    sessions = manager.list_sessions()

    if not sessions:
        return "当前没有活跃的 Vivado 会话。使用 start_session 启动一个新会话。"

    return json.dumps(sessions, indent=2, ensure_ascii=False)
