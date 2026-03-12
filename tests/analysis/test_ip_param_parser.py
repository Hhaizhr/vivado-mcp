"""IP 参数解析器测试。"""

from __future__ import annotations

from vivado_mcp.analysis.ip_param_parser import parse_ip_params

# ====================================================================== #
#  模拟 Tcl 输出
# ====================================================================== #

_SAMPLE_OUTPUT = """\
VMCP_IP_INFO:xilinx.com:ip:xdma:4.1
VMCP_IP_PARAM:CONFIG.PCIE_BOARD_INTERFACE|pci_express_x4
VMCP_IP_PARAM:CONFIG.PF0_DEVICE_ID|9024
VMCP_IP_PARAM:CONFIG.PL_LINK_CAP_MAX_LINK_SPEED|5.0_GT/s
VMCP_IP_PARAM:CONFIG.PL_LINK_CAP_MAX_LINK_WIDTH|X4
VMCP_IP_PARAM:CONFIG.REF_CLK_FREQ|100_MHz
VMCP_IP_PARAM:CONFIG.PCIE_GT_DEVICE|GTX
VMCP_IP_PARAM:CONFIG.PCIE_LANE_REVERSAL|false
VMCP_IP_PARAM:CONFIG.GT_LOC_NUM|4
VMCP_IP_PARAM_DONE
"""

_ERROR_OUTPUT = """\
VMCP_IP_PARAM_ERROR:IP 'nonexistent_ip' not found
"""

_EMPTY_CONFIG_OUTPUT = """\
VMCP_IP_INFO:xilinx.com:ip:util_ds_buf:2.1
VMCP_IP_PARAM_DONE
"""


# ====================================================================== #
#  parse_ip_params 测试
# ====================================================================== #


class TestParseIpParams:
    """测试 IP 参数解析。"""

    def test_parse_normal_output(self):
        """正常输出解析为完整报告。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None
        assert report.ip_name == "xdma_0"
        assert report.vlnv == "xilinx.com:ip:xdma:4.1"
        assert report.total_count == 8

    def test_parse_extracts_params(self):
        """验证参数名称和值正确提取。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        param_map = {p.short_name: p.value for p in report.params}
        assert param_map["PF0_DEVICE_ID"] == "9024"
        assert param_map["PL_LINK_CAP_MAX_LINK_SPEED"] == "5.0_GT/s"
        assert param_map["PCIE_GT_DEVICE"] == "GTX"
        assert param_map["GT_LOC_NUM"] == "4"

    def test_short_name_strips_config_prefix(self):
        """short_name 正确去掉 CONFIG. 前缀。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None
        for p in report.params:
            assert not p.short_name.startswith("CONFIG.")
            assert p.name.startswith("CONFIG.")

    def test_returns_none_on_error(self):
        """IP 不存在时返回 None。"""
        result = parse_ip_params(_ERROR_OUTPUT, "nonexistent_ip")
        assert result is None

    def test_empty_config(self):
        """无 CONFIG.* 参数的 IP 返回空列表。"""
        report = parse_ip_params(_EMPTY_CONFIG_OUTPUT, "buf_0")
        assert report is not None
        assert report.total_count == 0
        assert report.params == []

    def test_handles_empty_value(self):
        """参数值为空字符串时正确处理。"""
        raw = (
            "VMCP_IP_INFO:xilinx.com:ip:test:1.0\n"
            "VMCP_IP_PARAM:CONFIG.EMPTY_PARAM|\n"
            "VMCP_IP_PARAM_DONE\n"
        )
        report = parse_ip_params(raw, "test_0")
        assert report is not None
        assert report.params[0].value == ""

    def test_handles_value_with_pipe(self):
        """参数值中包含竖线时，只在第一个竖线处分割。"""
        raw = (
            "VMCP_IP_INFO:xilinx.com:ip:test:1.0\n"
            "VMCP_IP_PARAM:CONFIG.COMPLEX|value|with|pipes\n"
            "VMCP_IP_PARAM_DONE\n"
        )
        report = parse_ip_params(raw, "test_0")
        assert report is not None
        # 正则 (.*)$ 会匹配第一个 | 后的所有内容
        assert report.params[0].value == "value|with|pipes"


# ====================================================================== #
#  IpParamReport.filter 测试
# ====================================================================== #


class TestIpParamReportFilter:
    """测试按关键词过滤。"""

    def test_filter_by_name(self):
        """按参数名过滤。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        gt_params = report.filter("gt")
        gt_names = {p.short_name for p in gt_params}
        assert "PCIE_GT_DEVICE" in gt_names
        assert "GT_LOC_NUM" in gt_names
        # 不含无关参数
        assert "REF_CLK_FREQ" not in gt_names

    def test_filter_by_value(self):
        """按参数值过滤。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        gtx_params = report.filter("GTX")
        assert len(gtx_params) >= 1
        assert any(p.short_name == "PCIE_GT_DEVICE" for p in gtx_params)

    def test_filter_case_insensitive(self):
        """过滤不区分大小写。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        assert len(report.filter("GT")) == len(report.filter("gt"))

    def test_filter_empty_keyword(self):
        """空关键词返回所有参数。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        assert len(report.filter("")) == report.total_count

    def test_filter_no_match(self):
        """无匹配结果返回空列表。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        assert report.filter("zzz_nonexistent") == []


# ====================================================================== #
#  IpParamReport.format 测试
# ====================================================================== #


class TestIpParamReportFormat:
    """测试格式化输出。"""

    def test_format_all(self):
        """格式化输出包含基本字段。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        text = report.format()
        assert "xdma_0" in text
        assert "xilinx.com:ip:xdma:4.1" in text
        assert "总参数数: 8" in text
        assert "PF0_DEVICE_ID" in text
        assert "9024" in text

    def test_format_with_filter(self):
        """带关键词格式化显示匹配数。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        text = report.format(keyword="lane")
        assert "过滤关键词" in text
        assert "lane" in text.lower()
        # 不应包含不匹配的参数
        assert "REF_CLK_FREQ" not in text

    def test_format_no_match(self):
        """无匹配时提示。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        text = report.format(keyword="zzz")
        assert "未找到" in text

    def test_format_empty_config(self):
        """空配置的格式化提示。"""
        report = parse_ip_params(_EMPTY_CONFIG_OUTPUT, "buf_0")
        assert report is not None

        text = report.format()
        assert "没有 CONFIG.* 参数" in text

    def test_to_dict(self):
        """验证 to_dict 输出结构。"""
        report = parse_ip_params(_SAMPLE_OUTPUT, "xdma_0")
        assert report is not None

        d = report.to_dict()
        assert d["ip_name"] == "xdma_0"
        assert d["vlnv"] == "xilinx.com:ip:xdma:4.1"
        assert d["total_count"] == 8
        assert len(d["params"]) == 8
        assert all("name" in p and "short_name" in p and "value" in p for p in d["params"])
