"""io_verifier.py 单元测试。

重点覆盖：
- 全部匹配场景
- GT 不匹配 → CRITICAL 严重级别
- GPIO 不匹配 → WARNING 严重级别
- XDC 中有约束但 report_io 中不存在的端口
- 混合场景（部分匹配、部分不匹配）
- 引脚比较不区分大小写
- 空 XDC 输入
- format_io_verification 输出可读性
"""

from vivado_mcp.analysis.io_parser import IoPort, IoReport
from vivado_mcp.analysis.io_verifier import (
    IoMismatch,
    IoVerification,
    format_io_verification,
    verify_io_placement,
)
from vivado_mcp.analysis.xdc_parser import XdcConstraint

# ====================================================================== #
#  测试辅助工厂函数
# ====================================================================== #


def _make_gt_port(name: str, pin: str, site: str = "MGTXRXP0_116") -> IoPort:
    """创建一个 GT 类型的测试端口。"""
    return IoPort(
        port_name=name,
        package_pin=pin,
        site=site,
        direction="INPUT",
        io_standard="",
        bank=116,
        fixed=True,
        io_type="GT",
    )


def _make_gpio_port(
    name: str, pin: str, site: str = "IOB_X0Y158", io_std: str = "LVCMOS33"
) -> IoPort:
    """创建一个 GPIO 类型的测试端口。"""
    return IoPort(
        port_name=name,
        package_pin=pin,
        site=site,
        direction="INPUT",
        io_standard=io_std,
        bank=33,
        fixed=True,
        io_type="GPIO",
    )


def _make_constraint(port: str, pin: str, source: str = "C:/proj/pins.xdc") -> XdcConstraint:
    """创建一条测试 XDC 约束。"""
    return XdcConstraint(
        source_file=source,
        line_number=1,
        pin=pin,
        port=port,
    )


def _make_report(ports: list[IoPort]) -> IoReport:
    """从端口列表构建 IoReport。"""
    gt_count = sum(1 for p in ports if p.io_type == "GT")
    gpio_count = sum(1 for p in ports if p.io_type == "GPIO")
    unplaced = sum(1 for p in ports if not p.package_pin)
    return IoReport(
        ports=ports,
        total_ports=len(ports),
        gt_ports=gt_count,
        gpio_ports=gpio_count,
        unplaced_ports=unplaced,
    )


# ====================================================================== #
#  全部匹配
# ====================================================================== #


class TestAllMatched:
    """所有引脚匹配正确的场景。"""

    def test_all_matched(self):
        """XDC 约束与 report_io 完全一致时，mismatched=0。"""
        ports = [
            _make_gt_port("rxp[0]", "M6"),
            _make_gpio_port("sys_clk_p", "AB8"),
        ]
        constraints = [
            _make_constraint("rxp[0]", "M6"),
            _make_constraint("sys_clk_p", "AB8"),
        ]
        report = _make_report(ports)
        result = verify_io_placement(constraints, report)

        assert result.total_constrained == 2
        assert result.matched == 2
        assert result.mismatched == 0
        assert result.not_found == 0
        assert len(result.mismatches) == 0


# ====================================================================== #
#  GT 不匹配 → CRITICAL
# ====================================================================== #


class TestGtMismatch:
    """GT 端口不匹配应标记为 CRITICAL。"""

    def test_pin_mismatch_gt(self):
        """GT 端口引脚不匹配时，severity 应为 CRITICAL。"""
        ports = [_make_gt_port("rxp[0]", "M6", site="MGTXRXP3_116")]
        constraints = [_make_constraint("rxp[0]", "AA4")]  # XDC 说 AA4，实际 M6
        report = _make_report(ports)

        result = verify_io_placement(constraints, report)

        assert result.mismatched == 1
        assert len(result.mismatches) == 1

        mismatch = result.mismatches[0]
        assert mismatch.port == "rxp[0]"
        assert mismatch.expected_pin == "AA4"
        assert mismatch.actual_pin == "M6"
        assert mismatch.is_gt is True
        assert mismatch.severity == "CRITICAL"


# ====================================================================== #
#  GPIO 不匹配 → WARNING
# ====================================================================== #


class TestGpioMismatch:
    """GPIO 端口不匹配应标记为 WARNING。"""

    def test_pin_mismatch_gpio(self):
        """GPIO 端口引脚不匹配时，severity 应为 WARNING。"""
        ports = [_make_gpio_port("led[0]", "AA2")]
        constraints = [_make_constraint("led[0]", "BB3")]  # XDC 说 BB3，实际 AA2
        report = _make_report(ports)

        result = verify_io_placement(constraints, report)

        assert result.mismatched == 1
        mismatch = result.mismatches[0]
        assert mismatch.is_gt is False
        assert mismatch.severity == "WARNING"


# ====================================================================== #
#  端口未找到
# ====================================================================== #


