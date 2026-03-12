"""报告工具：report / get_io_report / get_timing_report。

report: 通用报告接口，按 report_type 选择报告类型。
get_io_report / get_timing_report: 结构化解析后的报告（JSON），
便于 LLM 精确提取数值，而非解析原始表格文本。
"""

import json

from mcp.server.fastmcp import Context

from vivado_mcp.analysis.io_parser import parse_report_io
from vivado_mcp.analysis.timing_parser import format_timing_report, parse_timing_summary
from vivado_mcp.server import _NO_SESSION, _require_session, _safe_execute, mcp

# 支持的报告类型 → Tcl 命令映射（白名单，已验证安全）
_REPORT_TYPES = {
    "utilization": "report_utilization",
    "timing": "report_timing_summary",
    "power": "report_power",
    "drc": "report_drc",
    "io": "report_io",
    "clock": "report_clocks",
    "clock_networks": "report_clock_networks",
    "methodology": "report_methodology",
    "cdc": "report_cdc",
    "congestion": "report_design_analysis -congestion",
    "route_status": "report_route_status",
}


@mcp.tool()
async def report(
    report_type: str,
    options: str = "",
    session_id: str = "default",
    timeout: int = 120,
    ctx: Context = None,
) -> str:
    """获取 Vivado 设计报告。

    支持的 report_type:
    - utilization: 资源利用率报告
    - timing: 时序报告摘要
    - power: 功耗报告
    - drc: 设计规则检查
    - io: IO 引脚报告
    - clock: 时钟报告
    - clock_networks: 时钟网络报告
    - methodology: 方法学检查
    - cdc: 跨时钟域报告
    - congestion: 拥塞分析
    - route_status: 布线状态

    Args:
        report_type: 报告类型（见上方列表）。
        options: 额外 Tcl 选项（如 "-max_paths 10"）。
        session_id: 目标会话 ID。
        timeout: 超时秒数，默认 120。
    """
    if report_type not in _REPORT_TYPES:
        available = ", ".join(sorted(_REPORT_TYPES.keys()))
        return (
            f"[ERROR] 未知报告类型 '{report_type}'。\n"
            f"支持的类型: {available}"
        )

    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    tcl_cmd = _REPORT_TYPES[report_type]
    tcl = f"{tcl_cmd} -return_string {options}"

    return await _safe_execute(
        session, tcl, float(timeout), f"生成 {report_type} 报告失败"
    )


@mcp.tool()
async def get_io_report(
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """获取结构化 IO 引脚报告（JSON）。

    执行 report_io 并解析为结构化数据，包含：
    - 每个端口的引脚、站点、方向、IO 标准、Bank
    - GT / GPIO 类型自动判定
    - 汇总统计（总数、GT 数、GPIO 数、未分配数）

    Args:
        session_id: 目标会话 ID。
    """
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    # 直接获取完整输出（不经 _safe_execute，避免 .summary 截断）
    try:
        result = await session.execute(
            "report_io -return_string", timeout=60.0
        )
        io_report = parse_report_io(result.output)
        return json.dumps(io_report.to_dict(), ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[ERROR] 获取 IO 报告失败: {e}"


@mcp.tool()
async def get_timing_report(
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """获取结构化时序报告。

    执行 report_timing_summary 并解析为结构化摘要 + 关键路径详情。
    返回人类可读的中文时序分析报告，包含 PASS/FAIL 状态判定。

    Args:
        session_id: 目标会话 ID。
    """
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    # 直接获取完整输出（不经 _safe_execute，避免 .summary 截断）
    try:
        result = await session.execute(
            "report_timing_summary -return_string", timeout=120.0
        )
        timing_report = parse_timing_summary(result.output)
        return format_timing_report(timing_report)
    except Exception as e:
        return f"[ERROR] 获取时序报告失败: {e}"
