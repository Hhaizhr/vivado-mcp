"""Vitis / XSCT helper tools."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from mcp.server.fastmcp import Context

from vivado_mcp.config import find_xsct, normalize_path
from vivado_mcp.server import mcp
from vivado_mcp.vivado.tcl_utils import to_tcl_path, validate_identifier

_SAFE_RELATIVE_SOURCE_RE = re.compile(r"^[A-Za-z0-9_./\\:-]{1,240}$")


def _run_xsct(script: str, xsct_path: str = "", timeout: int = 300) -> tuple[int, str]:
    exe = find_xsct(xsct_path or None)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".tcl",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(script)
        script_path = tmp.name
    try:
        cmd = [exe, script_path]
        env = os.environ.copy()
        if exe.lower().endswith(".bat"):
            cmd = ["cmd", "/c", exe, script_path]
            # Xilinx 2019.2 batch launchers infer win32/win64 from these vars.
            # Codex/MCP can inherit a reduced environment that makes loader.bat
            # choose win32.o, which does not exist on this install.
            env["PROCESSOR_ARCHITECTURE"] = "AMD64"
            env.setdefault("PROCESSOR_ARCHITEW6432", "AMD64")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _format_xsa_summary(raw: str) -> str:
    processors: list[str] = []
    cells: list[tuple[str, str]] = []
    mem_ranges: list[dict[str, str]] = []
    interrupt_pins: list[dict[str, str]] = []

    for line in raw.splitlines():
        if line.startswith("VMCP_XSA_PROCESSOR:"):
            processors.append(line.split(":", 1)[1].strip())
        elif line.startswith("VMCP_XSA_CELL:"):
            name, _, vlnv = line.split(":", 1)[1].partition("|")
            cells.append((name.strip(), vlnv.strip()))
        elif line.startswith("VMCP_XSA_MEM:"):
            parts = line.split(":", 1)[1].split("|")
            if len(parts) >= 6:
                mem_ranges.append(
                    {
                        "instance": parts[0],
                        "base": parts[1],
                        "high": parts[2],
                        "type": parts[3],
                        "master": parts[4],
                        "slave": parts[5],
                    }
                )
        elif line.startswith("VMCP_XSA_INTR:"):
            parts = line.split(":", 1)[1].split("|")
            if len(parts) >= 4:
                interrupt_pins.append(
                    {
                        "cell": parts[0],
                        "pin": parts[1],
                        "direction": parts[2],
                        "sensitivity": parts[3],
                    }
                )

    lines = ["--- XSA summary ---"]
    lines.append(f"Processors ({len(processors)}):")
    lines.extend(f"  - {p}" for p in processors[:10])
    if not processors:
        lines.append("  (none found)")

    user_cells = [
        (name, vlnv)
        for name, vlnv in cells
        if not name.startswith("ps7_") or name == "ps7_0"
    ]
    lines.append("")
    lines.append(f"Design cells ({len(user_cells)} shown / {len(cells)} total):")
    for name, vlnv in user_cells[:20]:
        lines.append(f"  - {name}: {vlnv}")
    if len(user_cells) > 20:
        lines.append(f"  ... {len(user_cells) - 20} more")

    user_mems = [
        m
        for m in mem_ranges
        if not m["instance"].startswith("ps7_") or m["instance"] in {"ps7_ddr_0", "ps7_ram_0"}
    ]
    lines.append("")
    lines.append(f"Address ranges ({len(user_mems)} shown / {len(mem_ranges)} total):")
    for mem in user_mems[:20]:
        lines.append(
            "  - {instance}: {base}..{high} ({type}, master={master}, slave={slave})".format(
                **mem
            )
        )
    if len(user_mems) > 20:
        lines.append(f"  ... {len(user_mems) - 20} more")

    lines.append("")
    lines.append(f"Interrupt pins ({len(interrupt_pins)}):")
    for intr in interrupt_pins[:20]:
        lines.append(
            "  - {cell}/{pin}: dir={direction}, sensitivity={sensitivity}".format(
                **intr
            )
        )
    if not interrupt_pins:
        lines.append("  (none found)")
    if len(interrupt_pins) > 20:
        lines.append(f"  ... {len(interrupt_pins) - 20} more")

    return "\n".join(lines)


@mcp.tool()
async def locate_xsct(xsct_path: str = "", ctx: Context = None) -> str:
    """Locate the XSCT executable used by Vitis automation."""
    try:
        path = find_xsct(xsct_path or None)
    except FileNotFoundError as e:
        return f"[ERROR] {e}"
    return f"XSCT: {path}"


@mcp.tool()
async def inspect_xsa(
    xsa_path: str,
    xsct_path: str = "",
    timeout_seconds: int = 120,
    ctx: Context = None,
) -> str:
    """Inspect an exported XSA with XSCT/HSI and summarize processors and IP."""
    if not Path(xsa_path).is_file():
        return f"[ERROR] XSA 文件不存在: {xsa_path}"
    script = f"""\
