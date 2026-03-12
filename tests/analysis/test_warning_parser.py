"""warning_parser.py 单元测试。

重点覆盖：
- parse_diag_counts 诊断计数解析
- parse_critical_warnings CRITICAL WARNING 逐行解析
- group_warnings 按 warning_id 聚合分组
- format_warning_report 中文报告格式化
- parse_pre_bitstream Bitstream 前置检查解析
- 边界情况：空输入、未知 ID、缺失字段
"""

from __future__ import annotations

import pathlib

from vivado_mcp.analysis.warning_parser import (
    CriticalWarning,
    WarningGroup,
    WarningReport,
    format_warning_report,
    group_warnings,
    parse_critical_warnings,
    parse_diag_counts,
    parse_pre_bitstream,
)

# ====================================================================== #
#  测试 fixture 辅助
# ====================================================================== #

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


def _make_vmcp_cw_output(log_path: pathlib.Path) -> str:
    """模拟 Tcl 脚本 EXTRACT_CRITICAL_WARNINGS 从 runme.log 产生的 VMCP_CW 输出。

    逐行扫描文件，遇到 CRITICAL WARNING 行就输出 ``VMCP_CW:行号|原文``，
    最后追加 ``VMCP_CW_DONE``。
    """
    lines = log_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for i, line in enumerate(lines, 1):
        if "CRITICAL WARNING:" in line:
            out.append(f"VMCP_CW:{i}|{line}")
    out.append("VMCP_CW_DONE")
    return "\n".join(out)


# ====================================================================== #
#  parse_diag_counts：诊断计数解析
# ====================================================================== #


class TestParseDiagCounts:
    """parse_diag_counts 诊断计数解析测试。"""

    def test_parse_diag_counts_normal(self):
        """正常输出解析为三元组。"""
        raw = "some info\nVMCP_DIAG:errors=0,critical_warnings=16,warnings=42\nmore info"
        assert parse_diag_counts(raw) == (0, 16, 42)

    def test_parse_diag_counts_not_found(self):
        """不包含 VMCP_DIAG 行时返回 (-1,-1,-1)。"""
        raw = "INFO: Vivado complete\nno diag line here"
        assert parse_diag_counts(raw) == (-1, -1, -1)

    def test_parse_diag_counts_log_missing(self):
        """runme.log 不存在时 Tcl 脚本输出 -1，解析结果也为 -1。"""
        raw = "VMCP_DIAG:errors=-1,critical_warnings=-1,warnings=-1"
        assert parse_diag_counts(raw) == (-1, -1, -1)

    def test_parse_diag_counts_empty(self):
        """空字符串不崩溃，返回 (-1,-1,-1)。"""
        assert parse_diag_counts("") == (-1, -1, -1)


# ====================================================================== #
#  parse_critical_warnings：CRITICAL WARNING 解析
# ====================================================================== #


