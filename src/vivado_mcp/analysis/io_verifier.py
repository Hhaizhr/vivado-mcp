"""IO 引脚验证器：比对 XDC 约束与实际 report_io 结果，发现引脚不匹配。

核心用途：检测 PCIe GT 引脚交叉布线等严重错误。
GT 端口不匹配标记为 CRITICAL，GPIO 端口不匹配标记为 WARNING。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from vivado_mcp.analysis.io_parser import IoPort, IoReport
from vivado_mcp.analysis.xdc_parser import XdcConstraint


@dataclass(frozen=True)
class IoMismatch:
    """单个引脚不匹配记录。

    Attributes:
        port: 端口名称。
        expected_pin: XDC 约束中指定的引脚。
        actual_pin: report_io 中实际分配的引脚。
        expected_source: 约束来源 XDC 文件路径。
        actual_site: 实际 FPGA 站点。
        is_gt: 是否为 GT（高速收发器）端口。
        severity: 严重程度——"CRITICAL"（GT）或 "WARNING"（GPIO）。
    """

    port: str
    expected_pin: str
    actual_pin: str
    expected_source: str
    actual_site: str
    is_gt: bool
    severity: str


@dataclass
class IoVerification:
    """IO 验证结果汇总。

    Attributes:
        total_constrained: XDC 中约束的端口总数。
        matched: 引脚匹配正确的端口数。
        mismatched: 引脚不匹配的端口数。
        not_found: 在 XDC 中有约束但 report_io 中找不到的端口数。
        mismatches: 不匹配详情列表。
    """

    total_constrained: int = 0
    matched: int = 0
    mismatched: int = 0
    not_found: int = 0
    mismatches: list[IoMismatch] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为 JSON 可序列化的字典。"""
        return {
            "total_constrained": self.total_constrained,
            "matched": self.matched,
            "mismatched": self.mismatched,
            "not_found": self.not_found,
            "mismatches": [asdict(m) for m in self.mismatches],
        }


def verify_io_placement(
    xdc_constraints: list[XdcConstraint],
    io_report: IoReport,
) -> IoVerification:
    """比对 XDC 引脚约束与 report_io 实际结果。

    算法：
    1. 从 io_report 构建 port_name → IoPort 的索引
    2. 遍历每条 XDC 约束，查找对应端口
    3. 比较引脚是否匹配（不区分大小写）
    4. GT 端口不匹配标记为 CRITICAL，GPIO 标记为 WARNING

    Args:
        xdc_constraints: 从 XDC 文件解析出的约束列表。
        io_report: 从 report_io 解析出的 IO 报告。

    Returns:
        验证结果 IoVerification 实例。
    """
    # 构建端口名称 → IoPort 的快速查找索引
    port_index: dict[str, IoPort] = {p.port_name: p for p in io_report.ports}

    matched = 0
    mismatched = 0
    not_found = 0
    mismatches: list[IoMismatch] = []

    for constraint in xdc_constraints:
        port_info = port_index.get(constraint.port)

        if port_info is None:
            # XDC 中有约束，但 report_io 中找不到该端口
            not_found += 1
            continue

        # 引脚比较：不区分大小写
        if port_info.package_pin.upper() == constraint.pin.upper():
            matched += 1
        else:
            is_gt = port_info.io_type == "GT"
            severity = "CRITICAL" if is_gt else "WARNING"

            mismatches.append(
                IoMismatch(
                    port=constraint.port,
                    expected_pin=constraint.pin,
                    actual_pin=port_info.package_pin,
                    expected_source=constraint.source_file,
                    actual_site=port_info.site,
                    is_gt=is_gt,
                    severity=severity,
                )
            )
            mismatched += 1

    return IoVerification(
        total_constrained=len(xdc_constraints),
        matched=matched,
        mismatched=mismatched,
        not_found=not_found,
        mismatches=mismatches,
    )


def format_io_verification(v: IoVerification) -> str:
    """将 IO 验证结果格式化为人类可读的文本。

    输出包含：
    - 汇总统计（总数、匹配、不匹配、未找到）
    - CRITICAL 不匹配详情（GT 端口，高亮显示）
    - WARNING 不匹配详情（GPIO 端口）

    Args:
        v: IoVerification 验证结果。

    Returns:
        格式化的文本报告。
    """
    lines: list[str] = []

    # 汇总标题
    lines.append("=" * 60)
    lines.append("IO 引脚验证报告")
    lines.append("=" * 60)
    lines.append("")

    # 统计信息
    lines.append(f"约束端口总数:  {v.total_constrained}")
    lines.append(f"匹配正确:      {v.matched}")
    lines.append(f"引脚不匹配:    {v.mismatched}")
    lines.append(f"未找到端口:    {v.not_found}")
    lines.append("")

    if not v.mismatches:
        lines.append("所有约束端口的引脚分配均正确。")
        return "\n".join(lines)

    # 按严重程度分组输出
    critical = [m for m in v.mismatches if m.severity == "CRITICAL"]
    warnings = [m for m in v.mismatches if m.severity == "WARNING"]

    if critical:
        lines.append("!!! CRITICAL 不匹配（GT 高速收发器端口）!!!")
        lines.append("-" * 60)
        for m in critical:
            lines.append(f"  端口: {m.port}")
            lines.append(f"    XDC 约束引脚:   {m.expected_pin} (来源: {m.expected_source})")
            lines.append(f"    实际分配引脚:   {m.actual_pin}")
            lines.append(f"    FPGA 站点:      {m.actual_site}")
            lines.append("")

    if warnings:
        lines.append("WARNING 不匹配（GPIO 端口）")
        lines.append("-" * 60)
        for m in warnings:
            lines.append(f"  端口: {m.port}")
            lines.append(f"    XDC 约束引脚:   {m.expected_pin} (来源: {m.expected_source})")
            lines.append(f"    实际分配引脚:   {m.actual_pin}")
            lines.append(f"    FPGA 站点:      {m.actual_site}")
            lines.append("")

    return "\n".join(lines)
