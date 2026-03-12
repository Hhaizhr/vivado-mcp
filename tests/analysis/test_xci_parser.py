"""XCI 解析器与对比算法测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vivado_mcp.analysis.xci_parser import (
    XciConfig,
    compare_xci_configs,
    format_xci_compare,
    parse_xci,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_SAMPLE_A = str(_FIXTURES / "sample_a.xci")
_SAMPLE_B = str(_FIXTURES / "sample_b.xci")


# ====================================================================== #
#  parse_xci 测试
# ====================================================================== #


class TestParseXci:
    """测试 XCI 文件解析。"""

    def test_parse_sample_a(self):
        """解析 sample_a.xci，验证基本字段。"""
        config = parse_xci(_SAMPLE_A)
        assert config.ip_name == "xdma"
        assert config.instance_name == "xdma_0"
        assert config.ip_version == "4.1"
        assert len(config.params) == 8

    def test_parse_extracts_params(self):
        """验证参数键值正确提取。"""
        config = parse_xci(_SAMPLE_A)
        assert config.params["PARAM_VALUE.PF0_DEVICE_ID"] == "9024"
        assert config.params["PARAM_VALUE.REF_CLK_FREQ"] == "100_MHz"
        assert config.params["PARAM_VALUE.PL_LINK_CAP_MAX_LINK_SPEED"] == "5.0_GT/s"

    def test_parse_sample_b(self):
        """解析 sample_b.xci，验证与 A 的差异参数。"""
        config = parse_xci(_SAMPLE_B)
        assert config.params["PARAM_VALUE.PF0_DEVICE_ID"] == "9038"
        assert config.params["PARAM_VALUE.PL_LINK_CAP_MAX_LINK_SPEED"] == "8.0_GT/s"
        assert config.params["PARAM_VALUE.PCIE_LANE_REVERSAL"] == "true"
        # B 独有的参数
        assert "PARAM_VALUE.ENABLE_MARK_DEBUG" in config.params

    def test_file_not_found(self):
        """文件不存在时抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            parse_xci("/nonexistent/path/file.xci")

    def test_wrong_extension(self, tmp_path):
        """非 .xci 扩展名时抛出 ValueError。"""
        bad_file = tmp_path / "test.xml"
        bad_file.write_text("<root/>")
        with pytest.raises(ValueError, match="扩展名"):
            parse_xci(str(bad_file))

    def test_invalid_xml(self, tmp_path):
        """无效 XML 内容时抛出 ValueError。"""
        bad_file = tmp_path / "bad.xci"
        bad_file.write_text("not xml content {{{")
        with pytest.raises(ValueError, match="XML 解析失败"):
            parse_xci(str(bad_file))

    def test_missing_component_instance(self, tmp_path):
        """缺少 componentInstance 元素时抛出 ValueError。"""
        minimal = tmp_path / "empty.xci"
        minimal.write_text(
            '<?xml version="1.0"?>'
            '<spirit:design xmlns:spirit='
            '"http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009">'
            '</spirit:design>'
        )
        with pytest.raises(ValueError, match="componentInstance"):
            parse_xci(str(minimal))

    def test_file_too_large(self, tmp_path):
        """文件超过大小限制时抛出 ValueError。"""
        big_file = tmp_path / "huge.xci"
        # 创建超过 10MB 的文件
        big_file.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        with pytest.raises(ValueError, match="文件过大"):
            parse_xci(str(big_file))


# ====================================================================== #
#  compare_xci_configs 测试
# ====================================================================== #