class TestParseCriticalWarnings:
    """parse_critical_warnings CRITICAL WARNING 解析测试。"""

    def test_parse_single_cw(self):
        """解析单条 VMCP_CW 行，验证所有字段正确提取。"""
        raw = (
            "VMCP_CW:3|CRITICAL WARNING: [Vivado 12-1411] Cannot set LOC property "
            "of port pcie_7x_mgt_rtl_0_rxp[0] to package_pin AA4, because the "
            "MGTXRXP0_115 is occupied by port pcie_7x_mgt_rtl_0_rxn[7]. "
            "The conflicting port was constrained by [board_pins.xdc:15].\n"
            "VMCP_CW_DONE"
        )
        result = parse_critical_warnings(raw)
        assert len(result) == 1

        cw = result[0]
        assert cw.warning_id == "Vivado 12-1411"
        assert cw.line_number == 3
        assert cw.source_file == "board_pins.xdc"
        assert cw.port == "pcie_7x_mgt_rtl_0_rxp[0]"
        assert cw.pin == "AA4"
        assert "Cannot set LOC" in cw.message

    def test_parse_multiple_cw(self):
        """解析 fixture 文件中 16 条 CRITICAL WARNING。"""
        log_path = FIXTURES / "sample_runme_log.txt"
        raw = _make_vmcp_cw_output(log_path)
        result = parse_critical_warnings(raw)
        assert len(result) == 16

    def test_extract_warning_id(self):
        """验证 warning_id 从 [Vivado 12-1411] 正确提取。"""
        raw = (
            "VMCP_CW:10|CRITICAL WARNING: [Vivado 12-1411] Cannot set LOC "
            "of port test_port to package_pin B5. [test.xdc:1]."
        )
        result = parse_critical_warnings(raw)
        assert result[0].warning_id == "Vivado 12-1411"

    def test_extract_source_file(self):
        """验证源文件从消息末尾 [board_pins.xdc:15] 提取。"""
        raw = (
            "VMCP_CW:5|CRITICAL WARNING: [Vivado 12-1411] some text "
            "[board_pins.xdc:15]."
        )
        result = parse_critical_warnings(raw)
        assert result[0].source_file == "board_pins.xdc"

    def test_extract_port(self):
        """验证端口名从 'port xxx' 正确提取。"""
        raw = (
            "VMCP_CW:7|CRITICAL WARNING: [Vivado 12-1411] Cannot set LOC "
            "property of port my_port_rx[3] to package_pin C7. [test.xdc:2]."
        )
        result = parse_critical_warnings(raw)
        assert result[0].port == "my_port_rx[3]"

    def test_extract_pin(self):
        """验证引脚名从 'package_pin XX' 正确提取。"""
        raw = (
            "VMCP_CW:9|CRITICAL WARNING: [Vivado 12-1411] Cannot set LOC "
            "property of port test to package_pin AB6. [test.xdc:3]."
        )
        result = parse_critical_warnings(raw)
        assert result[0].pin == "AB6"

    def test_empty_input(self):
        """空字符串不崩溃，返回空列表。"""
        assert parse_critical_warnings("") == []

    def test_no_matching_lines(self):
        """不含 VMCP_CW 行时返回空列表。"""
        raw = "INFO: normal log line\nVMCP_CW_DONE"
        assert parse_critical_warnings(raw) == []

    def test_warning_without_source_file(self):
        """消息中不含源文件引用时 source_file 为空。"""
        raw = "VMCP_CW:1|CRITICAL WARNING: [Vivado 12-4739] Clock constraint issue."
        result = parse_critical_warnings(raw)
        assert result[0].source_file == ""

    def test_warning_without_port_or_pin(self):
        """消息中不含 port/pin 时对应字段为空。"""
        raw = "VMCP_CW:1|CRITICAL WARNING: [Timing 38-282] Timing violation detected."
        result = parse_critical_warnings(raw)
        assert result[0].port == ""
        assert result[0].pin == ""


# ====================================================================== #
#  group_warnings：聚合分组
# ====================================================================== #


