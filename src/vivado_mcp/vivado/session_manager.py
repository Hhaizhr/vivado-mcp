"""SessionManager：多 Vivado 实例管理。

每个 session_id 对应一个独立的 VivadoSession（= 一个 vivado -mode tcl 子进程）。
支持按需创建、按 ID 关闭、全部清理（用于 lifespan shutdown）。
"""

import logging
import re

from vivado_mcp.vivado.session import VivadoSession

logger = logging.getLogger(__name__)

# session_id 格式：1~64 个字母、数字、下划线、连字符
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _validate_session_id(session_id: str) -> str:
    """验证 session_id 格式，拒绝非法字符。"""
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(
            f"session_id 格式非法: {session_id!r}。"
            f"仅允许字母、数字、下划线、连字符，长度 1~64。"
        )
    return session_id


class SessionManager:
    """管理多个 Vivado 会话实例。"""

    def __init__(self, vivado_path: str):
        """
        Args:
            vivado_path: 默认 Vivado 可执行文件路径。
        """
        self._default_vivado_path = vivado_path
        self._sessions: dict[str, VivadoSession] = {}

    @property
    def default_vivado_path(self) -> str:
        return self._default_vivado_path

    def get(self, session_id: str) -> VivadoSession | None:
        """获取已有会话（不自动创建）。"""
        _validate_session_id(session_id)
        session = self._sessions.get(session_id)
        if session and not session.is_alive:
            # 会话存在但进程已死，清理掉
            logger.warning("会话 '%s' 进程已死，自动清理。", session_id)
            del self._sessions[session_id]
            return None
        return session

    async def start_session(
        self,
        session_id: str = "default",
        vivado_path: str | None = None,
        timeout: float = 60.0,
    ) -> tuple[VivadoSession, str]:
        """启动新会话或返回已有会话。

        Args:
            session_id: 会话标识符。
            vivado_path: 可选的自定义 Vivado 路径（覆盖默认值）。
            timeout: Vivado 启动超时秒数。

        Returns:
            (会话实例, 启动横幅/状态消息) 元组。
        """
        _validate_session_id(session_id)
        existing = self.get(session_id)
        if existing:
            return existing, f"会话 '{session_id}' 已在运行中。"

        path = vivado_path or self._default_vivado_path
        session = VivadoSession(vivado_path=path, session_id=session_id)
        banner = await session.start(timeout=timeout)
        self._sessions[session_id] = session

        return session, banner

    async def get_or_start(
        self,
        session_id: str = "default",
        vivado_path: str | None = None,
    ) -> VivadoSession:
        """获取已有会话，若不存在则自动启动。"""
        session = self.get(session_id)
        if session:
            return session

        session, _ = await self.start_session(
            session_id=session_id,
            vivado_path=vivado_path,
        )
        return session

    async def stop_session(self, session_id: str) -> str:
        """关闭指定会话。

        Returns:
            操作结果描述。
        """
        session = self._sessions.pop(session_id, None)
        if not session:
            return f"会话 '{session_id}' 不存在。"

        await session.stop()
        return f"会话 '{session_id}' 已关闭。"

    async def close_all(self) -> None:
        """关闭所有会话（lifespan cleanup）。"""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            session = self._sessions.pop(sid, None)
            if session:
                try:
                    await session.stop()
                except Exception as e:
                    logger.error("关闭会话 '%s' 失败: %s", sid, e)

        logger.info("所有 Vivado 会话已清理完毕。")

    def list_sessions(self) -> list[dict]:
        """列出所有活跃会话的状态信息。"""
        # 先清理死亡的会话
        dead = [
            sid for sid, s in self._sessions.items()
            if not s.is_alive
        ]
        for sid in dead:
            del self._sessions[sid]

        return [s.status_dict() for s in self._sessions.values()]
