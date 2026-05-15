"""Block Design inspection helpers."""

from __future__ import annotations

from mcp.server.fastmcp import Context

from vivado_mcp.server import _NO_SESSION, _require_session, mcp

_INSPECT_BD_INTERRUPTS_TCL = r"""\
if {[catch {current_bd_design} __bd]} {
    puts "VMCP_BD_INTR_ERROR:no current block design"
} else {
    puts "VMCP_BD_INTR_DESIGN:$__bd"
    set __pins [get_bd_pins -quiet -hier -filter {TYPE == intr || TYPE == INTERRUPT}]
    foreach __p $__pins {
        set __dir ""
        set __sens ""
        catch {set __dir [get_property DIR $__p]}
        catch {set __sens [get_property CONFIG.SENSITIVITY $__p]}
        if {$__sens eq ""} { catch {set __sens [get_property SENSITIVITY $__p]} }
        set __net [get_bd_nets -quiet -of_objects $__p]
        if {$__net eq ""} {
            puts "VMCP_BD_INTR_PIN:$__p|$__dir|$__sens|UNCONNECTED|"
        } else {
            set __others [list]
            foreach __q [get_bd_pins -quiet -of_objects $__net] {
                if {$__q ne $__p} { lappend __others $__q }
            }
            puts "VMCP_BD_INTR_PIN:$__p|$__dir|$__sens|$__net|[join $__others ,]"
        }
    }
    foreach __ps [get_bd_cells -quiet -hier -filter {VLNV =~ *processing_system7*}] {
        set __use_irq ""
        set __irq_f2p ""
        catch {set __use_irq [get_property CONFIG.PCW_USE_FABRIC_INTERRUPT $__ps]}
        catch {set __irq_f2p [get_property CONFIG.PCW_IRQ_F2P_INTR $__ps]}
        puts "VMCP_BD_PS7:$__ps|PCW_USE_FABRIC_INTERRUPT=$__use_irq|PCW_IRQ_F2P_INTR=$__irq_f2p"
    }
    puts "VMCP_BD_INTR_DONE"
}
"""


def _format_bd_interrupts(raw: str) -> str:
    design = ""
    pins: list[dict[str, str]] = []
    ps7: list[str] = []
    error = ""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("VMCP_BD_INTR_ERROR:"):
            error = line.split(":", 1)[1].strip()
        elif line.startswith("VMCP_BD_INTR_DESIGN:"):
            design = line.split(":", 1)[1].strip()
        elif line.startswith("VMCP_BD_INTR_PIN:"):
            parts = line.split(":", 1)[1].split("|")
            if len(parts) >= 5:
                pins.append(
                    {
                        "pin": parts[0],
                        "dir": parts[1] or "?",
                        "sens": parts[2] or "?",
                        "net": parts[3] or "UNCONNECTED",
                        "peers": parts[4] or "",
                    }
                )
        elif line.startswith("VMCP_BD_PS7:"):
            ps7.append(line.split(":", 1)[1].strip())

    if error:
        return f"[ERROR] {error}"

    lines = ["--- BD interrupt inspection ---", f"design: {design or '(unknown)'}"]
    lines.append("")
    lines.append(f"interrupt pins ({len(pins)}):")
    for p in pins:
        peers = p["peers"] if p["peers"] else "(no peers)"
        lines.append(
            f"  - {p['pin']}: dir={p['dir']}, sensitivity={p['sens']}, "
            f"net={p['net']}, peers={peers}"
        )
    if not pins:
        lines.append("  (none found)")
    lines.append("")
    lines.append(f"processing_system7 cells ({len(ps7)}):")
    lines.extend(f"  - {item}" for item in ps7)
    if not ps7:
        lines.append("  (none found)")
    return "\n".join(lines)


@mcp.tool()
async def inspect_bd_interrupts(
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """Inspect interrupt pins and nets in the current block design."""
    session = _require_session(ctx, session_id)
    if not session:
        return _NO_SESSION.format(sid=session_id)
    try:
        result = await session.execute(_INSPECT_BD_INTERRUPTS_TCL, timeout=30.0)
    except Exception as e:
        return f"[ERROR] 查询 BD 中断失败: {e}"
    if result.is_error:
        return f"[ERROR] 查询 BD 中断失败（rc={result.return_code}）：\n{result.output}"
    return _format_bd_interrupts(result.output)


@mcp.tool()
async def verify_zynq_interrupt_wiring(
    session_id: str = "default",
    ctx: Context = None,
) -> str:
    """Check common Zynq PS-PL interrupt wiring expectations in the current BD."""
    report = await inspect_bd_interrupts(session_id=session_id, ctx=ctx)
    if report.startswith("[ERROR]"):
        return report

    has_ps7 = "processing_system7 cells (0)" not in report
    fabric_enabled = "PCW_USE_FABRIC_INTERRUPT=1" in report
    irq_f2p_enabled = "PCW_IRQ_F2P_INTR=1" in report
    has_connected_intr = "UNCONNECTED" not in "\n".join(
        line for line in report.splitlines() if line.strip().startswith("- ")
    )

    lines = ["--- Zynq interrupt wiring check ---"]
    checks = [
        ("processing_system7 present", has_ps7),
        ("fabric interrupt enabled", fabric_enabled),
        ("IRQ_F2P enabled", irq_f2p_enabled),
        ("interrupt pins connected", has_connected_intr),
    ]
    for name, ok in checks:
        lines.append(f"{'PASS' if ok else 'WARN'}: {name}")
    lines.append("")
    lines.append(report)
    return "\n".join(lines)
