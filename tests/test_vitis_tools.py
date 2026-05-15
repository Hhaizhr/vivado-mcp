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


def test_format_xsa_summary_includes_address_and_interrupt():
    from vivado_mcp.tools.vitis_tools import _format_xsa_summary

    raw = "\n".join(
        [
            "VMCP_XSA_PROCESSOR:ps7_cortexa9_0",
            "VMCP_XSA_CELL:axi_timer_0|xilinx.com:ip:axi_timer:2.0",
            "VMCP_XSA_MEM:axi_timer_0|0x42800000|0x4280FFFF|REGISTER|M_AXI_GP0|S_AXI",
            "VMCP_XSA_INTR:axi_timer_0|interrupt|O|LEVEL_HIGH",
        ]
    )

    text = _format_xsa_summary(raw)

    assert "ps7_cortexa9_0" in text
    assert "axi_timer_0: xilinx.com:ip:axi_timer:2.0" in text
    assert "0x42800000..0x4280FFFF" in text
    assert "axi_timer_0/interrupt" in text


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
