from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vivado_mcp.vivado.tcl_utils import TclResult


def _make_tcl_result(output: str, return_code: int = 0) -> TclResult:
    return TclResult(output=output, return_code=return_code, is_error=return_code != 0)


def _mock_context():
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    return ctx


def test_bitstream_complete_requires_write_bitstream_step():
    from vivado_mcp.tools.flow_tools import _is_bitstream_complete

    assert _is_bitstream_complete("write_bitstream Complete!")
    assert not _is_bitstream_complete("route_design Complete!")
    assert not _is_bitstream_complete("write_bitstream Running")


@pytest.mark.asyncio
async def test_run_behavioral_simulation_rejects_unbounded_runtime():
    from vivado_mcp.tools.simulation_tools import run_behavioral_simulation

    result = await run_behavioral_simulation(runtime="all", ctx=_mock_context())

    assert "[ERROR]" in result
    assert "Avoid open-ended" in result


@pytest.mark.asyncio
async def test_run_behavioral_simulation_executes_bounded_runtime():
    from vivado_mcp.tools.simulation_tools import run_behavioral_simulation

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=_make_tcl_result("VMCP_SIM|errors=0|time=300 ns|notes=")
    )

    with patch("vivado_mcp.tools.simulation_tools._require_session", return_value=session):
        result = await run_behavioral_simulation(runtime="300 ns", ctx=_mock_context())

    assert "--- 前仿真结果 ---" in result
    assert "runtime: 300 ns" in result
    tcl = session.execute.call_args.args[0]
    assert "launch_simulation -simset sim_1 -mode behavioral" in tcl
    assert "run {300 ns}" in tcl
