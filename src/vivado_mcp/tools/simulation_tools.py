"""Simulation helpers for bounded Vivado/xsim runs."""

from __future__ import annotations

import re

from mcp.server.fastmcp import Context

from vivado_mcp.server import _NO_SESSION, _require_session, mcp
from vivado_mcp.vivado.tcl_utils import validate_identifier

_RUNTIME_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*(fs|ps|ns|us|ms|s)\s*$", re.IGNORECASE)


def _validate_runtime(runtime: str) -> str:
    runtime = runtime.strip()
    if not _RUNTIME_RE.match(runtime):
        raise ValueError(
            "runtime must look like '300 ns', '10 us', or '1 ms'. "
            "Avoid open-ended 'run all' in MCP simulations."
        )
    return runtime


@mcp.tool()
async def run_behavioral_simulation(
    simset: str = "sim_1",
    runtime: str = "300 ns",
    top: str = "",
    relaunch: bool = True,
    close_after: bool = False,
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """Run a bounded Vivado behavioral simulation.

    This wraps the safe pattern discovered in practice: launch xsim, run for a
    finite duration, report a concise status, and optionally close the sim.
    """
    try:
        simset = validate_identifier(simset, "simset")
        runtime = _validate_runtime(runtime)
        if top:
            top = validate_identifier(top, "top")
    except ValueError as e:
        return f"[ERROR] {e}"

    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)

    lines: list[str] = [
        "set __vmcp_sim_errors 0",
        "set __vmcp_sim_notes {}",
    ]
    if relaunch:
        lines.append("catch {close_sim}")
    if top:
        lines.append(
            f"if {{[catch {{set_property top {top} [get_filesets {simset}]}} __e]}} "
            "{ incr __vmcp_sim_errors; lappend __vmcp_sim_notes \"set_top:$__e\" }"
        )
    lines.extend(
        [
            f"if {{[catch {{launch_simulation -simset {simset} -mode behavioral}} __e]}} "
            "{ incr __vmcp_sim_errors; lappend __vmcp_sim_notes \"launch:$__e\" }",
            "if {$__vmcp_sim_errors == 0 && [catch {run "
            + runtime
            + "} __e]} { incr __vmcp_sim_errors; lappend __vmcp_sim_notes \"run:$__e\" }",
            "if {[catch {set __vmcp_now [current_time]}]} { set __vmcp_now unknown }",
            'puts "VMCP_SIM|errors=$__vmcp_sim_errors|time=$__vmcp_now|notes=$__vmcp_sim_notes"',
        ]
    )
    if close_after:
        lines.append("catch {close_sim}")

    try:
        result = await session.execute("\n".join(lines), timeout=120.0)
    except Exception as e:
        return f"[ERROR] 前仿真执行失败: {e}"

    marker = next(
        (line for line in result.output.splitlines() if line.startswith("VMCP_SIM|")),
        "",
    )
    if result.is_error:
        return f"[ERROR] 前仿真 Tcl 返回错误:\n{result.output}"
    if "errors=0" not in marker:
        return f"[ERROR] 前仿真未完成:\n{result.output}"

    return (
        "--- 前仿真结果 ---\n"
        f"simset: {simset}\n"
        f"runtime: {runtime}\n"
        f"{marker}"
    )
