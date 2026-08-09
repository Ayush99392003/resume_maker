"""Durable JSON chat session store."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatMessageRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str
    content: str
    timestamp: str = Field(default_factory=_utcnow)
    provider: Optional[str] = None
    model: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ChatSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New resume chat"
    template_name: str = "modern"
    latex_code: str = ""
    # Numbered zone document (orchestrator source of truth)
    header: str = ""
    footer: str = ""
    zones: List[Dict[str, Any]] = Field(default_factory=list)
    zone_order: List[int] = Field(default_factory=list)
    next_zone_no: int = 1
    source_url: Optional[str] = None
    project_dir: Optional[str] = None
    setup_complete: bool = False
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)
    active_provider: str = "groq"
    active_model: str = "llama-3.3-70b-versatile"
    messages: List[ChatMessageRecord] = Field(default_factory=list)


class SessionStore:
    """File-backed session persistence under data/sessions/."""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent / "data" / "sessions"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def create(
        self,
        *,
        template_name: str = "modern",
        title: str = "New resume chat",
        latex_code: str = "",
        provider: str = "groq",
        model: str = "llama-3.3-70b-versatile",
        welcome: Optional[str] = None,
        header: str = "",
        footer: str = "",
        zones: Optional[List[Dict[str, Any]]] = None,
        zone_order: Optional[List[int]] = None,
        next_zone_no: int = 1,
        source_url: Optional[str] = None,
        project_dir: Optional[str] = None,
        setup_complete: bool = False,
    ) -> ChatSession:
        session = ChatSession(
            title=title,
            template_name=template_name,
            latex_code=latex_code,
            active_provider=provider,
            active_model=model,
            header=header,
            footer=footer,
            zones=zones or [],
            zone_order=zone_order or [],
            next_zone_no=next_zone_no,
            source_url=source_url,
            project_dir=project_dir,
            setup_complete=setup_complete,
        )
        if welcome:
            session.messages.append(
                ChatMessageRecord(role="assistant", content=welcome)
            )
        self.save(session)
        return session

    def save(self, session: ChatSession) -> ChatSession:
        session.updated_at = _utcnow()
        path = self._path(session.session_id)
        path.write_text(
            session.model_dump_json(indent=2), encoding="utf-8"
        )
        return session

    def get(self, session_id: str) -> Optional[ChatSession]:
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ChatSession(**data)

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        items = []
        for path in sorted(
            self.base_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append(
                    {
                        "session_id": data.get("session_id"),
                        "title": data.get("title"),
                        "updated_at": data.get("updated_at"),
                        "active_provider": data.get("active_provider"),
                        "active_model": data.get("active_model"),
                        "template_name": data.get("template_name"),
                        "setup_complete": data.get("setup_complete", False),
                        "zone_count": len(data.get("zones") or []),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue
        return items

    def append_message(
        self,
        session: ChatSession,
        *,
        role: str,
        content: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> ChatSession:
        session.messages.append(
            ChatMessageRecord(
                role=role,
                content=content,
                provider=provider,
                model=model,
                meta=meta or {},
            )
        )
        return self.save(session)

    def set_model(
        self, session: ChatSession, provider: str, model: str
    ) -> ChatSession:
        session.active_provider = provider
        session.active_model = model
        return self.save(session)

    def set_latex(self, session: ChatSession, latex_code: str) -> ChatSession:
        session.latex_code = latex_code
        return self.save(session)


session_store = SessionStore()
