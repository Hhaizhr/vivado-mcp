"""Vitis / XSCT helper tools."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from mcp.server.fastmcp import Context

from vivado_mcp.config import find_xsct, normalize_path
from vivado_mcp.server import mcp
from vivado_mcp.vivado.tcl_utils import to_tcl_path, validate_identifier

_SAFE_RELATIVE_SOURCE_RE = re.compile(r"^[A-Za-z0-9_./\\:-]{1,240}$")
_BSP_MACRO_RE = re.compile(r"^#define\s+((?:XPAR|XPS)_[A-Za-z0-9_]+)\s+(.+?)\s*$")


def _tail_text(path: Path, max_lines: int = 80) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-max_lines:]


def _interesting_log_lines(lines: list[str], max_lines: int = 40) -> list[str]:
    needles = ("ERROR", "Exception", "Invalid Workspace", "reset", "NPE", "NullPointer")
    interesting = [line for line in lines if any(needle in line for needle in needles)]
    return (interesting or lines)[-max_lines:]


def _inspect_xsa_archive(xsa_path: str) -> dict[str, list[str] | str]:
    path = Path(xsa_path)
    info: dict[str, list[str] | str] = {
        "bit_files": [],
        "hwh_files": [],
        "mmi_files": [],
        "xsa_files": [],
        "other_hw_files": [],
    }
    if not zipfile.is_zipfile(path):
        info["error"] = "not a zip-format XSA"
        return info

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        info["error"] = str(exc)
        return info

    suffix_map = {
        ".bit": "bit_files",
        ".hwh": "hwh_files",
        ".mmi": "mmi_files",
        ".xsa": "xsa_files",
    }
    for name in names:
        lower = name.lower()
        for suffix, key in suffix_map.items():
            if lower.endswith(suffix):
                values = info[key]
                assert isinstance(values, list)
                values.append(name)
                break
        else:
            if "/hw/" in lower or lower.startswith("hw/"):
                values = info["other_hw_files"]
                assert isinstance(values, list)
                values.append(name)
    return info


def _format_xsa_archive_summary(xsa_path: str) -> str:
    info = _inspect_xsa_archive(xsa_path)
    lines = ["--- XSA archive summary ---"]
    error = info.get("error")
    if isinstance(error, str):
        lines.append(f"archive: {error}")
        return "\n".join(lines)

    bit_files = info["bit_files"]
    hwh_files = info["hwh_files"]
    assert isinstance(bit_files, list)
    assert isinstance(hwh_files, list)
    lines.append(f"bitstream embedded: {'yes' if bit_files else 'no'}")
    for label in ("bit_files", "hwh_files", "mmi_files", "xsa_files"):
        values = info[label]
        assert isinstance(values, list)
        lines.append(f"{label} ({len(values)}):")
        if values:
            lines.extend(f"  - {value}" for value in values[:20])
            if len(values) > 20:
                lines.append(f"  ... {len(values) - 20} more")
        else:
            lines.append("  (none found)")
    return "\n".join(lines)


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
    seen_mem_ranges: set[tuple[str, str, str, str, str, str]] = set()
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
                key = tuple(parts[:6])
                if key in seen_mem_ranges:
                    continue
                seen_mem_ranges.add(key)
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
    return (
        _format_xsa_archive_summary(xsa_path)
        + "\n\n"
        + _format_xsa_summary(output)
        + "\n\n--- Raw XSA inspect result ---\n"
        + output
    )


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
        return (
            f"[ERROR] Vitis app build 失败（rc={rc}）：\n{output}\n\n"
            "Hint: 如果看到 Invalid Workspace / XSCT channel reset，先调用 "
            "diagnose_vitis_workspace(workspace=...) 检查 metadata、project 和日志；"
            "不要继续尝试操控 Vitis GUI 打开文件。"
        )
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


@mcp.tool()
async def diagnose_vitis_workspace(
    workspace: str,
    app_name: str = "",
    platform_name: str = "",
    log_lines: int = 80,
    ctx: Context = None,
) -> str:
    """Diagnose Vitis workspace metadata, projects, logs, and app build outputs."""
    ws = Path(workspace)
    if not ws.is_dir():
        return f"[ERROR] workspace 不存在: {workspace}"

    lines = ["--- Vitis workspace diagnostics ---", f"workspace: {normalize_path(str(ws))}"]

    metadata = ws / ".metadata"
    lines.append(f"metadata: {'present' if metadata.is_dir() else 'missing'}")
    log = metadata / ".log"
    if log.is_file():
        lines.append(f"log: {normalize_path(str(log))}")
        tail = _tail_text(log, max_lines=max(1, int(log_lines)))
        interesting = _interesting_log_lines(tail)
        if interesting:
            lines.append("log highlights:")
            lines.extend(f"  {line}" for line in interesting)
    else:
        lines.append("log: missing")

    projects: list[Path] = []
    for child in sorted(ws.iterdir()):
        if child.is_dir() and (child / ".project").is_file():
            projects.append(child)

    lines.append("")
    lines.append(f"projects ({len(projects)}):")
    if projects:
        for project in projects[:30]:
            markers = []
            if (project / ".cproject").is_file():
                markers.append("cproject")
            if (project / ".sdkproject").is_file():
                markers.append("sdkproject")
            if (project / "src").is_dir():
                markers.append("src")
            if (project / "Debug" / "makefile").is_file():
                markers.append("Debug/makefile")
            elf_count = len(list(project.rglob("*.elf")))
            if elf_count:
                markers.append(f"elf={elf_count}")
            suffix = f" [{', '.join(markers)}]" if markers else ""
            lines.append(f"  - {project.name}{suffix}")
    else:
        lines.append("  (none found)")

    if app_name:
        try:
            app_name = validate_identifier(app_name, "app_name")
        except ValueError as e:
            return f"[ERROR] {e}"
        app_dir = ws / app_name
        lines.append("")
        lines.append(f"app: {app_name}")
        lines.append(f"  dir: {'present' if app_dir.is_dir() else 'missing'}")
        if app_dir.is_dir():
            src_dir = app_dir / "src"
            src_files = (
                sorted(p.name for p in src_dir.glob("*") if p.is_file())
                if src_dir.is_dir()
                else []
            )
            lines.append(f"  src files ({len(src_files)}): {', '.join(src_files[:30]) or '(none)'}")
            debug_dir = app_dir / "Debug"
            makefile_state = "present" if (debug_dir / "makefile").is_file() else "missing"
            lines.append(f"  Debug/makefile: {makefile_state}")
            elfs = sorted(app_dir.rglob("*.elf"))
            lines.append(f"  ELF files ({len(elfs)}):")
            lines.extend(f"    - {normalize_path(str(path))}" for path in elfs[:10])
            if not elfs:
                lines.append("    (none found)")

    if platform_name:
        try:
            platform_name = validate_identifier(platform_name, "platform_name")
        except ValueError as e:
            return f"[ERROR] {e}"
        platform_dir = ws / platform_name
        lines.append("")
        lines.append(f"platform: {platform_name}")
        lines.append(f"  dir: {'present' if platform_dir.is_dir() else 'missing'}")
        if platform_dir.is_dir():
            xparams = sorted(platform_dir.rglob("xparameters.h"))
            lines.append(f"  xparameters.h files ({len(xparams)}):")
            lines.extend(f"    - {normalize_path(str(path))}" for path in xparams[:10])
            if not xparams:
                lines.append("    (none found)")

    lines.append("")
    lines.append(
        "Guidance: Vitis 2019.2 GUI/workspace metadata can be fragile. Prefer XSCT/helper "
        "builds for automation; use the GUI mainly for manual debug. For source viewing, "
        "open files directly instead of forcing Vitis IDE project import."
    )
    return "\n".join(lines)


@mcp.tool()
async def inspect_vitis_bsp(
    workspace: str,
    app_name: str = "",
    platform_name: str = "",
    macro_filter: str = "",
    max_macros: int = 120,
    ctx: Context = None,
) -> str:
    """Inspect Vitis BSP xparameters.h macros relevant to addresses and interrupts."""
    ws = Path(workspace)
    if not ws.is_dir():
        return f"[ERROR] workspace 不存在: {workspace}"
    for value, name in ((app_name, "app_name"), (platform_name, "platform_name")):
        if value:
            try:
                validate_identifier(value, name)
            except ValueError as e:
                return f"[ERROR] {e}"

    search_roots = []
    if platform_name and (ws / platform_name).is_dir():
        search_roots.append(ws / platform_name)
    if app_name and (ws / app_name).is_dir():
        search_roots.append(ws / app_name)
    search_roots.append(ws)

    xparams: list[Path] = []
    seen: set[Path] = set()
    for root in search_roots:
        for path in root.rglob("xparameters.h"):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                xparams.append(path)

    filter_terms = [
        term.upper()
        for term in re.split(r"[,;\s]+", macro_filter.strip())
        if term.strip()
    ]

    lines = ["--- Vitis BSP inspection ---", f"workspace: {normalize_path(str(ws))}"]
    if filter_terms:
        lines.append(f"macro filter: {', '.join(filter_terms)}")
    lines.append(f"xparameters.h files ({len(xparams)}):")
    if not xparams:
        lines.append("  (none found)")
        return "\n".join(lines)

    macro_rows: dict[tuple[str, str], list[str]] = {}
    for path in xparams:
        lines.append(f"  - {normalize_path(str(path))}")
        for line in _tail_text(path, max_lines=20000):
            match = _BSP_MACRO_RE.match(line.strip())
            if not match:
                continue
            macro, value = match.groups()
            upper = macro.upper()
            if any(
                token in upper
                for token in (
                    "BASEADDR",
                    "HIGHADDR",
                    "DEVICE_ID",
                    "INT_ID",
                    "INTR",
                    "IRQ",
                    "SCUGIC",
                    "FABRIC",
                )
            ) and (not filter_terms or any(term in upper for term in filter_terms)):
                key = (macro, value.strip())
                macro_rows.setdefault(key, []).append(normalize_path(str(path)))

    lines.append("")
    lines.append(f"relevant macros ({len(macro_rows)}):")
    if not macro_rows:
        lines.append("  (none found)")
    else:
        rows = sorted(macro_rows.items())
        for (macro, value), paths in rows[: int(max_macros)]:
            suffix = f" ({paths[0]})"
            if len(paths) > 1:
                suffix = f" ({paths[0]}; also in {len(paths) - 1} more)"
            lines.append(f"  - {macro} = {value}{suffix}")
        if len(macro_rows) > int(max_macros):
            lines.append(f"  ... {len(macro_rows) - int(max_macros)} more")

    lines.append("")
    lines.append(
        "Guidance: use the macros actually present here. Do not assume generated names "
        "such as XPAR_FABRIC_<IP>_INTR exist; Zynq F2P interrupts often appear as "
        "XPS_FPGA*_INT_ID, and GIC commonly uses XPAR_SCUGIC_0_DEVICE_ID."
    )
    return "\n".join(lines)
