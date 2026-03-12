"""项目管理工具：create_project / open_project / close_project / add_files。"""

from mcp.server.fastmcp import Context

from vivado_mcp.server import _NO_SESSION, _require_session, _safe_execute, mcp
from vivado_mcp.vivado.tcl_utils import to_tcl_path, validate_identifier


@mcp.tool()
async def create_project(
    name: str,
    directory: str,
    part: str = "",
    board_part: str = "",
    force: bool = False,
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """创建新的 Vivado 项目。

    Args:
        name: 项目名称。
        directory: 项目目录路径。
        part: FPGA 器件型号（如 "xc7a35tcpg236-1"）。part 和 board_part 至少指定一个。
        board_part: 开发板型号（如 "digilentinc.com:basys3:part0:1.1"）。与 part 二选一。
        force: 是否强制覆盖已有项目。
        session_id: 目标会话 ID。
    """
    try:
        name = validate_identifier(name, "name")
        if part:
            part = validate_identifier(part, "part")
        if board_part:
            board_part = validate_identifier(board_part, "board_part")
    except ValueError as e:
        return f"[ERROR] {e}"

    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    tcl_dir = to_tcl_path(directory)
    cmd_parts = [f"create_project {name} {tcl_dir}"]

    if part:
        cmd_parts.append(f"-part {part}")
    if board_part:
        cmd_parts.append(f"-board_part {board_part}")
    if force:
        cmd_parts.append("-force")

    tcl = " ".join(cmd_parts)

    return await _safe_execute(session, tcl, 30.0, "创建项目失败")


@mcp.tool()
async def open_project(
    xpr_path: str,
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """打开已有的 Vivado 项目文件（.xpr）。

    Args:
        xpr_path: 项目文件路径（.xpr 文件）。
        session_id: 目标会话 ID。
    """
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    tcl = f"open_project {to_tcl_path(xpr_path)}"
    return await _safe_execute(session, tcl, 30.0, "打开项目失败")


@mcp.tool()
async def close_project(
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """关闭当前打开的 Vivado 项目。

    Args:
        session_id: 目标会话 ID。
    """
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    return await _safe_execute(session, "close_project", 15.0, "关闭项目失败")


@mcp.tool()
async def add_files(
    files: str,
    fileset: str = "sources_1",
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """向 Vivado 项目添加源文件。

    Args:
        files: 文件路径，多个文件用空格分隔。路径中含空格请用大括号包裹。
        fileset: 目标 fileset，默认 "sources_1"。约束文件用 "constrs_1"，仿真文件用 "sim_1"。
        session_id: 目标会话 ID。
    """
    try:
        fileset = validate_identifier(fileset, "fileset")
    except ValueError as e:
        return f"[ERROR] {e}"

    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    # 转换路径中的反斜杠
    files_tcl = files.replace("\\", "/")
    tcl = f"add_files -fileset [get_filesets {fileset}] {files_tcl}"

    return await _safe_execute(session, tcl, 30.0, "添加文件失败")
