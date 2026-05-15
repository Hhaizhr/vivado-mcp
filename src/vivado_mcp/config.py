from __future__ import annotations

import glob
import os
import secrets
import shutil
import sys
from pathlib import Path

VMCP_AUTH_ENV = "VMCP_AUTH_TOKEN"
_VMCP_HOME_DIR = ".vivado-mcp"
_TOKEN_FILE_NAME = "auth_token.txt"
_SERVER_SCRIPT_NAME = "vivado_mcp_server.tcl"


def _default_install_globs() -> list[str]:
    if sys.platform == "win32":
        return [
            "D:/Xilinx/Vivado/*/bin/vivado.bat",
            "C:/Xilinx/Vivado/*/bin/vivado.bat",
        ]
    return [
        "/tools/Xilinx/Vivado/*/bin/vivado",
        "/opt/Xilinx/Vivado/*/bin/vivado",
        "/opt/xilinx/Vivado/*/bin/vivado",
        os.path.expanduser("~/Xilinx/Vivado/*/bin/vivado"),
    ]


def _default_xsct_globs() -> list[str]:
    if sys.platform == "win32":
        return [
            "D:/Xilinx/Vitis/*/bin/xsct.bat",
            "C:/Xilinx/Vitis/*/bin/xsct.bat",
            "D:/Xilinx/SDK/*/bin/xsct.bat",
            "C:/Xilinx/SDK/*/bin/xsct.bat",
        ]
    return [
        "/tools/Xilinx/Vitis/*/bin/xsct",
        "/opt/Xilinx/Vitis/*/bin/xsct",
        "/opt/xilinx/Vitis/*/bin/xsct",
        os.path.expanduser("~/Xilinx/Vitis/*/bin/xsct"),
    ]


def normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def find_vivado(vivado_path: str | None = None) -> str:
    if vivado_path and os.path.isfile(vivado_path):
        return normalize_path(vivado_path)

    env_path = os.environ.get("VIVADO_PATH")
    if env_path and os.path.isfile(env_path):
        return normalize_path(env_path)

    which = shutil.which("vivado") or shutil.which("vivado.bat")
    if which:
        return normalize_path(which)

    for pattern in _default_install_globs():
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return normalize_path(matches[0])

    raise FileNotFoundError(
        "未找到 Vivado installation. Set VIVADO_PATH or add vivado to PATH."
    )


def find_xsct(xsct_path: str | None = None) -> str:
    if xsct_path and os.path.isfile(xsct_path):
        return normalize_path(xsct_path)

    env_path = os.environ.get("XSCT_PATH") or os.environ.get("VITIS_XSCT_PATH")
    if env_path and os.path.isfile(env_path):
        return normalize_path(env_path)

    which = shutil.which("xsct") or shutil.which("xsct.bat")
    if which:
        return normalize_path(which)

    for pattern in _default_xsct_globs():
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return normalize_path(matches[0])

    raise FileNotFoundError(
        "未找到 XSCT installation. Set XSCT_PATH or add xsct to PATH."
    )


def get_vivado_version(vivado_path: str) -> str:
    parts = Path(vivado_path).parts
    for i, part in enumerate(parts):
        if part.lower() == "vivado" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if candidate[:2] == "20" and "." in candidate:
                return candidate
    return "unknown"


def vmcp_home_dir() -> Path:
    return Path.home() / _VMCP_HOME_DIR


def auth_token_file() -> Path:
    return vmcp_home_dir() / _TOKEN_FILE_NAME


def installed_server_script() -> Path:
    return vmcp_home_dir() / _SERVER_SCRIPT_NAME


def generate_auth_token() -> str:
    return secrets.token_urlsafe(24)


def save_auth_token(token: str) -> Path:
    path = auth_token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip() + "\n", encoding="utf-8")
    return path


def load_auth_token() -> str | None:
    env_token = os.environ.get(VMCP_AUTH_ENV, "").strip()
    if env_token:
        return env_token

    path = auth_token_file()
    if not path.is_file():
        return None

    token = path.read_text(encoding="utf-8", errors="replace").strip()
    return token or None