class TestGroupWarnings:
    """group_warnings 分组测试。"""

    def test_group_same_id(self):
        """相同 warning_id 的 16 条警告聚合为 1 组。"""
        log_path = FIXTURES / "sample_runme_log.txt"
        raw = _make_vmcp_cw_output(log_path)
        cw_list = parse_critical_warnings(raw)
        groups = group_warnings(cw_list)
        # fixture 文件中所有 CW 都是 Vivado 12-1411
        assert len(groups) == 1
        assert groups[0].count == 16
        assert groups[0].warning_id == "Vivado 12-1411"

    def test_group_mixed_ids(self):
        """不同 warning_id 分为不同组。"""
        cw_list = [
            CriticalWarning("Vivado 12-1411", "msg A", 1, "a.xdc", "portA", "A1"),
            CriticalWarning("Vivado 12-1411", "msg B", 2, "a.xdc", "portB", "A2"),
            CriticalWarning("Timing 38-282", "msg C", 5, "", "", ""),
            CriticalWarning("DRC RTSTAT-1", "msg D", 8, "", "", ""),
            CriticalWarning("Timing 38-282", "msg E", 10, "", "", ""),
        ]
        groups = group_warnings(cw_list)
        assert len(groups) == 3

        # 验证各组计数
        by_id = {g.warning_id: g for g in groups}
        assert by_id["Vivado 12-1411"].count == 2
        assert by_id["Timing 38-282"].count == 2
        assert by_id["DRC RTSTAT-1"].count == 1

    def test_known_category(self):
        """已知 warning_id 映射到正确的分类标签。"""
        cw_list = [
            CriticalWarning("Vivado 12-1411", "msg", 1, "a.xdc", "p", "A1"),
        ]
        groups = group_warnings(cw_list)
        assert groups[0].category == "GT_PIN_CONFLICT"
        assert "GT端口" in groups[0].suggestion

    def test_unknown_category(self):
        """未知 warning_id 分类为 UNKNOWN，使用通用建议。"""
        cw_list = [
            CriticalWarning("Vivado 99-9999", "unknown msg", 42, "", "", ""),
        ]
        groups = group_warnings(cw_list)
        assert groups[0].category == "UNKNOWN"
        assert "未知" in groups[0].suggestion

    def test_group_affected_ports_dedup(self):
        """受影响端口去重，保持出现顺序。"""
        cw_list = [
            CriticalWarning("Vivado 12-1411", "msg1", 1, "a.xdc", "portA", "A1"),
            CriticalWarning("Vivado 12-1411", "msg2", 2, "a.xdc", "portA", "A2"),
            CriticalWarning("Vivado 12-1411", "msg3", 3, "a.xdc", "portB", "A3"),
        ]
        groups = group_warnings(cw_list)
        assert groups[0].affected_ports == ["portA", "portB"]

    def test_group_source_files_dedup(self):
        """源文件去重，保持出现顺序。"""
        cw_list = [
            CriticalWarning("Vivado 12-1411", "msg1", 1, "a.xdc", "p1", "A1"),
            CriticalWarning("Vivado 12-1411", "msg2", 2, "b.xdc", "p2", "A2"),
            CriticalWarning("Vivado 12-1411", "msg3", 3, "a.xdc", "p3", "A3"),
        ]
        groups = group_warnings(cw_list)
        assert groups[0].source_files == ["a.xdc", "b.xdc"]

    def test_group_empty_list(self):
        """空列表输入返回空分组列表。"""
        assert group_warnings([]) == []


# ====================================================================== #
#  format_warning_report：报告格式化
# ====================================================================== #


class TestFormatWarningReport:
    """format_warning_report 报告格式化测试。"""

    def test_format_with_cw(self):
        """存在 CRITICAL WARNING 时首行包含 '!! 发现'。"""
        groups = [
            WarningGroup(
                warning_id="Vivado 12-1411",
                category="GT_PIN_CONFLICT",
                count=16,
                first_line=3,
                message_template="Cannot set LOC ...",
                affected_ports=["portA", "portB"],
                source_files=["board_pins.xdc"],
                suggestion="GT端口PACKAGE_PIN约束与IP内部LOC冲突。",
            ),
        ]
        report = WarningReport(errors=0, critical_warnings=16, warnings=42, groups=groups)
        text = format_warning_report(report)

        assert text.startswith("!! 发现 16 条 CRITICAL WARNING !!")
        assert "GT_PIN_CONFLICT" in text
        assert "portA" in text
        assert "board_pins.xdc" in text
        assert "建议:" in text

    def test_format_clean(self):
        """无 CRITICAL WARNING 时不出现警告头。"""
        report = WarningReport(errors=0, critical_warnings=0, warnings=5, groups=[])
        text = format_warning_report(report)

        assert "!! 发现" not in text
        assert "critical_warnings=0" in text

    def test_format_multiple_groups(self):
        """多个分组都出现在报告中。"""
        groups = [
            WarningGroup(
                warning_id="Vivado 12-1411",
                category="GT_PIN_CONFLICT",
                count=8,
                first_line=3,
                message_template="msg A",
                suggestion="建议A",
            ),
            WarningGroup(
                warning_id="Timing 38-282",
                category="TIMING_VIOLATION",
                count=2,
                first_line=20,
                message_template="msg B",
                suggestion="建议B",
            ),
        ]
        report = WarningReport(errors=0, critical_warnings=10, warnings=0, groups=groups)
        text = format_warning_report(report)

        assert "GT_PIN_CONFLICT" in text
        assert "TIMING_VIOLATION" in text
        assert "建议A" in text
        assert "建议B" in text