hsi::open_hw_design {to_tcl_path(xsa_path)}
puts "VMCP_XSA:name=[file tail {to_tcl_path(xsa_path)}]"
foreach __p [hsi::get_cells -filter {{IP_TYPE==PROCESSOR}}] {{
    puts "VMCP_XSA_PROCESSOR:$__p"
}}
foreach __c [hsi::get_cells] {{
    set __vlnv ""
    catch {{set __vlnv [common::get_property VLNV $__c]}}
    if {{$__vlnv ne ""}} {{
        puts "VMCP_XSA_CELL:$__c|$__vlnv"
    }}
    foreach __p [hsi::get_pins -of_objects $__c] {{
        set __type ""
        catch {{set __type [common::get_property TYPE $__p]}}
        if {{$__type eq "INTERRUPT"}} {{
            set __dir ""
            set __sens ""
            catch {{set __dir [common::get_property DIRECTION $__p]}}
            catch {{set __sens [common::get_property SENSITIVITY $__p]}}
            puts "VMCP_XSA_INTR:$__c|$__p|$__dir|$__sens"
        }}
    }}
}}
foreach __m [hsi::get_mem_ranges] {{
    set __inst ""
    set __base ""
    set __high ""
    set __type ""
    set __master ""
    set __slave ""
    catch {{set __inst [common::get_property INSTANCE $__m]}}
    catch {{set __base [common::get_property BASE_VALUE $__m]}}
    catch {{set __high [common::get_property HIGH_VALUE $__m]}}
    catch {{set __type [common::get_property MEM_TYPE $__m]}}
    catch {{set __master [common::get_property MASTER_INTERFACE $__m]}}
    catch {{set __slave [common::get_property SLAVE_INTERFACE $__m]}}
    puts "VMCP_XSA_MEM:$__inst|$__base|$__high|$__type|$__master|$__slave"
}}
hsi::close_hw_design [hsi::current_hw_design]
"""
    try:
        rc, output = _run_xsct(script, xsct_path=xsct_path, timeout=timeout_seconds)
    except Exception as e:
        return f"[ERROR] XSCT 执行失败: {e}"
    if rc != 0:
        return f"[ERROR] XSCT inspect_xsa 失败（rc={rc}）：\n{output}"
    return _format_xsa_summary(output) + "\n\n--- Raw XSA inspect result ---\n" + output


@mcp.tool()
async def create_vitis_baremetal_app(
    xsa_path: str,
    workspace: str,
    platform_name: str,
    app_name: str,
    processor: str = "ps7_cortexa9_0",
    os_name: str = "standalone",
    template: str = "Empty Application",
    xsct_path: str = "",
    timeout_seconds: int = 300,
    ctx: Context = None,
) -> str:
    """Create a Vitis platform and bare-metal application from an XSA."""
    if not Path(xsa_path).is_file():
        return f"[ERROR] XSA 文件不存在: {xsa_path}"
    try:
        platform_name = validate_identifier(platform_name, "platform_name")
        app_name = validate_identifier(app_name, "app_name")
        processor = validate_identifier(processor, "processor")
        os_name = validate_identifier(os_name, "os_name")
    except ValueError as e:
        return f"[ERROR] {e}"

    Path(workspace).mkdir(parents=True, exist_ok=True)
    script = f"""\
