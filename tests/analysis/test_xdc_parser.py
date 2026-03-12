"""xdc_parser.py 单元测试。

重点覆盖：
- 单行 / 多行约束解析
- 含方括号的端口名称（如 rxp[0]）
- VMCP_XDC_PIN_DONE 标记正确忽略
- 空输入容错
"""

import pytest

from vivado_mcp.analysis.xdc_parser import parse_xdc_constraints

# ====================================================================== #
#  基本解析功能
# ====================================================================== #


class TestParseBasic:
    """基本解析测试。"""

    def test_parse_single_constraint(self):
        """解析单行约束。"""
        raw = "VMCP_XDC_PIN:C:/project/board.xdc|10|AB8|sys_clk_p\n"
        result = parse_xdc_constraints(raw)

        assert len(result) == 1
        c = result[0]
        assert c.source_file == "C:/project/board.xdc"
        assert c.line_number == 10
        assert c.pin == "AB8"
        assert c.port == "sys_clk_p"

    def test_parse_multiple_constraints(self):
        """解析多行约束。"""
        raw = (
            "VMCP_XDC_PIN:C:/project/board.xdc|15|AA4|pcie_rxp[0]\n"
            "VMCP_XDC_PIN:C:/project/board.xdc|16|AB6|pcie_rxp[1]\n"
            "VMCP_XDC_PIN:C:/project/board.xdc|17|AC4|pcie_rxp[2]\n"
            "VMCP_XDC_PIN_DONE\n"
        )
        result = parse_xdc_constraints(raw)

        assert len(result) == 3
        assert result[0].pin == "AA4"
        assert result[1].pin == "AB6"
        assert result[2].pin == "AC4"


# ====================================================================== #
#  特殊端口名称
# ====================================================================== #


class TestSpecialPorts:
    """特殊端口名称处理测试。"""

    def test_port_with_brackets(self):
        """端口名称含方括号 [0] 应正确解析。"""
        raw = "VMCP_XDC_PIN:C:/proj/pins.xdc|5|M6|pcie_7x_mgt_rtl_0_rxp[0]\n"
        result = parse_xdc_constraints(raw)

        assert len(result) == 1
        assert result[0].port == "pcie_7x_mgt_rtl_0_rxp[0]"
        assert result[0].pin == "M6"

    def test_port_without_brackets(self):
        """普通端口名称（无方括号）应正确解析。"""
        raw = "VMCP_XDC_PIN:C:/proj/pins.xdc|21|AB8|sys_clk_p\n"
        result = parse_xdc_constraints(raw)

        assert len(result) == 1
        assert result[0].port == "sys_clk_p"


# ====================================================================== #
#  标记和边界处理
# ====================================================================== #


class TestMarkers:
    """标记行和边界情况测试。"""

    def test_done_marker_ignored(self):
        """VMCP_XDC_PIN_DONE 不应被解析为约束。"""
        raw = (
            "VMCP_XDC_PIN:C:/proj/pins.xdc|1|AA4|port_a\n"
            "VMCP_XDC_PIN_DONE\n"
        )
        result = parse_xdc_constraints(raw)

        assert len(result) == 1
        # 确认没有误将 DONE 行解析为约束
        assert all(c.port != "VMCP_XDC_PIN_DONE" for c in result)

    def test_empty_output(self):
        """空字符串应返回空列表。"""
        assert parse_xdc_constraints("") == []

    def test_whitespace_only(self):
        """仅含空白字符应返回空列表。"""
        assert parse_xdc_constraints("   \n\n  ") == []

    def test_non_matching_lines_ignored(self):
        """非 VMCP_XDC_PIN 行应被忽略。"""
        raw = (
            "INFO: Reading constraints...\n"
            "VMCP_XDC_PIN:C:/proj/pins.xdc|1|AA4|port_a\n"
            "Some other output\n"
            "VMCP_XDC_PIN_DONE\n"
        )
        result = parse_xdc_constraints(raw)

        assert len(result) == 1
        assert result[0].port == "port_a"


# ====================================================================== #
#  数据类型验证
# ====================================================================== #


class TestDataTypes:
    """字段数据类型测试。"""

    def test_line_number_is_int(self):
        """line_number 应为 int 类型。"""
        raw = "VMCP_XDC_PIN:C:/proj/pins.xdc|42|AB8|sys_clk_p\n"
        result = parse_xdc_constraints(raw)

        assert isinstance(result[0].line_number, int)
        assert result[0].line_number == 42

    def test_constraint_is_frozen(self):
        """XdcConstraint 应为不可变（frozen）。"""
        raw = "VMCP_XDC_PIN:C:/proj/pins.xdc|1|AA4|port_a\n"
        result = parse_xdc_constraints(raw)

        with pytest.raises(AttributeError):
            result[0].pin = "BB5"  # type: ignore[misc]
