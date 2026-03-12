"""设计流程工具。

run_synthesis / run_implementation / generate_bitstream / get_status / program_device。
封装 Vivado 长时间运行的操作，提供超时管理和进度反馈。
综合/实现完成后自动执行警告诊断，bitstream 生成前自动安全检查。
"""

from mcp.server.fastmcp import Context

from vivado_mcp.analysis.warning_parser import parse_diag_counts, parse_pre_bitstream
from vivado_mcp.server import _NO_SESSION, _require_session, _safe_execute, mcp
from vivado_mcp.tcl_scripts import CHECK_PRE_BITSTREAM, COUNT_WARNINGS
from vivado_mcp.vivado.tcl_utils import to_tcl_path, validate_identifier

# --------------------------------------------------------------------------- #
#  内部辅助：综合 / 实现共享的 launch-and-wait 逻辑
# --------------------------------------------------------------------------- #

async def _launch_and_wait(
    session,
    run_name: str,
    jobs: int,
    timeout_minutes: int,
    label: str,
    ctx: Context,
) -> str:
    """执行 reset_run → launch_runs → wait_on_run → 查询状态。

    综合与实现的核心流程完全相同，仅标签不同。
    """
    timeout_sec = timeout_minutes * 60.0

    tcl = (
        f"reset_run {run_name}\n"
        f"launch_runs {run_name} -jobs {jobs}\n"
        f"wait_on_run {run_name} -timeout {timeout_minutes}"
    )

    try:
        await ctx.report_progress(progress=0, total=1)
        result = await session.execute(tcl, timeout=timeout_sec + 60)
        # 追加运行状态
        status_result = await session.execute(
            f'set s [get_property STATUS [get_runs {run_name}]]; '
            f'set p [get_property STATS.ELAPSED [get_runs {run_name}]]; '
            f'puts "状态: $s | 耗时: $p"',
            timeout=10.0,
        )
        await ctx.report_progress(progress=1, total=1)

        parts: list[str] = [
            f"{result.summary}\n\n--- {label}结果 ---\n{status_result.output}"
        ]

        # 自动诊断：统计 runme.log 中的 error / critical_warning / warning
        try:
            diag_result = await session.execute(
                COUNT_WARNINGS.format(run_name=run_name), timeout=30.0
            )
            errors, cw, w = parse_diag_counts(diag_result.output)
            if cw > 0:
                parts.insert(
                    0,
                    f"!! 发现 {cw} 条 CRITICAL WARNING !! "
                    "建议立即运行 get_critical_warnings 查看分类详情和修复建议。",
                )
            if errors > 0:
                parts.insert(
                    0,
                    f"!! 发现 {errors} 条 ERROR !!"
                    " 请检查 runme.log 详情。",
                )
            parts.append(
                f"\n诊断概览: errors={errors},"
                f" critical_warnings={cw}, warnings={w}"
            )
        except Exception:
            # 诊断失败不应影响主流程返回
            pass

        return "\n".join(parts)
    except Exception as e:
        return f"[ERROR] {label}失败: {e}"


# --------------------------------------------------------------------------- #
#  工具定义
# --------------------------------------------------------------------------- #

