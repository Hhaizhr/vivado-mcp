"""IP 参数解析器。

解析 INSPECT_IP_PARAMS Tcl 脚本产生的 VMCP_ 前缀结构化输出，
将 IP 的 CONFIG.* 属性列表转换为结构化对象。

输入格式（参见 tcl_scripts.py）:
- ``VMCP_IP_INFO:xilinx.com:ip:xdma:4.1``
- ``VMCP_IP_PARAM:CONFIG.PCIE_LINK_SPEED|5.0_GT/s``
- ``VMCP_IP_PARAM_DONE``
- ``VMCP_IP_PARAM_ERROR:IP 'xxx' not found``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ====================================================================== #
#  数据结构
# ====================================================================== #


@dataclass(frozen=True)
class IpParam:
    """单个 IP 配置参数。"""

    name: str        # "CONFIG.PCIE_LINK_SPEED"
    short_name: str  # "PCIE_LINK_SPEED"（去掉 CONFIG. 前缀）
    value: str


@dataclass
class IpParamReport:
    """IP 参数查询的完整报告。"""

    ip_name: str
    vlnv: str        # "xilinx.com:ip:xdma:4.1"
    params: list[IpParam] = field(default_factory=list)
    total_count: int = 0

    def filter(self, keyword: str) -> list[IpParam]:
        """按关键词过滤参数（不区分大小写，匹配名称或值）。"""
        if not keyword:
            return self.params
        kw = keyword.lower()
        return [
            p for p in self.params
            if kw in p.short_name.lower() or kw in p.value.lower()
        ]

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典。"""
        return {
            "ip_name": self.ip_name,
            "vlnv": self.vlnv,
            "total_count": self.total_count,
            "params": [
                {"name": p.name, "short_name": p.short_name, "value": p.value}
                for p in self.params
            ],
        }

    def format(self, keyword: str = "") -> str:
        """格式化为人类可读的中文文本。

        Args:
            keyword: 可选过滤关键词。
        """
        filtered = self.filter(keyword)
        lines: list[str] = []

        lines.append(f"=== IP 参数报告: {self.ip_name} ===")
        lines.append(f"VLNV: {self.vlnv}")
        lines.append(f"总参数数: {self.total_count}")

        if keyword:
            lines.append(f"过滤关键词: '{keyword}' (匹配 {len(filtered)} 条)")
        lines.append("")

        if not filtered:
            if keyword:
                lines.append(f"未找到包含 '{keyword}' 的参数。")
            else:
                lines.append("该 IP 没有 CONFIG.* 参数。")
            return "\n".join(lines)

        # 计算对齐宽度
        max_name_len = max(len(p.short_name) for p in filtered)
        # 限制最大宽度避免过宽
        max_name_len = min(max_name_len, 45)

        for p in filtered:
            lines.append(f"  {p.short_name:<{max_name_len}}  {p.value}")

        return "\n".join(lines)


# ====================================================================== #
#  编译正则
# ====================================================================== #

_RE_IP_INFO = re.compile(r"VMCP_IP_INFO:(.+)")
_RE_IP_PARAM = re.compile(r"VMCP_IP_PARAM:([^|]+)\|(.*)$")
_RE_IP_ERROR = re.compile(r"VMCP_IP_PARAM_ERROR:(.+)")


# ====================================================================== #
#  解析函数
# ====================================================================== #


def parse_ip_params(raw: str, ip_name: str) -> IpParamReport | None:
    """解析 INSPECT_IP_PARAMS 脚本输出。

    Args:
        raw: Tcl 脚本的原始输出文本。
        ip_name: 查询的 IP 实例名称。

    Returns:
        IpParamReport 实例。若 IP 未找到，返回 None。
    """
    # 检查错误
    for line in raw.splitlines():
        stripped = line.strip()
        if _RE_IP_ERROR.match(stripped):
            return None

    vlnv = ""
    params: list[IpParam] = []

    for line in raw.splitlines():
        stripped = line.strip()

        m_info = _RE_IP_INFO.match(stripped)
        if m_info:
            vlnv = m_info.group(1)
            continue

        m_param = _RE_IP_PARAM.match(stripped)
        if m_param:
            name = m_param.group(1)
            value = m_param.group(2)
            # 去掉 CONFIG. 前缀
            short_name = name[len("CONFIG."):] if name.startswith("CONFIG.") else name
            params.append(IpParam(name=name, short_name=short_name, value=value))
            continue

    return IpParamReport(
        ip_name=ip_name,
        vlnv=vlnv,
        params=params,
        total_count=len(params),
    )
