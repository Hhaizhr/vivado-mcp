"""Vivado CRITICAL WARNING 解析器。

纯 Python 模块，不依赖 Vivado 进程。解析 Tcl 脚本产生的 VMCP_ 前缀结构化输出，
将 CRITICAL WARNING 分类、聚合，并生成中文诊断报告。

输入来源（参见 tcl_scripts.py）:
- COUNT_WARNINGS  → ``VMCP_DIAG:errors=E,critical_warnings=CW,warnings=W``
- EXTRACT_CRITICAL_WARNINGS → ``VMCP_CW:行号|原始消息``
- CHECK_PRE_BITSTREAM → ``VMCP_PRE_BIT:status=S,critical_warnings=N``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ====================================================================== #
#  数据结构
# ====================================================================== #


@dataclass(frozen=True)
class CriticalWarning:
    """单条 CRITICAL WARNING 的结构化表示。"""

    warning_id: str  # 例如 "Vivado 12-1411"
    message: str  # 完整消息文本
    line_number: int  # runme.log 中的行号
    source_file: str  # 从消息末尾 [file.xdc:line] 提取的文件名
    port: str  # 从消息提取的端口名（如有）
    pin: str  # 从消息提取的引脚名（如有）


@dataclass
class WarningGroup:
    """按 warning_id 聚合后的分组。"""

    warning_id: str
    category: str  # "GT_PIN_CONFLICT" 等分类标签
    count: int
    first_line: int  # 该分组在 runme.log 中首次出现的行号
    message_template: str  # 代表性消息
    affected_ports: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    suggestion: str = ""  # 中文修复建议


@dataclass
class WarningReport:
    """整合诊断计数与分组后的完整报告。"""

    errors: int
    critical_warnings: int
    warnings: int
    groups: list[WarningGroup] = field(default_factory=list)


# ====================================================================== #
#  已知分类表——内置中文修复建议
# ====================================================================== #

_KNOWN_CATEGORIES: dict[str, tuple[str, str]] = {
    "Vivado 12-1411": (
        "GT_PIN_CONFLICT",
        "GT端口PACKAGE_PIN约束与IP内部LOC冲突。\n"
        "  原因: IP 内部 GT Location 约束已锁定通道映射，XDC 中的 PACKAGE_PIN 与其冲突。\n"
        "  修复方法:\n"
        "  1. [推荐] 删除 XDC 中 GT 端口的 PACKAGE_PIN 约束，让 IP 自动分配\n"
        "  2. 修正 XDC 引脚顺序使其与 IP 内部 Lane 映射一致\n"
        "  注意: disable_gt_loc 仅对 UltraScale+(GT Wizard)有效，"
        "7-Series(pcie_7x)的 LOC 由 .ttcl 模板无条件生成，该参数无效。\n"
        "  诊断: 运行 inspect_ip_params(filter_keyword='gt') 确认 IP 支持哪些 GT 参数",
    ),
    "Vivado 12-2285": (
        "GT_LOC_CONFLICT",
        "Cell级LOC与已占用BEL冲突。检查是否有重复GT LOC约束。",
    ),
    "Vivado 12-4739": (
        "TIMING_CONSTRAINT",
        "时钟约束问题。检查create_clock定义。",
    ),
    "DRC RTSTAT-1": (
        "UNROUTED_NET",
        "存在未布线网络。检查管脚约束是否完整。",
    ),
    "Timing 38-282": (
        "TIMING_VIOLATION",
        "时序违例。运行 report_timing_summary 查看详情。",
    ),
    "Vivado 12-180": (
        "CLOCK_NOT_FOUND",
        "时钟约束目标不存在。检查create_clock的端口名是否与RTL一致。",
    ),
    "Synth 8-3295": (
        "UNCONNECTED_PORT",
        "模块端口未连接。检查RTL实例化的端口连接。",
    ),
    "DRC BIVC-1": (
        "IO_STANDARD_MISMATCH",
        "Bank内IOSTANDARD不一致。检查同Bank引脚的电平标准。",
    ),
    "Vivado 12-1790": (
        "MISSING_PIN_CONSTRAINT",
        "端口缺少 PACKAGE_PIN 或 LOC 约束。检查 XDC 文件是否遗漏了该端口的引脚分配。",
    ),
    "Vivado 12-4385": (
        "CLOCK_PLACEMENT",
        "时钟输入未放置在专用时钟引脚（MRCC/SRCC）。\n"
        "  修复: 将时钟信号分配到 MRCC 或 SRCC 类型的引脚。",
    ),
    "DRC NSTD-1": (
        "UNSPECIFIED_IOSTANDARD",
        "端口未指定 IOSTANDARD，将使用默认值。\n"
        "  修复: 在 XDC 中为所有端口添加 set_property IOSTANDARD 约束。",
    ),
    "DRC UCIO-1": (
        "UNCONSTRAINED_IO",
        "端口未约束到物理引脚。\n"
        "  修复: 在 XDC 中为该端口添加 PACKAGE_PIN 约束，或确认是否为未使用端口。",
    ),
}

# ====================================================================== #
#  编译正则——模块加载时一次编译
# ====================================================================== #

# 匹配 VMCP_DIAG 行
_RE_DIAG = re.compile(
    r"VMCP_DIAG:errors=(-?\d+),critical_warnings=(-?\d+),warnings=(-?\d+)"
)

# 匹配 VMCP_CW 行：行号|消息
_RE_CW_LINE = re.compile(r"VMCP_CW:(\d+)\|(.+)")

# 从消息中提取 warning ID，如 [Vivado 12-1411]、[DRC RTSTAT-1]、[Timing 38-282]
_RE_WARNING_ID = re.compile(r"\[(\w+[\s\-]\d+[\-\d]*)\]")

# 从消息末尾提取源文件引用，如 [board_pins.xdc:15]
_RE_SOURCE_FILE = re.compile(r"\[(\S+?\.\w+):(\d+)\]")

# 提取端口名：port xxxx
_RE_PORT = re.compile(r"port\s+(\S+)", re.IGNORECASE)

# 提取引脚名：package_pin XXXX
_RE_PIN = re.compile(r"package_pin\s+(\w+)", re.IGNORECASE)

# 匹配 VMCP_PRE_BIT 状态行
_RE_PRE_BIT = re.compile(r"VMCP_PRE_BIT:status=([^,]+),critical_warnings=(-?\d+)")

# 匹配 VMCP_PRE_BIT_CW 样本行
_RE_PRE_BIT_CW = re.compile(r"VMCP_PRE_BIT_CW:(.+)")


# ====================================================================== #
#  解析函数
# ====================================================================== #


def parse_diag_counts(raw: str) -> tuple[int, int, int]:
    """解析 COUNT_WARNINGS 脚本输出中的 VMCP_DIAG 行。

    返回 ``(errors, critical_warnings, warnings)`` 三元组。
    若未找到匹配行，返回 ``(-1, -1, -1)``。
    """
    m = _RE_DIAG.search(raw)
    if m is None:
        return (-1, -1, -1)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def parse_critical_warnings(raw: str) -> list[CriticalWarning]:
    """解析 EXTRACT_CRITICAL_WARNINGS 脚本输出。

    逐行匹配 ``VMCP_CW:行号|消息`` 格式，从消息中提取：
    - warning_id: ``[Vivado 12-1411]`` 中的 ID
    - source_file: 消息末尾 ``[xxx.xdc:N]`` 中的文件名
    - port: ``port xxx`` 中的端口名
    - pin: ``package_pin xxx`` 中的引脚名
    """
    results: list[CriticalWarning] = []
    for line in raw.splitlines():
        m = _RE_CW_LINE.match(line.strip())
        if m is None:
            continue

        line_number = int(m.group(1))
        message = m.group(2)

        # 提取 warning ID（取第一个匹配）
        wid_match = _RE_WARNING_ID.search(message)
        warning_id = wid_match.group(1) if wid_match else "UNKNOWN"

        # 提取源文件（取最后一个匹配，因为 warning ID 也用方括号）
        source_file = ""
        for sf_match in _RE_SOURCE_FILE.finditer(message):
            source_file = sf_match.group(1)

        # 提取端口名（取第一个匹配）
        port_match = _RE_PORT.search(message)
        port = port_match.group(1) if port_match else ""

        # 提取引脚名
        pin_match = _RE_PIN.search(message)
        pin = pin_match.group(1) if pin_match else ""

        results.append(
            CriticalWarning(
                warning_id=warning_id,
                message=message,
                line_number=line_number,
                source_file=source_file,
                port=port,
                pin=pin,
            )
        )
    return results


def group_warnings(warnings: list[CriticalWarning]) -> list[WarningGroup]:
    """按 warning_id 对 CriticalWarning 列表进行聚合分组。

    每组查询 ``_KNOWN_CATEGORIES`` 获取分类标签和中文建议。
    未知 ID 使用 ``"UNKNOWN"`` 分类和通用建议。
    """
    # 按 warning_id 分桶，保持首次出现顺序
    buckets: dict[str, list[CriticalWarning]] = {}
    for cw in warnings:
        buckets.setdefault(cw.warning_id, []).append(cw)

    groups: list[WarningGroup] = []
    for wid, cw_list in buckets.items():
        if wid in _KNOWN_CATEGORIES:
            category, suggestion = _KNOWN_CATEGORIES[wid]
        else:
            category = "UNKNOWN"
            suggestion = "未知警告类型，请查阅 Vivado 日志获取详细信息。"

        # 收集受影响的端口（去重，保持顺序）
        seen_ports: set[str] = set()
        affected_ports: list[str] = []
        for cw in cw_list:
            if cw.port and cw.port not in seen_ports:
                seen_ports.add(cw.port)
                affected_ports.append(cw.port)

        # 收集源文件（去重，保持顺序）
        seen_files: set[str] = set()
        source_files: list[str] = []
        for cw in cw_list:
            if cw.source_file and cw.source_file not in seen_files:
                seen_files.add(cw.source_file)
                source_files.append(cw.source_file)

        groups.append(
            WarningGroup(
                warning_id=wid,
                category=category,
                count=len(cw_list),
                first_line=cw_list[0].line_number,
                message_template=cw_list[0].message,
                affected_ports=affected_ports,
                source_files=source_files,
                suggestion=suggestion,
            )
        )
    return groups


def format_warning_report(report: WarningReport) -> str:
    """将 WarningReport 格式化为人类可读的中文文本。

    如果存在 CRITICAL WARNING，首行为醒目提示：
    ``!! 发现 N 条 CRITICAL WARNING !!``
    """
    lines: list[str] = []

    # 概览行
    lines.append(
        f"诊断概览: errors={report.errors}, "
        f"critical_warnings={report.critical_warnings}, "
        f"warnings={report.warnings}"
    )

    if report.critical_warnings > 0:
        lines.insert(0, f"!! 发现 {report.critical_warnings} 条 CRITICAL WARNING !!")
        lines.append("")

        for g in report.groups:
            lines.append(f"--- [{g.warning_id}] {g.category} ({g.count} 条) ---")
            lines.append(f"  首次出现: 第 {g.first_line} 行")
            if g.affected_ports:
                port_str = ", ".join(g.affected_ports[:10])
                if len(g.affected_ports) > 10:
                    port_str += f" ... 共 {len(g.affected_ports)} 个"
                lines.append(f"  受影响端口: {port_str}")
            if g.source_files:
                lines.append(f"  约束文件: {', '.join(g.source_files)}")
            lines.append(f"  建议: {g.suggestion}")
            lines.append("")

    return "\n".join(lines)


def parse_pre_bitstream(raw: str) -> tuple[str, int, list[str]]:
    """解析 CHECK_PRE_BITSTREAM 脚本输出。

    返回 ``(status, cw_count, sample_lines)``：
    - status: 实现状态字符串（如 "route_design Complete"）
    - cw_count: CRITICAL WARNING 计数
    - sample_lines: 前 N 条 CRITICAL WARNING 样本文本

    若未匹配到状态行，返回 ``("UNKNOWN", -1, [])``。
    """
    status = "UNKNOWN"
    cw_count = -1
    sample_lines: list[str] = []

    m = _RE_PRE_BIT.search(raw)
    if m is not None:
        status = m.group(1)
        cw_count = int(m.group(2))

    for line in raw.splitlines():
        cm = _RE_PRE_BIT_CW.match(line.strip())
        if cm is not None:
            sample_lines.append(cm.group(1))

    return (status, cw_count, sample_lines)
