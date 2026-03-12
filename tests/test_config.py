"""config.py 单元测试。

测试路径检测逻辑（使用环境变量 mock，不依赖实际 Vivado 安装）。
"""

import os
import sys
from unittest.mock import patch

import pytest

from vivado_mcp.config import (
    _default_install_globs,
    find_vivado,
    get_vivado_version,
    normalize_path,
)


class TestNormalizePath:
    """路径标准化测试。"""

    def test_backslash_to_forward(self):
        assert normalize_path("C:\\Users\\test") == "C:/Users/test"

    def test_forward_slash_unchanged(self):
        assert normalize_path("/opt/vivado") == "/opt/vivado"

    def test_empty_string(self):
        assert normalize_path("") == ""


class TestDefaultInstallGlobs:
    """跨平台默认安装路径测试。"""

    def test_windows_globs(self):
        """Windows 平台返回 .bat 路径。"""
        with patch.object(sys, "platform", "win32"):
            globs = _default_install_globs()
            assert any("vivado.bat" in g for g in globs)
            assert any("D:/" in g for g in globs)

    def test_linux_globs(self):
        """Linux 平台返回无后缀路径。"""
        with patch.object(sys, "platform", "linux"):
            globs = _default_install_globs()
            assert any("/tools/Xilinx" in g for g in globs)
            assert any("/opt/Xilinx" in g for g in globs)
            assert all(".bat" not in g for g in globs)


class TestFindVivado:
    """Vivado 路径查找测试。"""

    def test_explicit_path(self, tmp_path):
        """显式传入的路径优先使用。"""
        fake = tmp_path / "vivado.bat"
        fake.write_text("fake")
        result = find_vivado(str(fake))
        assert "vivado.bat" in result

    def test_env_var(self, tmp_path):
        """VIVADO_PATH 环境变量被识别。"""
        fake = tmp_path / "vivado"
        fake.write_text("fake")
        with patch.dict(os.environ, {"VIVADO_PATH": str(fake)}):
            result = find_vivado()
            assert "vivado" in result

    def test_not_found_raises(self):
        """全部搜索失败时抛出 FileNotFoundError。"""
        with patch.dict(os.environ, {}, clear=True):
            with patch("vivado_mcp.config.shutil.which", return_value=None):
                with patch("vivado_mcp.config.glob.glob", return_value=[]):
                    with pytest.raises(FileNotFoundError, match="未找到"):
                        find_vivado()


class TestGetVivadoVersion:
    """版本号提取测试。"""

    def test_extract_version(self):
        assert get_vivado_version("D:/Xilinx/Vivado/2019.1/bin/vivado.bat") == "2019.1"

    def test_linux_path(self):
        assert get_vivado_version("/opt/Xilinx/Vivado/2024.1/bin/vivado") == "2024.1"

    def test_unknown_format(self):
        assert get_vivado_version("/usr/local/bin/vivado") == "unknown"
