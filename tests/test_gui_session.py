import sys


def test_vivado_gui_command_forces_64_bit_env_on_windows_batch(monkeypatch):
    from vivado_mcp.vivado.gui_session import _vivado_gui_command

    monkeypatch.setattr(sys, "platform", "win32")

    cmd, env = _vivado_gui_command(
        r"D:\Xilinx\Vivado\2019.2\bin\vivado.bat",
        r"C:\Temp\vmcp.tcl",
    )

    assert cmd[:2] == ["cmd", "/c"]
    assert cmd[2] == r"D:\Xilinx\Vivado\2019.2\bin\vivado.bat"
    assert "-source" in cmd
    assert env["PROCESSOR_ARCHITECTURE"] == "AMD64"
    assert env["PROCESSOR_ARCHITEW6432"] == "AMD64"
