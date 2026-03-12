"""Vivado report_timing_summary 解析器。

将 Vivado `report_timing_summary -return_string` 的原始文本输出
解析为结构化 Python 数据对象，供 MCP 工具层直接返回给 LLM。

解析策略：
1. Design Timing Summary 表格 → TimingSummary（WNS/TNS/WHS/THS + 端点计数）
2. 逐条 Slack 路径块 → TimingPath 列表（slack / source / dest / 时钟域等）

不依赖 Vivado 进程，可独立单元测试。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# ====================================================================== #
#  正则模式
# ====================================================================== #

# Design Timing Summary 表头行（用来定位数据行）
_SUMMARY_HEADER_RE = re.compile(
    r"WNS\(ns\)\s+TNS\(ns\)\s+TNS Failing Endpoints\s+TNS Total Endpoints"
    r"\s+WHS\(ns\)\s+THS\(ns\)\s+THS Failing Endpoints\s+THS Total Endpoints"
)

# 路径块各字段
_SLACK_RE = re.compile(r"Slack\s+\((MET|VIOLATED)\)\s*:\s*([-\d.]+)\s*ns")
_SOURCE_RE = re.compile(r"^\s+Source:\s+(.+)")
_DEST_RE = re.compile(r"^\s+Destination:\s+(.+)")
_PATH_GROUP_RE = re.compile(r"^\s+Path Group:\s+(\S+)")
_PATH_TYPE_RE = re.compile(r"^\s+Path Type:\s+(\S+)")
_REQUIREMENT_RE = re.compile(r"^\s+Requirement:\s+([-\d.]+)\s*ns")
_DATA_DELAY_RE = re.compile(r"^\s+Data Path Delay:\s+([-\d.]+)\s*ns")

# ====================================================================== #
#  数据结构
# ====================================================================== #


@dataclass(frozen=True)
class TimingSummary:
    """时序摘要指标（来自 Design Timing Summary 表格）。"""

    wns: float  # Worst Negative Slack (setup)
    tns: float  # Total Negative Slack (setup)
    whs: float  # Worst Hold Slack
    ths: float  # Total Hold Slack
    failing_endpoints: int  # setup failing endpoints
    total_endpoints: int  # setup total endpoints
    timing_met: bool  # wns >= 0 and whs >= 0


@dataclass(frozen=True)
class TimingPath:
    """单条时序路径信息（来自 Slack 块）。"""

    slack_ns: float
    met: bool  # True = MET, False = VIOLATED
    source: str  # 源寄存器/单元路径
    destination: str  # 目标寄存器/单元路径
    path_group: str  # 时钟域名称（如 "userclk2"）
    path_type: str  # "Setup" 或 "Hold"
    requirement_ns: float
    data_delay_ns: float


@dataclass
class TimingReport:
    """完整时序报告：摘要 + 路径列表。"""

    summary: TimingSummary
    paths: list[TimingPath] = field(default_factory=list)

    def to_dict(self) -> dict:
        """返回可直接 ``json.dumps`` 序列化的字典。"""
        return {
            "summary": asdict(self.summary),
            "paths": [asdict(p) for p in self.paths],
        }


# ====================================================================== #
#  内部辅助
# ====================================================================== #


def _parse_summary_table(text: str) -> TimingSummary:
    """从 Design Timing Summary 表格解析摘要行。

    定位策略：
    1. 找到同时包含 ``WNS(ns)`` 与 ``WHS(ns)`` 的表头行
    2. 跳过紧随其后的 ``-------`` 分隔行
    3. 解析下一行的 8 个数值字段

    如果找不到表头或数据行，返回全零的默认摘要。
    """
    lines = text.splitlines()

    # 寻找 Design Timing Summary 区段内的表头行
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if _SUMMARY_HEADER_RE.search(line):
            header_idx = i
            break

    if header_idx is None:
        return TimingSummary(
            wns=0.0, tns=0.0, whs=0.0, ths=0.0,
            failing_endpoints=0, total_endpoints=0, timing_met=True,
        )

    # 跳过分隔线（一行或多行 -------），找到第一行数据
    data_line: str | None = None
    for j in range(header_idx + 1, min(header_idx + 5, len(lines))):
        stripped = lines[j].strip()
        if stripped and not stripped.startswith("---"):
            data_line = stripped
            break

    if data_line is None:
        return TimingSummary(
            wns=0.0, tns=0.0, whs=0.0, ths=0.0,
            failing_endpoints=0, total_endpoints=0, timing_met=True,
        )

    tokens = data_line.split()
    if len(tokens) < 8:
        return TimingSummary(
            wns=0.0, tns=0.0, whs=0.0, ths=0.0,
            failing_endpoints=0, total_endpoints=0, timing_met=True,
        )

    wns = float(tokens[0])
    tns = float(tokens[1])
    failing_setup = int(tokens[2])
    total_setup = int(tokens[3])
    whs = float(tokens[4])
    ths = float(tokens[5])
    # tokens[6] = THS Failing, tokens[7] = THS Total（暂不单独存储）

    return TimingSummary(
        wns=wns,
        tns=tns,
        whs=whs,
        ths=ths,
        failing_endpoints=failing_setup,
        total_endpoints=total_setup,
        timing_met=(wns >= 0 and whs >= 0),
    )


def _parse_paths(text: str) -> list[TimingPath]:
    """逐块解析 ``Slack (MET/VIOLATED)`` 路径信息。

    每个路径块以 ``Slack (MET)`` 或 ``Slack (VIOLATED)`` 行开头，
    后续字段由缩进的 ``Key: Value`` 行组成。Source / Destination
    可能跨越多行（续行以大量空格 + ``(`` 开头），需要拼接。
    """
    lines = text.splitlines()
    paths: list[TimingPath] = []

    i = 0
    while i < len(lines):
        m_slack = _SLACK_RE.search(lines[i])
        if not m_slack:
            i += 1
            continue

        # 解析当前路径块
        met = m_slack.group(1) == "MET"
        slack_ns = float(m_slack.group(2))

        source = ""
        destination = ""
        path_group = ""
        path_type = ""
        requirement_ns = 0.0
        data_delay_ns = 0.0

        # 从 Slack 行之后逐行扫描，直到遇到下一个 Slack 行或文件末尾
        j = i + 1
        while j < len(lines):
            line = lines[j]

            # 遇到下一个 Slack 块，停止
            if _SLACK_RE.search(line):
                break

            m_src = _SOURCE_RE.match(line)
            if m_src:
                source = m_src.group(1).strip()
                # 检查续行
                j += 1
                while j < len(lines) and _is_continuation(lines[j]):
                    j += 1
                continue

            m_dst = _DEST_RE.match(line)
            if m_dst:
                destination = m_dst.group(1).strip()
                # 检查续行
                j += 1
                while j < len(lines) and _is_continuation(lines[j]):
                    j += 1
                continue

            m_pg = _PATH_GROUP_RE.match(line)
            if m_pg:
                path_group = m_pg.group(1).strip()
                j += 1
                continue

            m_pt = _PATH_TYPE_RE.match(line)
            if m_pt:
                path_type = m_pt.group(1).strip()
                j += 1
                continue

            m_req = _REQUIREMENT_RE.match(line)
            if m_req:
                requirement_ns = float(m_req.group(1))
                j += 1
                continue

            m_dd = _DATA_DELAY_RE.match(line)
            if m_dd:
                data_delay_ns = float(m_dd.group(1))
                j += 1
                continue

            j += 1

        paths.append(
            TimingPath(
                slack_ns=slack_ns,
                met=met,
                source=source,
                destination=destination,
                path_group=path_group,
                path_type=path_type,
                requirement_ns=requirement_ns,
                data_delay_ns=data_delay_ns,
            )
        )

        # 移动到下一个 Slack 块的起始位置
        i = j

    return paths


def _is_continuation(line: str) -> bool:
    """判断是否为 Source/Destination 的续行。

    续行特征：大量前导空格后紧跟 ``(``，例如
    ``                            (rising edge-triggered ...)``
    """
    stripped = line.lstrip()
    return stripped.startswith("(") and len(line) - len(stripped) >= 10


# ====================================================================== #
#  公共 API
# ====================================================================== #


def parse_timing_summary(raw_text: str) -> TimingReport:
    """解析 ``report_timing_summary -return_string`` 的完整输出。

    参数:
        raw_text: Vivado 返回的原始多行文本。

    返回:
        TimingReport —— 包含 summary（TimingSummary）和 paths（TimingPath 列表）。

    空输入或无法识别的格式不会抛异常，而是返回全零的默认报告。
    """
    summary = _parse_summary_table(raw_text)
    paths = _parse_paths(raw_text)
    return TimingReport(summary=summary, paths=paths)


def format_timing_report(report: TimingReport) -> str:
    """将 TimingReport 格式化为人类可读的摘要文本。

    重点高亮违例信息，方便 LLM 和用户快速判断时序状态。
    """
    s = report.summary
    lines: list[str] = []

    # 总体状态
    status = "PASS (时序满足)" if s.timing_met else "FAIL (时序违例)"
    lines.append(f"=== 时序分析摘要 === 状态: {status}")
    lines.append("")

    # Setup 指标
    lines.append(f"  Setup  WNS = {s.wns:+.3f} ns   TNS = {s.tns:.3f} ns")
    lines.append(f"         失败端点: {s.failing_endpoints} / {s.total_endpoints}")

    # Hold 指标
    lines.append(f"  Hold   WHS = {s.whs:+.3f} ns   THS = {s.ths:.3f} ns")
    lines.append("")

    # 违例警告
    if s.wns < 0:
        lines.append(f"  [!] Setup 违例: WNS = {s.wns:.3f} ns，需优化关键路径。")
    if s.whs < 0:
        lines.append(f"  [!] Hold 违例: WHS = {s.whs:.3f} ns，需检查时钟偏斜。")

    # 路径详情
    if report.paths:
        lines.append("")
        lines.append(f"--- 关键路径 ({len(report.paths)} 条) ---")
        for idx, p in enumerate(report.paths, 1):
            flag = "MET" if p.met else "VIOLATED"
            lines.append(f"  [{idx}] Slack {p.slack_ns:+.3f} ns ({flag})")
            lines.append(f"      {p.source} -> {p.destination}")
            lines.append(f"      时钟域: {p.path_group}  类型: {p.path_type}")
            lines.append(
                f"      Requirement: {p.requirement_ns:.3f} ns"
                f"  Data Delay: {p.data_delay_ns:.3f} ns"
            )

    return "\n".join(lines)