@mcp.tool()
async def run_synthesis(
    run_name: str = "synth_1",
    jobs: int = 4,
    timeout_minutes: int = 30,
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """运行综合。自动执行 reset_run → launch_runs → wait_on_run。

    Args:
        run_name: 综合 run 名称，默认 "synth_1"。
        jobs: 并行任务数，默认 4。
        timeout_minutes: 超时分钟数，默认 30。
        session_id: 目标会话 ID。
    """
    try:
        run_name = validate_identifier(run_name, "run_name")
    except ValueError as e:
        return f"[ERROR] {e}"

    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    return await _launch_and_wait(
        session, run_name, jobs, timeout_minutes, "综合", ctx
    )


@mcp.tool()
async def run_implementation(
    run_name: str = "impl_1",
    jobs: int = 4,
    timeout_minutes: int = 60,
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """运行实现（布局布线）。自动执行 reset_run → launch_runs → wait_on_run。

    Args:
        run_name: 实现 run 名称，默认 "impl_1"。
        jobs: 并行任务数，默认 4。
        timeout_minutes: 超时分钟数，默认 60。
        session_id: 目标会话 ID。
    """
    try:
        run_name = validate_identifier(run_name, "run_name")
    except ValueError as e:
        return f"[ERROR] {e}"

    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    return await _launch_and_wait(
        session, run_name, jobs, timeout_minutes, "实现", ctx
    )


@mcp.tool()
async def generate_bitstream(
    impl_run: str = "impl_1",
    jobs: int = 4,
    timeout_minutes: int = 30,
    force: bool = False,
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """生成比特流文件。在实现完成后执行。

    默认启用前置安全检查：检测 CRITICAL WARNING 后阻止生成，
    需确认无风险后使用 force=True 跳过检查。

    Args:
        impl_run: 实现 run 名称，默认 "impl_1"。
        jobs: 并行任务数，默认 4。
        timeout_minutes: 超时分钟数，默认 30。
        force: 跳过 CRITICAL WARNING 安全检查，默认 False。
        session_id: 目标会话 ID。
    """
    try:
        impl_run = validate_identifier(impl_run, "impl_run")
    except ValueError as e:
        return f"[ERROR] {e}"

    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    # 前置安全检查：force=False 时检测 CRITICAL WARNING
    if not force:
        try:
            pre_result = await session.execute(
                CHECK_PRE_BITSTREAM.format(impl_run=impl_run), timeout=30.0
            )
            status, cw_count, samples = parse_pre_bitstream(pre_result.output)

            if cw_count > 0:
                lines = [
                    f"!! 安全检查未通过: 发现 {cw_count} 条 CRITICAL WARNING !!",
                    f"实现状态: {status}",
                    "",
                    "前 10 条 CRITICAL WARNING 样本:",
                ]
                for s in samples:
                    lines.append(f"  - {s}")
                lines.append("")
                lines.append(
                    "建议: 先运行 get_critical_warnings 查看详情并修复。"
                )
                lines.append(
                    "如确认可忽略，请使用 force=True 跳过安全检查。"
                )
                return "\n".join(lines)
        except Exception:
            # 安全检查本身失败不应阻塞——降级为跳过检查
            pass

    timeout_sec = timeout_minutes * 60.0

    tcl = (
        f"launch_runs {impl_run} -to_step write_bitstream -jobs {jobs}\n"
        f"wait_on_run {impl_run} -timeout {timeout_minutes}"
    )

    try:
        await ctx.report_progress(progress=0, total=1)
        result = await session.execute(tcl, timeout=timeout_sec + 60)
        bit_result = await session.execute(
            f'set d [get_property DIRECTORY [get_runs {impl_run}]]; '
            f'puts "比特流目录: $d"',
            timeout=10.0,
        )
        await ctx.report_progress(progress=1, total=1)
        return f"{result.summary}\n\n{bit_result.output}"
    except Exception as e:
        return f"[ERROR] 生成比特流失败: {e}"


@mcp.tool()
async def get_status(
    run_name: str = "",
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """查询 Vivado 运行状态。

    Args:
        run_name: 指定 run 名称（如 "synth_1"、"impl_1"）。留空则显示所有 run 的状态。
        session_id: 目标会话 ID。
    """
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    if run_name:
        try:
            run_name = validate_identifier(run_name, "run_name")
        except ValueError as e:
            return f"[ERROR] {e}"
        tcl = (
            f'set r [get_runs {run_name}]\n'
            f'set s [get_property STATUS $r]\n'
            f'set p [get_property PROGRESS $r]\n'
            f'set e [get_property STATS.ELAPSED $r]\n'
            f'puts "Run: {run_name}"\n'
            f'puts "状态: $s"\n'
            f'puts "进度: $p"\n'
            f'puts "耗时: $e"'
        )
    else:
        tcl = (
            'foreach r [get_runs] {\n'
            '  set s [get_property STATUS $r]\n'
            '  set p [get_property PROGRESS $r]\n'
            '  puts "[get_property NAME $r]: $s ($p)"\n'
            '}'
        )

    return await _safe_execute(session, tcl, 15.0, "查询状态失败")


@mcp.tool()
async def program_device(
    bitstream_path: str,
    target: str = "*",
    hw_server_url: str = "localhost:3121",
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """编程 FPGA 设备。封装 open_hw_manager → connect → program 多步操作。

    Args:
        bitstream_path: 比特流文件路径（.bit 文件）。
        target: 目标设备过滤器，默认 "*"（第一个可用设备）。
        hw_server_url: 硬件服务器地址，默认 "localhost:3121"。
        session_id: 目标会话 ID。
    """
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    bit_tcl = to_tcl_path(bitstream_path)

    tcl = (
        f'open_hw_manager\n'
        f'connect_hw_server -url {hw_server_url}\n'
        f'open_hw_target [lindex [get_hw_targets {target}] 0]\n'
        f'set dev [lindex [get_hw_devices] 0]\n'
        f'current_hw_device $dev\n'
        f'set_property PROGRAM.FILE {bit_tcl} $dev\n'
        f'program_hw_devices $dev\n'
        f'puts "编程完成: $dev"'
    )

    return await _safe_execute(session, tcl, 60.0, "编程设备失败")