class TestPortNotFound:
    """XDC 中有约束但 report_io 中不存在的端口。"""

    def test_port_not_found(self):
        """约束的端口在 report_io 中不存在时，应计入 not_found。"""
        ports = [_make_gpio_port("sys_clk_p", "AB8")]
        constraints = [
            _make_constraint("sys_clk_p", "AB8"),
            _make_constraint("nonexistent_port", "ZZ9"),
        ]
        report = _make_report(ports)

        result = verify_io_placement(constraints, report)

        assert result.total_constrained == 2
        assert result.matched == 1
        assert result.not_found == 1
        assert result.mismatched == 0


# ====================================================================== #
#  混合场景
# ====================================================================== #


class TestMixedResults:
    """部分匹配、部分不匹配的混合场景。"""

    def test_mixed_results(self):
        """混合场景：1 匹配 + 1 GT 不匹配 + 1 未找到。"""
        ports = [
            _make_gt_port("rxp[0]", "M6"),
            _make_gpio_port("sys_clk_p", "AB8"),
        ]
        constraints = [
            _make_constraint("sys_clk_p", "AB8"),   # 匹配
            _make_constraint("rxp[0]", "AA4"),       # GT 不匹配
            _make_constraint("missing_port", "ZZ1"), # 未找到
        ]
        report = _make_report(ports)

        result = verify_io_placement(constraints, report)

        assert result.total_constrained == 3
        assert result.matched == 1
        assert result.mismatched == 1
        assert result.not_found == 1
        assert result.mismatches[0].severity == "CRITICAL"


# ====================================================================== #
#  大小写不敏感比较
# ====================================================================== #


class TestCaseInsensitive:
    """引脚比较应不区分大小写。"""

    def test_case_insensitive(self):
        """引脚 'ab8' 与 'AB8' 应视为匹配。"""
        ports = [_make_gpio_port("sys_clk_p", "AB8")]
        constraints = [_make_constraint("sys_clk_p", "ab8")]  # 小写
        report = _make_report(ports)

        result = verify_io_placement(constraints, report)

        assert result.matched == 1
        assert result.mismatched == 0

    def test_mixed_case(self):
        """引脚 'Ab8' 与 'aB8' 应视为匹配。"""
        ports = [_make_gpio_port("clk", "Ab8")]
        constraints = [_make_constraint("clk", "aB8")]
        report = _make_report(ports)

        result = verify_io_placement(constraints, report)

        assert result.matched == 1
        assert result.mismatched == 0


# ====================================================================== #
#  空 XDC 输入
# ====================================================================== #


class TestEmptyXdc:
    """空约束列表的处理。"""

    def test_empty_xdc(self):
        """无约束时，所有计数应为 0。"""
        ports = [_make_gpio_port("sys_clk_p", "AB8")]
        report = _make_report(ports)

        result = verify_io_placement([], report)

        assert result.total_constrained == 0
        assert result.matched == 0
        assert result.mismatched == 0
        assert result.not_found == 0
        assert len(result.mismatches) == 0


# ====================================================================== #
#  格式化输出
# ====================================================================== #


class TestFormatOutput:
    """format_io_verification 输出测试。"""

    def test_format_output(self):
        """格式化结果应包含关键信息。"""
        ports = [
            _make_gt_port("rxp[0]", "M6"),
            _make_gpio_port("led[0]", "AA2"),
        ]
        constraints = [
            _make_constraint("rxp[0]", "AA4"),   # GT 不匹配
            _make_constraint("led[0]", "BB3"),   # GPIO 不匹配
        ]
        report = _make_report(ports)
        verification = verify_io_placement(constraints, report)
        output = format_io_verification(verification)

        # 验证输出包含关键元素
        assert "IO 引脚验证报告" in output
        assert "CRITICAL" in output
        assert "WARNING" in output
        assert "rxp[0]" in output
        assert "led[0]" in output
        assert "AA4" in output    # XDC 约束引脚
        assert "M6" in output     # 实际引脚
        assert "BB3" in output

    def test_format_all_matched(self):
        """全部匹配时，输出应包含正确提示。"""
        verification = IoVerification(
            total_constrained=5,
            matched=5,
            mismatched=0,
            not_found=0,
            mismatches=[],
        )
        output = format_io_verification(verification)

        assert "所有约束端口的引脚分配均正确" in output
        assert "CRITICAL" not in output

    def test_to_dict_serializable(self):
        """IoVerification.to_dict() 结果应可 JSON 序列化。"""
        verification = IoVerification(
            total_constrained=1,
            matched=0,
            mismatched=1,
            not_found=0,
            mismatches=[
                IoMismatch(
                    port="rxp[0]",
                    expected_pin="AA4",
                    actual_pin="M6",
                    expected_source="pins.xdc",
                    actual_site="MGTXRXP3_116",
                    is_gt=True,
                    severity="CRITICAL",
                )
            ],
        )
        import json

        d = verification.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        assert isinstance(json_str, str)
        assert "CRITICAL" in json_str
