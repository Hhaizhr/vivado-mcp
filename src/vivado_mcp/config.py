"""Vivado 路径检测与全局配置。

检测优先级：
1. VIVADO_PATH 环境变量
2. 系统 PATH 中的 vivado / vivado.bat
3. 平台相关的默认安装路径（取最新版本）
"""

import glob
import os
import shutil
import sys
from pathlib import Path


def _default_install_globs() -> list[str]:
    """根据当前平台返回 Vivado 默认安装搜索路径。"""
    if sys.platform == "win32":
        return [
            "D:/Xilinx/Vivado/*/bin/vivado.bat",
            "C:/Xilinx/Vivado/*/bin/vivado.bat",
        ]
    else:
        # Linux / macOS
        return [
            "/tools/Xilinx/Vivado/*/bin/vivado",
            "/opt/Xilinx/Vivado/*/bin/vivado",
            "/opt/xilinx/Vivado/*/bin/vivado",
            os.path.expanduser("~/Xilinx/Vivado/*/bin/vivado"),
        ]


def normalize_path(path: str) -> str:
    """将 Windows 反斜杠路径转换为正斜杠（Tcl 兼容）。"""
    return path.replace("\\", "/")


def find_vivado(vivado_path: str | None = None) -> str:
    """查找 Vivado 可执行文件路径。

    Args:
        vivado_path: 显式指定的路径，优先级最高。

    Returns:
        Vivado 可执行文件的完整路径（正斜杠格式）。

    Raises:
        FileNotFoundError: 未找到任何 Vivado 安装。
    """
    # 1. 显式传入
    if vivado_path and os.path.isfile(vivado_path):
        return normalize_path(vivado_path)

    # 2. 环境变量 VIVADO_PATH
    env_path = os.environ.get("VIVADO_PATH")
    if env_path and os.path.isfile(env_path):
        return normalize_path(env_path)

    # 3. 系统 PATH
    which = shutil.which("vivado") or shutil.which("vivado.bat")
    if which:
        return normalize_path(which)

    # 4. 平台相关的默认安装目录（取版本号最大的）
    for pattern in _default_install_globs():
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return normalize_path(matches[0])

    raise FileNotFoundError(
        "未找到 Vivado 安装。请设置 VIVADO_PATH 环境变量，"
        "或确保 vivado 可执行文件在系统 PATH 中。"
    )


def get_vivado_version(vivado_path: str) -> str:
    """从路径中提取 Vivado 版本号（如 '2019.1'）。"""
    parts = Path(vivado_path).parts
    for i, part in enumerate(parts):
        if part.lower() == "vivado" and i + 1 < len(parts):
            candidate = parts[i + 1]
            # 版本号格式: 20xx.x
            if candidate[:2] == "20" and "." in candidate:
                return candidate
    return "unknown"
