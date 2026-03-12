"""XCI 文件解析器与对比算法。

纯 Python 模块，不依赖 Vivado。解析 Xilinx IP .xci 文件（XML 格式），
提取 IP 配置参数并支持两个 XCI 文件的差异对比。

XCI 结构关键路径：
  spirit:design / spirit:componentInstances / spirit:componentInstance
    ├─ spirit:instanceName → 实例名（如 "xdma_0"）
    ├─ spirit:componentRef  → vendor/library/name/version（即 VLNV）
    └─ spirit:configurableElementValues
         └─ spirit:configurableElementValue[@spirit:referenceId] → 参数值
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# SPIRIT 命名空间
_NS = {"spirit": "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"}

# 文件大小上限（10MB）
_MAX_FILE_SIZE = 10 * 1024 * 1024


# ====================================================================== #
#  数据结构
# ====================================================================== #


@dataclass(frozen=True)
class XciConfig:
    """单个 XCI 文件的解析结果。"""

    file_path: str
    ip_name: str        # IP 类型名（如 "xdma"）
    instance_name: str  # 实例名（如 "xdma_0"）
    ip_version: str     # 版本号（如 "4.1"）
    params: dict[str, str] = field(default_factory=dict)  # referenceId → value


@dataclass(frozen=True)
class XciParamDiff:
    """单个参数的差异记录。"""

    param_name: str  # 简化后的参数名（去掉 PARAM_VALUE. 前缀）
    value_a: str     # 文件 A 的值（缺失为 "<absent>"）
    value_b: str     # 文件 B 的值（缺失为 "<absent>"）
    diff_type: str   # "modified" / "only_in_a" / "only_in_b"


@dataclass
class XciCompareResult:
    """两个 XCI 文件的对比结果。"""

    file_a: str
    file_b: str
    ip_match: bool      # IP 类型+版本是否一致
    identical_count: int
    diff_count: int
    diffs: list[XciParamDiff] = field(default_factory=list)
    all_params: list[tuple[str, str, str]] = field(default_factory=list)  # (name, val_a, val_b)

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典。"""
        return {
            "file_a": self.file_a,
            "file_b": self.file_b,
            "ip_match": self.ip_match,
            "identical_count": self.identical_count,
            "diff_count": self.diff_count,
            "diffs": [
                {
                    "param": d.param_name,
                    "value_a": d.value_a,
                    "value_b": d.value_b,
                    "type": d.diff_type,
                }
                for d in self.diffs
            ],
        }


# ====================================================================== #
#  解析函数
# ====================================================================== #


def _simplify_param_name(ref_id: str) -> str:
    """去掉 PARAM_VALUE. 前缀，保留有意义的参数名。"""
    prefix = "PARAM_VALUE."
    if ref_id.startswith(prefix):
        return ref_id[len(prefix):]
    return ref_id