setws {to_tcl_path(workspace)}
platform create -name {platform_name} -hw {to_tcl_path(xsa_path)} -out {to_tcl_path(workspace)}
platform active {platform_name}
domain create -name {processor}_{os_name} -os {os_name} -proc {processor}
platform generate
app create -name {app_name} -platform {platform_name} \\
    -domain {processor}_{os_name} -template {to_tcl_path(template)}
puts "VMCP_VITIS_APP:{normalize_path(str(Path(workspace) / app_name))}"
"""
    try:
        rc, output = _run_xsct(script, xsct_path=xsct_path, timeout=timeout_seconds)
    except Exception as e:
        return f"[ERROR] XSCT 执行失败: {e}"
    if rc != 0:
        return f"[ERROR] 创建 Vitis 裸机工程失败（rc={rc}）：\n{output}"
    return "--- Vitis bare-metal app created ---\n" + output


@mcp.tool()
async def build_vitis_app(
    workspace: str,
    app_name: str,
    xsct_path: str = "",
    timeout_seconds: int = 300,
    ctx: Context = None,
) -> str:
    """Build an existing Vitis application with XSCT."""
    try:
        app_name = validate_identifier(app_name, "app_name")
    except ValueError as e:
        return f"[ERROR] {e}"
    if not Path(workspace).is_dir():
        return f"[ERROR] workspace 不存在: {workspace}"
    script = f"""\
setws {to_tcl_path(workspace)}
app build -name {app_name}
puts "VMCP_VITIS_BUILD_DONE:{app_name}"
"""
    try:
        rc, output = _run_xsct(script, xsct_path=xsct_path, timeout=timeout_seconds)
    except Exception as e:
        return f"[ERROR] XSCT 执行失败: {e}"
    if rc != 0:
        return f"[ERROR] Vitis app build 失败（rc={rc}）：\n{output}"
    return "--- Vitis app build result ---\n" + output


@mcp.tool()
async def write_vitis_source_file(
    workspace: str,
    app_name: str,
    relative_path: str,
    content: str,
    build_after: bool = False,
    xsct_path: str = "",
    timeout_seconds: int = 300,
    ctx: Context = None,
) -> str:
    """Write a source file inside a Vitis app and optionally build the app."""
    try:
        app_name = validate_identifier(app_name, "app_name")
    except ValueError as e:
        return f"[ERROR] {e}"
    if not _SAFE_RELATIVE_SOURCE_RE.match(relative_path):
        return "[ERROR] relative_path 含非法字符。"
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        return "[ERROR] relative_path 必须是 app 内部相对路径，不能包含 '..'。"

    app_dir = Path(workspace) / app_name
    if not app_dir.is_dir():
        return f"[ERROR] Vitis app 目录不存在: {app_dir}"

    target = (app_dir / relative_path).resolve()
    app_root = app_dir.resolve()
    if app_root not in target.parents and target != app_root:
        return f"[ERROR] 目标文件超出 app 目录: {target}"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")

    lines = [
        "--- Vitis source file written ---",
        f"file: {normalize_path(str(target))}",
        f"bytes: {target.stat().st_size}",
    ]
    if build_after:
        build = await build_vitis_app(
            workspace=workspace,
            app_name=app_name,
            xsct_path=xsct_path,
            timeout_seconds=timeout_seconds,
            ctx=ctx,
        )
        lines.append("")
        lines.append(build)
    return "\n".join(lines)
