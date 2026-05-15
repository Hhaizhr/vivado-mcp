"""Vitis / XSCT helper tools."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from mcp.server.fastmcp import Context

from vivado_mcp.config import find_xsct, normalize_path
from vivado_mcp.server import mcp
from vivado_mcp.vivado.tcl_utils import to_tcl_path, validate_identifier


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
}}
hsi::close_hw_design [hsi::current_hw_design]
"""
    try:
        rc, output = _run_xsct(script, xsct_path=xsct_path, timeout=timeout_seconds)
    except Exception as e:
        return f"[ERROR] XSCT 执行失败: {e}"
    if rc != 0:
        return f"[ERROR] XSCT inspect_xsa 失败（rc={rc}）：\n{output}"
    return "--- XSA inspect result ---\n" + output


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
