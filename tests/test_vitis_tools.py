import zipfile
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_locate_xsct_returns_path():
    from vivado_mcp.tools.vitis_tools import locate_xsct

    with patch(
        "vivado_mcp.tools.vitis_tools.find_xsct",
        return_value="D:/Xilinx/Vitis/2019.2/bin/xsct.bat",
    ):
        result = await locate_xsct()

    assert "xsct.bat" in result


@pytest.mark.asyncio
async def test_inspect_xsa_rejects_missing_file(tmp_path):
    from vivado_mcp.tools.vitis_tools import inspect_xsa

    result = await inspect_xsa(str(tmp_path / "missing.xsa"))

    assert "[ERROR]" in result
    assert "XSA 文件不存在" in result


@pytest.mark.asyncio
async def test_create_vitis_baremetal_app_runs_xsct(tmp_path):
    from vivado_mcp.tools.vitis_tools import create_vitis_baremetal_app

    xsa = tmp_path / "design.xsa"
    xsa.write_text("fake")
    workspace = tmp_path / "workspace"

    with patch(
        "vivado_mcp.tools.vitis_tools._run_xsct",
        return_value=(0, "VMCP_VITIS_APP:ok"),
    ) as run:
        result = await create_vitis_baremetal_app(
            xsa_path=str(xsa),
            workspace=str(workspace),
            platform_name="p",
            app_name="app",
        )

    assert "bare-metal app created" in result
    script = run.call_args.args[0]
    assert "platform create" in script
    assert "app create -name app" in script
    assert workspace.is_dir()


@pytest.mark.asyncio
async def test_build_vitis_app_runs_xsct(tmp_path):
    from vivado_mcp.tools.vitis_tools import build_vitis_app

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with patch(
        "vivado_mcp.tools.vitis_tools._run_xsct",
        return_value=(0, "VMCP_VITIS_BUILD_DONE:app"),
    ) as run:
        result = await build_vitis_app(str(workspace), "app")

    assert "Vitis app build result" in result
    assert "app build -name app" in run.call_args.args[0]


@pytest.mark.asyncio
async def test_build_vitis_app_rejects_missing_workspace(tmp_path):
    from vivado_mcp.tools.vitis_tools import build_vitis_app

    result = await build_vitis_app(str(tmp_path / "missing"), "app")

    assert "[ERROR]" in result
    assert "workspace 不存在" in result


@pytest.mark.asyncio
async def test_build_vitis_app_failure_suggests_diagnostics(tmp_path):
    from vivado_mcp.tools.vitis_tools import build_vitis_app

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with patch(
        "vivado_mcp.tools.vitis_tools._run_xsct",
        return_value=(1, "Invalid Workspace"),
    ):
        result = await build_vitis_app(str(workspace), "app")

    assert "Invalid Workspace" in result
    assert "diagnose_vitis_workspace" in result


def test_format_xsa_summary_includes_address_and_interrupt():
    from vivado_mcp.tools.vitis_tools import _format_xsa_summary

    raw = "\n".join(
        [
            "VMCP_XSA_PROCESSOR:ps7_cortexa9_0",
            "VMCP_XSA_CELL:axi_timer_0|xilinx.com:ip:axi_timer:2.0",
            "VMCP_XSA_MEM:axi_timer_0|0x42800000|0x4280FFFF|REGISTER|M_AXI_GP0|S_AXI",
            "VMCP_XSA_MEM:axi_timer_0|0x42800000|0x4280FFFF|REGISTER|M_AXI_GP0|S_AXI",
            "VMCP_XSA_INTR:axi_timer_0|interrupt|O|LEVEL_HIGH",
        ]
    )

    text = _format_xsa_summary(raw)

    assert "ps7_cortexa9_0" in text
    assert "axi_timer_0: xilinx.com:ip:axi_timer:2.0" in text
    assert "0x42800000..0x4280FFFF" in text
    assert text.count("0x42800000..0x4280FFFF") == 1
    assert "axi_timer_0/interrupt" in text


