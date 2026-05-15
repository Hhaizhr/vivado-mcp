from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vivado_mcp.vivado.tcl_utils import TclResult


def _make_tcl_result(output: str, return_code: int = 0) -> TclResult:
    return TclResult(output=output, return_code=return_code, is_error=return_code != 0)


def _mock_context():
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    return ctx


def test_format_bd_interrupts():
    from vivado_mcp.tools.bd_tools import _format_bd_interrupts

    raw = "\n".join(
        [
            "VMCP_BD_INTR_DESIGN:ps_pl_irq",
            "VMCP_BD_INTR_PIN:/axi_timer_0/interrupt|O|LEVEL_HIGH|/irq_net|/xlconcat_0/In0",
            "VMCP_BD_PS7:/ps7_0|PCW_USE_FABRIC_INTERRUPT=1|PCW_IRQ_F2P_INTR=1",
            "VMCP_BD_INTR_DONE",
        ]
    )

    text = _format_bd_interrupts(raw)

    assert "ps_pl_irq" in text
    assert "/axi_timer_0/interrupt" in text
    assert "/xlconcat_0/In0" in text
    assert "PCW_IRQ_F2P_INTR=1" in text


@pytest.mark.asyncio
async def test_inspect_bd_interrupts_uses_session():
    from vivado_mcp.tools.bd_tools import inspect_bd_interrupts

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=_make_tcl_result(
            "VMCP_BD_INTR_DESIGN:bd\n"
            "VMCP_BD_INTR_PIN:/ip/intr|O|LEVEL_HIGH|/net|/ps7_0/IRQ_F2P\n"
            "VMCP_BD_INTR_DONE"
        )
    )

    with patch("vivado_mcp.tools.bd_tools._require_session", return_value=session):
        result = await inspect_bd_interrupts(ctx=_mock_context())

    assert "BD interrupt inspection" in result
    assert "/ip/intr" in result


@pytest.mark.asyncio
async def test_verify_zynq_interrupt_wiring_reports_passes():
    from vivado_mcp.tools.bd_tools import verify_zynq_interrupt_wiring

    report = "\n".join(
        [
            "--- BD interrupt inspection ---",
            "design: bd",
            "interrupt pins (1):",
            "  - /ip/intr: dir=O, sensitivity=LEVEL_HIGH, net=/net, peers=/ps7_0/IRQ_F2P",
            "processing_system7 cells (1):",
            "  - /ps7_0|PCW_USE_FABRIC_INTERRUPT=1|PCW_IRQ_F2P_INTR=1",
        ]
    )

    with patch("vivado_mcp.tools.bd_tools.inspect_bd_interrupts", return_value=report):
        result = await verify_zynq_interrupt_wiring(ctx=_mock_context())

    assert "PASS: processing_system7 present" in result
    assert "PASS: fabric interrupt enabled" in result
    assert "PASS: IRQ_F2P enabled" in result