class TestCompareXciConfigs:
    """测试 XCI 对比算法。"""

    def test_compare_fixtures(self):
        """对比 sample_a 和 sample_b，验证差异检测。"""
        config_a = parse_xci(_SAMPLE_A)
        config_b = parse_xci(_SAMPLE_B)
        result = compare_xci_configs(config_a, config_b)

        assert result.ip_match is True  # 同一 IP 类型和版本
        assert result.diff_count > 0

        # 验证具体差异
        diff_names = {d.param_name for d in result.diffs}
        assert "PF0_DEVICE_ID" in diff_names      # 9024 → 9038
        assert "PL_LINK_CAP_MAX_LINK_SPEED" in diff_names  # 5.0 → 8.0
        assert "PCIE_LANE_REVERSAL" in diff_names  # false → true
        assert "AXISTEN_IF_WIDTH" in diff_names    # 64_bit → 128_bit

    def test_only_in_a_and_only_in_b(self):
        """检测仅存在于单侧的参数。"""
        config_a = parse_xci(_SAMPLE_A)
        config_b = parse_xci(_SAMPLE_B)
        result = compare_xci_configs(config_a, config_b)

        diff_map = {d.param_name: d for d in result.diffs}

        # A 有 PF0_SUBSYSTEM_ID，B 没有
        assert "PF0_SUBSYSTEM_ID" in diff_map
        assert diff_map["PF0_SUBSYSTEM_ID"].diff_type == "only_in_a"

        # B 有 ENABLE_MARK_DEBUG，A 没有
        assert "ENABLE_MARK_DEBUG" in diff_map
        assert diff_map["ENABLE_MARK_DEBUG"].diff_type == "only_in_b"

    def test_identical_params_counted(self):
        """验证相同参数计数正确。"""
        config_a = parse_xci(_SAMPLE_A)
        config_b = parse_xci(_SAMPLE_B)
        result = compare_xci_configs(config_a, config_b)

        # PCIE_BOARD_INTERFACE, PL_LINK_CAP_MAX_LINK_WIDTH, REF_CLK_FREQ 相同
        assert result.identical_count == 3

    def test_compare_same_file(self):
        """同一文件对比，差异为 0。"""
        config = parse_xci(_SAMPLE_A)
        result = compare_xci_configs(config, config)

        assert result.diff_count == 0
        assert result.identical_count == 8
        assert result.ip_match is True

    def test_ip_mismatch_detection(self):
        """IP 类型不同时 ip_match 为 False。"""
        config_a = XciConfig(
            file_path="a.xci", ip_name="xdma", instance_name="xdma_0",
            ip_version="4.1", params={},
        )
        config_b = XciConfig(
            file_path="b.xci", ip_name="pcie3", instance_name="pcie3_0",
            ip_version="4.1", params={},
        )
        result = compare_xci_configs(config_a, config_b)
        assert result.ip_match is False

    def test_to_dict(self):
        """验证 to_dict 输出结构。"""
        config_a = parse_xci(_SAMPLE_A)
        config_b = parse_xci(_SAMPLE_B)
        result = compare_xci_configs(config_a, config_b)
        d = result.to_dict()

        assert "file_a" in d
        assert "file_b" in d
        assert "ip_match" in d
        assert "identical_count" in d
        assert "diff_count" in d
        assert isinstance(d["diffs"], list)
        assert all("param" in diff and "type" in diff for diff in d["diffs"])


# ====================================================================== #
#  format_xci_compare 测试
# ====================================================================== #


class TestFormatXciCompare:
    """测试对比结果格式化。"""

    def test_format_diff_only(self):
        """默认模式只显示差异。"""
        config_a = parse_xci(_SAMPLE_A)
        config_b = parse_xci(_SAMPLE_B)
        result = compare_xci_configs(config_a, config_b)
        text = format_xci_compare(result, show_all=False)

        assert "XCI 配置对比" in text
        assert "差异参数" in text
        assert "PF0_DEVICE_ID" in text
        assert "9024" in text
        assert "9038" in text

    def test_format_show_all(self):
        """show_all=True 显示所有参数。"""
        config_a = parse_xci(_SAMPLE_A)
        config_b = parse_xci(_SAMPLE_B)
        result = compare_xci_configs(config_a, config_b)
        text = format_xci_compare(result, show_all=True)

        assert "所有参数" in text
        # 相同参数也出现
        assert "REF_CLK_FREQ" in text

    def test_format_identical(self):
        """完全相同时显示提示。"""
        config = parse_xci(_SAMPLE_A)
        result = compare_xci_configs(config, config)
        text = format_xci_compare(result)

        assert "完全相同" in text

    def test_format_only_in_a(self):
        """仅存在于 A 的参数标记为"缺失"。"""
        config_a = parse_xci(_SAMPLE_A)
        config_b = parse_xci(_SAMPLE_B)
        result = compare_xci_configs(config_a, config_b)
        text = format_xci_compare(result)

        assert "缺失" in text