def test_format_xsa_archive_summary_reports_embedded_bitstream(tmp_path):
    from vivado_mcp.tools.vitis_tools import _format_xsa_archive_summary

    xsa = tmp_path / "design.xsa"
    with zipfile.ZipFile(xsa, "w") as archive:
        archive.writestr("hw/system.bit", "bit")
        archive.writestr("hw/system.hwh", "hwh")

    text = _format_xsa_archive_summary(str(xsa))

    assert "bitstream embedded: yes" in text
    assert "hw/system.bit" in text
    assert "hw/system.hwh" in text


def test_format_xsa_archive_summary_reports_missing_bitstream(tmp_path):
    from vivado_mcp.tools.vitis_tools import _format_xsa_archive_summary

    xsa = tmp_path / "design.xsa"
    with zipfile.ZipFile(xsa, "w") as archive:
        archive.writestr("hw/system.hwh", "hwh")

    text = _format_xsa_archive_summary(str(xsa))

    assert "bitstream embedded: no" in text
    assert "bit_files (0)" in text


@pytest.mark.asyncio
async def test_diagnose_vitis_workspace_reports_projects_logs_and_elf(tmp_path):
    from vivado_mcp.tools.vitis_tools import diagnose_vitis_workspace

    ws = tmp_path / "workspace"
    metadata = ws / ".metadata"
    app = ws / "app"
    platform = ws / "platform"
    (app / "src").mkdir(parents=True)
    (app / "Debug").mkdir()
    platform.mkdir(parents=True)
    metadata.mkdir(parents=True)
    (metadata / ".log").write_text("INFO\nERROR Invalid Workspace\n", encoding="utf-8")
    (app / ".project").write_text("<projectDescription />", encoding="utf-8")
    (app / ".cproject").write_text("<cproject />", encoding="utf-8")
    (app / "src" / "main.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
    (app / "Debug" / "makefile").write_text("all:\n", encoding="utf-8")
    (app / "Debug" / "app.elf").write_text("elf", encoding="utf-8")
    (platform / ".project").write_text("<projectDescription />", encoding="utf-8")
    (platform / "bsp" / "include").mkdir(parents=True)
    (platform / "bsp" / "include" / "xparameters.h").write_text("#define XPAR_X 1\n")

    result = await diagnose_vitis_workspace(str(ws), app_name="app", platform_name="platform")

    assert "metadata: present" in result
    assert "ERROR Invalid Workspace" in result
    assert "app [cproject, src, Debug/makefile, elf=1]" in result
    assert "app.elf" in result
    assert "xparameters.h files (1)" in result


@pytest.mark.asyncio
async def test_inspect_vitis_bsp_reports_relevant_macros(tmp_path):
    from vivado_mcp.tools.vitis_tools import inspect_vitis_bsp

    ws = tmp_path / "workspace"
    include = ws / "platform" / "bsp" / "include"
    include.mkdir(parents=True)
    (include / "xparameters.h").write_text(
        "\n".join(
            [
                "#define XPAR_AXI_TIMER_0_BASEADDR 0x42800000",
                "#define XPAR_SCUGIC_0_DEVICE_ID 0",
                "#define XPS_FPGA0_INT_ID 61",
                "#define IRRELEVANT 1",
            ]
        ),
        encoding="utf-8",
    )

    result = await inspect_vitis_bsp(str(ws), platform_name="platform")

    assert "XPAR_AXI_TIMER_0_BASEADDR = 0x42800000" in result
    assert "XPAR_SCUGIC_0_DEVICE_ID = 0" in result
    assert "XPS_FPGA0_INT_ID = 61" in result
    assert "IRRELEVANT" not in result


@pytest.mark.asyncio
async def test_inspect_vitis_bsp_filters_macros(tmp_path):
    from vivado_mcp.tools.vitis_tools import inspect_vitis_bsp

    ws = tmp_path / "workspace"
    include = ws / "platform" / "bsp" / "include"
    include.mkdir(parents=True)
    (include / "xparameters.h").write_text(
        "\n".join(
            [
                "#define XPAR_AXI_LITE_REG_CFG_0_BASEADDR 0x43C00000",
                "#define XPAR_DATA_COUNT_IRQ_AXI_0_BASEADDR 0x43C10000",
                "#define XPAR_SCUGIC_0_DEVICE_ID 0",
            ]
        ),
        encoding="utf-8",
    )

    result = await inspect_vitis_bsp(
        str(ws),
        platform_name="platform",
        macro_filter="DATA_COUNT SCUGIC",
    )

    assert "macro filter: DATA_COUNT, SCUGIC" in result
    assert "XPAR_DATA_COUNT_IRQ_AXI_0_BASEADDR = 0x43C10000" in result
    assert "XPAR_SCUGIC_0_DEVICE_ID = 0" in result
    assert "XPAR_AXI_LITE_REG_CFG_0_BASEADDR" not in result


@pytest.mark.asyncio
async def test_inspect_vitis_bsp_deduplicates_same_macro_value(tmp_path):
    from vivado_mcp.tools.vitis_tools import inspect_vitis_bsp

    ws = tmp_path / "workspace"
    include_a = ws / "platform" / "export" / "include"
    include_b = ws / "platform" / "bsp" / "include"
    include_a.mkdir(parents=True)
    include_b.mkdir(parents=True)
    content = "#define XPAR_DATA_COUNT_IRQ_AXI_0_BASEADDR 0x43C10000\n"
    (include_a / "xparameters.h").write_text(content, encoding="utf-8")
    (include_b / "xparameters.h").write_text(content, encoding="utf-8")

    result = await inspect_vitis_bsp(
        str(ws),
        platform_name="platform",
        macro_filter="DATA_COUNT",
    )

    assert "relevant macros (1)" in result
    assert result.count("XPAR_DATA_COUNT_IRQ_AXI_0_BASEADDR") == 1
    assert "also in 1 more" in result


@pytest.mark.asyncio
async def test_write_vitis_source_file(tmp_path):
    from vivado_mcp.tools.vitis_tools import write_vitis_source_file

    app = tmp_path / "workspace" / "app"
    app.mkdir(parents=True)

    result = await write_vitis_source_file(
        workspace=str(tmp_path / "workspace"),
        app_name="app",
        relative_path="src/main.c",
        content="int main(void) { return 0; }\n",
    )

    target = app / "src" / "main.c"
    assert target.read_text(encoding="utf-8") == "int main(void) { return 0; }\n"
    assert "Vitis source file written" in result


@pytest.mark.asyncio
async def test_write_vitis_source_rejects_path_escape(tmp_path):
    from vivado_mcp.tools.vitis_tools import write_vitis_source_file

    app = tmp_path / "workspace" / "app"
    app.mkdir(parents=True)

    result = await write_vitis_source_file(
        workspace=str(tmp_path / "workspace"),
        app_name="app",
        relative_path="../main.c",
        content="bad",
    )

    assert "[ERROR]" in result
    assert "相对路径" in result or "relative_path" in result


def test_run_xsct_wraps_bat_with_cmd(tmp_path):
    from vivado_mcp.tools.vitis_tools import _run_xsct

    completed = type(
        "Completed",
        (),
        {"returncode": 0, "stdout": "ok", "stderr": ""},
    )()

    with (
        patch(
            "vivado_mcp.tools.vitis_tools.find_xsct",
            return_value="D:/Xilinx/Vitis/2019.2/bin/xsct.bat",
        ),
        patch("vivado_mcp.tools.vitis_tools.subprocess.run", return_value=completed) as run,
    ):
        rc, output = _run_xsct("puts ok", timeout=1)

    assert rc == 0
    assert output == "ok"
    assert run.call_args.args[0][0:3] == [
        "cmd",
        "/c",
        "D:/Xilinx/Vitis/2019.2/bin/xsct.bat",
    ]
    env = run.call_args.kwargs["env"]
    assert env["PROCESSOR_ARCHITECTURE"] == "AMD64"
    assert env["PROCESSOR_ARCHITEW6432"] == "AMD64"