def parse_xci(file_path: str) -> XciConfig:
    """解析单个 XCI 文件，提取 IP 配置参数。

    Args:
        file_path: XCI 文件的绝对路径。

    Returns:
        XciConfig 实例。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 文件格式错误或超过大小限制。
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"XCI 文件不存在: {file_path}")

    file_size = os.path.getsize(file_path)
    if file_size > _MAX_FILE_SIZE:
        raise ValueError(
            f"XCI 文件过大 ({file_size / 1024 / 1024:.1f}MB)，"
            f"上限 {_MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
        )

    if not file_path.lower().endswith(".xci"):
        raise ValueError(f"文件扩展名不是 .xci: {file_path}")

    try:
        tree = ET.parse(file_path)
    except ET.ParseError as e:
        raise ValueError(f"XML 解析失败: {e}") from e

    root = tree.getroot()

    # 提取 componentInstance
    instance = root.find(
        ".//spirit:componentInstances/spirit:componentInstance", _NS
    )
    if instance is None:
        raise ValueError("XCI 文件缺少 componentInstance 元素")

    # 实例名
    instance_name_el = instance.find("spirit:instanceName", _NS)
    instance_name = instance_name_el.text if instance_name_el is not None else ""

    # componentRef → IP 名称和版本（VLNV）
    comp_ref = instance.find("spirit:componentRef", _NS)
    ip_name = ""
    ip_version = ""
    if comp_ref is not None:
        ns_prefix = f"{{{_NS['spirit']}}}"
        ip_name = comp_ref.get(f"{ns_prefix}name", "")
        ip_version = comp_ref.get(f"{ns_prefix}version", "")

    # 提取所有 configurableElementValue
    params: dict[str, str] = {}
    for elem in instance.findall(
        ".//spirit:configurableElementValues/spirit:configurableElementValue", _NS
    ):
        ns_prefix = f"{{{_NS['spirit']}}}"
        ref_id = elem.get(f"{ns_prefix}referenceId", "")
        if ref_id:
            params[ref_id] = elem.text or ""

    return XciConfig(
        file_path=file_path,
        ip_name=ip_name,
        instance_name=instance_name,
        ip_version=ip_version,
        params=params,
    )


# ====================================================================== #
#  对比算法
# ====================================================================== #


def compare_xci_configs(config_a: XciConfig, config_b: XciConfig) -> XciCompareResult:
    """对比两个 XciConfig 的参数差异。

    Args:
        config_a: 基准配置。
        config_b: 待对比配置。

    Returns:
        XciCompareResult 包含所有差异。
    """
    ip_match = (config_a.ip_name == config_b.ip_name
                and config_a.ip_version == config_b.ip_version)

    all_keys = sorted(set(config_a.params) | set(config_b.params))

    diffs: list[XciParamDiff] = []
    all_params: list[tuple[str, str, str]] = []
    identical_count = 0

    for key in all_keys:
        simplified = _simplify_param_name(key)
        in_a = key in config_a.params
        in_b = key in config_b.params

        val_a = config_a.params.get(key, "<absent>")
        val_b = config_b.params.get(key, "<absent>")

        all_params.append((simplified, val_a, val_b))

        if in_a and in_b:
            if val_a == val_b:
                identical_count += 1
            else:
                diffs.append(XciParamDiff(
                    param_name=simplified,
                    value_a=val_a,
                    value_b=val_b,
                    diff_type="modified",
                ))
        elif in_a and not in_b:
            diffs.append(XciParamDiff(
                param_name=simplified,
                value_a=val_a,
                value_b="<absent>",
                diff_type="only_in_a",
            ))
        else:
            diffs.append(XciParamDiff(
                param_name=simplified,
                value_a="<absent>",
                value_b=val_b,
                diff_type="only_in_b",
            ))

    return XciCompareResult(
        file_a=config_a.file_path,
        file_b=config_b.file_path,
        ip_match=ip_match,
        identical_count=identical_count,
        diff_count=len(diffs),
        diffs=diffs,
        all_params=all_params,
    )


# ====================================================================== #
#  格式化
# ====================================================================== #


def format_xci_compare(result: XciCompareResult, show_all: bool = False) -> str:
    """将 XciCompareResult 格式化为人类可读的中文文本。

    Args:
        result: 对比结果。
        show_all: 是否显示所有参数（默认仅显示差异）。
    """
    lines: list[str] = []

    lines.append("=== XCI 配置对比 ===")
    lines.append(f"文件 A: {result.file_a}")
    lines.append(f"文件 B: {result.file_b}")
    lines.append(f"IP 类型匹配: {'是' if result.ip_match else '否（IP类型或版本不同）'}")
    lines.append(f"相同参数: {result.identical_count}, 差异参数: {result.diff_count}")
    lines.append("")

    if result.diff_count == 0 and not show_all:
        lines.append("两个 XCI 文件的配置完全相同。")
        return "\n".join(lines)

    if result.diffs:
        lines.append("--- 差异参数 ---")
        for d in result.diffs:
            if d.diff_type == "modified":
                lines.append(f"  {d.param_name}")
                lines.append(f"    A: {d.value_a}")
                lines.append(f"    B: {d.value_b}")
            elif d.diff_type == "only_in_a":
                lines.append(f"  {d.param_name}")
                lines.append(f"    A: {d.value_a}")
                lines.append("    B: (缺失)")
            else:
                lines.append(f"  {d.param_name}")
                lines.append("    A: (缺失)")
                lines.append(f"    B: {d.value_b}")
        lines.append("")

    if show_all and result.all_params:
        lines.append("--- 所有参数 ---")
        for name, val_a, val_b in result.all_params:
            marker = " " if val_a == val_b else "*"
            lines.append(f" {marker} {name}: A={val_a} | B={val_b}")
        lines.append("")

    return "\n".join(lines)