# ====================================================================== #
#  parse_pre_bitstream：Bitstream 前置检查
# ====================================================================== #


class TestParsePreBitstream:
    """parse_pre_bitstream Bitstream 前置检查解析测试。"""

    def test_parse_pre_bitstream(self):
        """正常 VMCP_PRE_BIT 输出解析正确。"""
        raw = (
            "VMCP_PRE_BIT:status=route_design Complete,critical_warnings=3\n"
            "VMCP_PRE_BIT_CW:CRITICAL WARNING: [Vivado 12-1411] pin conflict 1\n"
            "VMCP_PRE_BIT_CW:CRITICAL WARNING: [Vivado 12-1411] pin conflict 2\n"
            "VMCP_PRE_BIT_CW:CRITICAL WARNING: [Timing 38-282] timing issue\n"
            "VMCP_PRE_BIT_DONE"
        )
        status, cw_count, samples = parse_pre_bitstream(raw)
        assert status == "route_design Complete"
        assert cw_count == 3
        assert len(samples) == 3
        assert "pin conflict 1" in samples[0]
        assert "timing issue" in samples[2]

    def test_parse_pre_bitstream_no_cw(self):
        """无 CRITICAL WARNING 时样本列表为空。"""
        raw = (
            "VMCP_PRE_BIT:status=route_design Complete,critical_warnings=0\n"
            "VMCP_PRE_BIT_DONE"
        )
        status, cw_count, samples = parse_pre_bitstream(raw)
        assert status == "route_design Complete"
        assert cw_count == 0
        assert samples == []

    def test_parse_pre_bitstream_empty(self):
        """空字符串不崩溃，返回默认值。"""
        status, cw_count, samples = parse_pre_bitstream("")
        assert status == "UNKNOWN"
        assert cw_count == -1
        assert samples == []


# ====================================================================== #
#  集成：从 fixture 文件端到端解析
# ====================================================================== #


class TestEndToEnd:
    """端到端集成测试：fixture → parse → group → format。"""

    def test_fixture_full_pipeline(self):
        """从 sample_runme_log.txt 完整走一遍解析流程。"""
        log_path = FIXTURES / "sample_runme_log.txt"
        raw_cw = _make_vmcp_cw_output(log_path)
        raw_diag = "VMCP_DIAG:errors=0,critical_warnings=16,warnings=42"

        # 解析计数
        errors, cw_count, w_count = parse_diag_counts(raw_diag)
        assert errors == 0
        assert cw_count == 16

        # 解析 CW 详情
        cw_list = parse_critical_warnings(raw_cw)
        assert len(cw_list) == 16

        # 分组
        groups = group_warnings(cw_list)
        assert len(groups) == 1
        assert groups[0].category == "GT_PIN_CONFLICT"

        # 格式化
        report = WarningReport(
            errors=errors,
            critical_warnings=cw_count,
            warnings=w_count,
            groups=groups,
        )
        text = format_warning_report(report)
        assert "!! 发现 16 条 CRITICAL WARNING !!" in text
        assert "board_pins.xdc" in text
