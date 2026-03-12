"""测试 fixtures：mock Vivado 进程、会话管理器等。"""

import pytest

from vivado_mcp.vivado.session_manager import SessionManager


@pytest.fixture
def session_manager() -> SessionManager:
    """创建一个不连接实际 Vivado 的 SessionManager 实例。"""
    return SessionManager(vivado_path="/fake/vivado")
