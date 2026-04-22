from __future__ import annotations

import logging
import re
from typing import Literal

from vivado_mcp.vivado.base_session import BaseSession
from vivado_mcp.vivado.gui_session import GuiSession
from vivado_mcp.vivado.session import SubprocessSession

VivadoSession = SubprocessSession

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
SessionMode = Literal["gui", "tcl", "attach"]
_VALID_MODES: tuple[str, ...] = ("gui", "tcl", "attach")


def _validate_session_id(session_id: str) -> str:
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(
            f"Invalid session_id: {session_id!r}. Only letters, digits, underscores, and hyphens are allowed."
        )
    return session_id


class SessionManager:
    def __init__(self, vivado_path: str):
        self._default_vivado_path = vivado_path
        self._sessions: dict[str, BaseSession] = {}

    @property
    def default_vivado_path(self) -> str:
        return self._default_vivado_path

    def get(self, session_id: str) -> BaseSession | None:
        _validate_session_id(session_id)
        session = self._sessions.get(session_id)
        if session and not session.is_alive:
            logger.warning("Session '%s' died and was pruned.", session_id)
            del self._sessions[session_id]
            return None
        return session

    async def start_session(
        self,
        session_id: str = "default",
        vivado_path: str | None = None,
        timeout: float = 120.0,
        mode: str = "gui",
        port: int = 9999,
        auth_token: str | None = None,
    ) -> tuple[BaseSession, str]:
        _validate_session_id(session_id)
        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid mode: {mode!r}. Supported modes: {_VALID_MODES}")

        existing = self.get(session_id)
        if existing:
            return existing, f"Session '{session_id}' is already running (mode={existing.mode})."

        path = vivado_path or self._default_vivado_path

        if mode == "tcl":
            session: BaseSession = SubprocessSession(vivado_path=path, session_id=session_id)
        elif mode == "gui":
            session = GuiSession(
                vivado_path=path,
                session_id=session_id,
                port=port,
                attach_only=False,
                auth_token=auth_token,
            )
        else:
            session = GuiSession(
                vivado_path=path,
                session_id=session_id,
                port=port,
                attach_only=True,
                auth_token=auth_token,
            )

        banner = await session.start(timeout=timeout)
        self._sessions[session_id] = session
        return session, banner

    async def get_or_start(
        self,
        session_id: str = "default",
        vivado_path: str | None = None,
        mode: str = "gui",
    ) -> BaseSession:
        session = self.get(session_id)
        if session:
            return session
        session, _ = await self.start_session(
            session_id=session_id,
            vivado_path=vivado_path,
            mode=mode,
        )
        return session

    async def stop_session(self, session_id: str) -> str:
        session = self._sessions.pop(session_id, None)
        if not session:
            return f"Session '{session_id}' does not exist."

        await session.stop()
        return f"Session '{session_id}' has been stopped."

    async def close_all(self) -> None:
        for sid in list(self._sessions.keys()):
            session = self._sessions.pop(sid, None)
            if session:
                try:
                    await session.stop()
                except Exception as exc:
                    logger.error("Failed to stop session '%s': %s", sid, exc)

    def list_sessions(self) -> list[dict]:
        return [s.status_dict() for s in self._sessions.values()]

    def prune_dead(self) -> list[str]:
        dead = [sid for sid, session in self._sessions.items() if not session.is_alive]
        for sid in dead:
            del self._sessions[sid]
        return dead
