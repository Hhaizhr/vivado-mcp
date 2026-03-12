"""纯 Python 解析模块：Vivado 输出结构化解析、警告分类、IO 验证、IP 参数/XCI 解析。

所有解析器不依赖 Vivado 进程，可独立测试。
"""

from vivado_mcp.analysis.io_parser import IoPort, IoReport, parse_report_io
from vivado_mcp.analysis.io_verifier import (
    IoMismatch,
    IoVerification,
    format_io_verification,
    verify_io_placement,
)
from vivado_mcp.analysis.ip_param_parser import IpParam, IpParamReport, parse_ip_params
from vivado_mcp.analysis.timing_parser import (
    TimingPath,
    TimingReport,
    TimingSummary,
    format_timing_report,
    parse_timing_summary,
)
from vivado_mcp.analysis.xci_parser import (
    XciCompareResult,
    XciConfig,
    XciParamDiff,
    compare_xci_configs,
    format_xci_compare,
    parse_xci,
)
from vivado_mcp.analysis.xdc_parser import XdcConstraint, parse_xdc_constraints

__all__ = [
    "IoMismatch",
    "IoPort",
    "IoReport",
    "IoVerification",
    "IpParam",
    "IpParamReport",
    "TimingPath",
    "TimingReport",
    "TimingSummary",
    "XciCompareResult",
    "XciConfig",
    "XciParamDiff",
    "XdcConstraint",
    "compare_xci_configs",
    "format_io_verification",
    "format_timing_report",
    "format_xci_compare",
    "parse_ip_params",
    "parse_report_io",
    "parse_timing_summary",
    "parse_xci",
    "parse_xdc_constraints",
    "verify_io_placement",
]
