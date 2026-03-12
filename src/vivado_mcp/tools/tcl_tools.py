"""通用 Tcl 执行工具：run_tcl / vivado_help。

run_tcl 是整个系统最核心的工具 —— 可执行任意 Vivado Tcl 命令，
等价于 200+ 专用工具的功能覆盖。
"""

from mcp.server.fastmcp import Context

from vivado_mcp.server import _NO_SESSION, _require_session, _safe_execute, mcp


@mcp.tool()
async def run_tcl(
    command: str,
    session_id: str = "default",
    timeout: int = 120,
    ctx: Context = None,
) -> str:
    """执行任意 Vivado Tcl 命令。支持所有 Vivado Tcl API。

    这是最通用的工具，可以执行任何 Vivado Tcl 命令，包括：
    - 约束命令：create_clock, set_property, ...
    - IP 管理：create_ip, generate_target, ...
    - Block Design：create_bd_design, create_bd_cell, ...
    - 文件操作：add_files, read_verilog, read_xdc, ...
    - 查询命令：get_ports, get_cells, get_nets, ...
    - 报告命令：report_utilization, report_timing_summary, ...
    - 以及任何其他 Vivado Tcl 命令

    支持多行脚本，用换行符分隔即可。

    Args:
        command: Tcl 命令文本（支持多行）。
        session_id: 目标会话 ID，默认 "default"。
        timeout: 命令执行超时秒数，默认 120。
    """
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    return await _safe_execute(session, command, float(timeout), "命令执行失败")


# Vivado Tcl 命令快速参考（内置，不需要启动 Vivado 即可查看）
_BUILTIN_HELP = {
    "create_project": (
        "create_project <name> <dir> [-part <part>] [-force]\n"
        "创建新 Vivado 项目。\n"
        "示例: create_project my_proj ./my_proj -part xc7a35tcpg236-1"
    ),
    "open_project": (
        "open_project <xpr_file>\n"
        "打开已有项目文件。\n"
        "示例: open_project ./my_proj/my_proj.xpr"
    ),
    "close_project": "close_project\n关闭当前打开的项目。",
    "add_files": (
        "add_files [-fileset <fileset>] [-norecurse] <files>\n"
        "添加源文件到项目。\n"
        "示例: add_files -fileset sources_1 {./src/top.v ./src/sub.v}"
    ),
    "launch_runs": (
        "launch_runs <run> [-jobs <N>] [-to_step <step>]\n"
        "启动综合/实现运行。\n"
        "示例: launch_runs synth_1 -jobs 4"
    ),
    "wait_on_run": (
        "wait_on_run <run> [-timeout <minutes>]\n"
        "等待运行完成。\n"
        "示例: wait_on_run synth_1 -timeout 30"
    ),
    "create_clock": (
        "create_clock -period <ns> [-name <name>] [-waveform {rise fall}] <port>\n"
        "创建时钟约束。\n"
        "示例: create_clock -period 10.000 -name sys_clk [get_ports clk]"
    ),
    "set_property": (
        "set_property <prop> <value> <object>\n"
        "设置对象属性。\n"
        '示例: set_property PACKAGE_PIN W5 [get_ports clk]'
    ),
    "report_utilization": (
        "report_utilization [-return_string] [-file <file>]\n"
        "生成资源利用率报告。"
    ),
    "report_timing_summary": (
        "report_timing_summary [-return_string] [-file <file>] "
        "[-max_paths <N>]\n"
        "生成时序报告摘要。"
    ),
    "report_power": (
        "report_power [-return_string] [-file <file>]\n"
        "生成功耗报告。"
    ),
}


@mcp.tool()
async def vivado_help(
    tcl_command: str = "",
    session_id: str = "",
    ctx: Context = None,
) -> str:
    """查询 Vivado Tcl 命令帮助。

    提供内置快速参考，如果指定了 session_id 且会话存在，
    还会调用 Vivado 的 help 命令获取完整文档。

    Args:
        tcl_command: 要查询的 Tcl 命令名（如 "create_clock"）。留空则显示所有可用的内置参考。
        session_id: 可选，如果指定且会话存在，会同时查询 Vivado 原生 help。
    """
    parts: list[str] = []

    if not tcl_command:
        # 列出所有内置参考
        parts.append("=== 内置快速参考 ===\n")
        parts.append("可查询的命令: " + ", ".join(sorted(_BUILTIN_HELP.keys())))
        parts.append("\n用法: vivado_help(tcl_command=\"create_clock\")")
        parts.append("\n提示: 使用 run_tcl 可执行任意 Tcl 命令，不限于此列表。")
        return "\n".join(parts)

    # 内置参考
    if tcl_command in _BUILTIN_HELP:
        parts.append(f"=== 内置参考: {tcl_command} ===\n")
        parts.append(_BUILTIN_HELP[tcl_command])

    # 如果有活跃会话，查询 Vivado 原生 help
    if session_id:
        session = _require_session(ctx, session_id)
        if session:
            try:
                result = await session.execute(
                    f"help {tcl_command}", timeout=10.0
                )
                parts.append("\n=== Vivado 原生帮助 ===\n")
                parts.append(result.output)
            except Exception as e:
                parts.append(f"\n[WARN] 查询 Vivado help 失败: {e}")

    if not parts:
        return (
            f"未找到 '{tcl_command}' 的内置参考。\n"
            "提示: 指定 session_id 参数可查询 Vivado 原生 help 命令。"
        )

    return "\n".join(parts)
