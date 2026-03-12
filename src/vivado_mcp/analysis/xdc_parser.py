"""XDC 约束解析器：解析 VMCP_XDC_PIN 格式的引脚约束信息。

从 Vivado Tcl 脚本预处理后的 VMCP_XDC_PIN 输出中提取：
- 源 XDC 文件路径
- 行号
- 引脚名称
- 端口名称

输入格式示例：
    VMCP_XDC_PIN:C:/project/board_pins.xdc|15|AA4|pcie_7x_mgt_rtl_0_rxp[0]
    VMCP_XDC_PIN_DONE
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class XdcConstraint:
    """单条 PACKAGE_PIN 约束的结构化信息。

    Attributes:
        source_file: 约束来源 XDC 文件路径。
        line_number: 在 XDC 文件中的行号。
        pin: 封装引脚名称，如 "AA4"。
        port: 端口名称，如 "pcie_7x_mgt_rtl_0_rxp[0]"。
    """

    source_file: str
    line_number: int
    pin: str
    port: str


# 匹配 VMCP_XDC_PIN 数据行的正则表达式
# 格式：VMCP_XDC_PIN:<file>|<line>|<pin>|<port>
_XDC_PIN_RE = re.compile(
    r"^VMCP_XDC_PIN:"      # 前缀标记
    r"([^|]+)"              # 组1: 源文件路径
    r"\|"                   # 分隔符
    r"(\d+)"                # 组2: 行号
    r"\|"                   # 分隔符
    r"([^|]+)"              # 组3: 引脚名称
    r"\|"                   # 分隔符
    r"(.+)$"                # 组4: 端口名称（可能含 [] 等特殊字符）
)


def parse_xdc_constraints(raw: str) -> list[XdcConstraint]:
    """解析 VMCP_XDC_PIN 格式的约束输出。

    逐行扫描，匹配 VMCP_XDC_PIN: 前缀的行，提取约束信息。
    忽略 VMCP_XDC_PIN_DONE 标记和其他非匹配行。

    Args:
        raw: 包含 VMCP_XDC_PIN 行的原始文本。

    Returns:
        解析后的 XdcConstraint 列表。
    """
    if not raw or not raw.strip():
        return []

    constraints: list[XdcConstraint] = []

    for line in raw.splitlines():
        line = line.strip()

        # 跳过结束标记和空行
        if not line or line == "VMCP_XDC_PIN_DONE":
            continue

        match = _XDC_PIN_RE.match(line)
        if match:
            constraints.append(
                XdcConstraint(
                    source_file=match.group(1).strip(),
                    line_number=int(match.group(2)),
                    pin=match.group(3).strip(),
                    port=match.group(4).strip(),
                )
            )

    return constraints
