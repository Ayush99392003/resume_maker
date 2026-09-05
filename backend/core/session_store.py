"""Durable JSON chat session store."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via temporary file, with fallback for FUSE."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
        ) as tf:
            tf.write(content)
            temp_path = Path(tf.name)
        os.replace(temp_path, path)
    except Exception:
        # Direct write fallback for FUSE mounts (e.g., GCS FUSE on Cloud Run)
        path.write_text(content, encoding="utf-8")
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


_DISCONTINUED_MODELS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-70b-versatile": "openai/gpt-oss-120b",
    "gpt-oss-120b": "openai/gpt-oss-120b",
}


def _normalize_model(model_name: Optional[str]) -> str:
    if not model_name:
        return "openai/gpt-oss-120b"
    return _DISCONTINUED_MODELS.get(model_name, model_name)


class ChatMessageRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str
    content: str
    timestamp: str = Field(default_factory=_utcnow)
    provider: Optional[str] = None
    model: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class TurnSnapshot(BaseModel):
    """State captured before one orchestrator chat turn — for user-initiated undo."""

    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    latex_code: str = ""
    zones: List[Dict[str, Any]] = Field(default_factory=list)
    zone_order: List[int] = Field(default_factory=list)
    header: str = ""
    footer: str = ""
    # Filled in *after* the turn completes, once we know the message IDs
    message_ids: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utcnow)


class ChatSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: Optional[str] = None
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
    # Rollback snapshot — written before every orchestrator turn (single slot,
    # used for automatic rollback on compile failure)
    zones_snapshot: List[Dict[str, Any]] = Field(default_factory=list)
    latex_code_snapshot: str = ""
    header_snapshot: str = ""
    footer_snapshot: str = ""
    # Per-turn undo history (ring buffer, newest last)
    turn_history: List[TurnSnapshot] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)
    active_provider: str = "groq"
    active_model: str = "openai/gpt-oss-120b"
    messages: List[ChatMessageRecord] = Field(default_factory=list)


# Maximum number of undo steps kept in memory per session
MAX_UNDO_DEPTH: int = 10


class SessionStore:
    """File-backed session persistence under data/sessions/."""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = (
                Path(__file__).resolve().parent.parent
                / "data"
                / "sessions"
            )
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def create(
        self,
        *,
        username: Optional[str] = None,
        template_name: str = "modern",
        title: str = "New resume chat",
        latex_code: str = "",
        provider: str = "groq",
        model: str = "openai/gpt-oss-120b",
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
            username=username,
            title=title,
            template_name=template_name,
            latex_code=latex_code,
            active_provider=provider,
            active_model=_normalize_model(model),
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
        _atomic_write_text(
            path, session.model_dump_json(indent=2)
        )
        return session

    def get(self, session_id: str) -> Optional[ChatSession]:
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        session = ChatSession(**data)
        normalized = _normalize_model(session.active_model)
        if session.active_model != normalized:
            session.active_model = normalized
            self.save(session)
        return session

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(
        self, username: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        items = []
        for path in sorted(
            self.base_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session_user = data.get("username")
                if username is not None and session_user != username:
                    continue
                items.append(
                    {
                        "session_id": data.get("session_id"),
                        "username": session_user,
                        "title": data.get("title"),
                        "updated_at": data.get("updated_at"),
                        "active_provider": data.get("active_provider"),
                        "active_model": _normalize_model(
                            data.get("active_model")
                        ),
                        "template_name": data.get("template_name"),
                        "setup_complete": data.get("setup_complete", False),
                        "zone_count": len(data.get("zones") or []),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue
        return items

    def verify_ownership(
        self, session: ChatSession, username: Optional[str]
    ) -> bool:
        """Check whether session belongs to the user or is legacy."""
        if not username:
            return False
        if not session.username:
            # Legacy unowned session: claim it for this user
            session.username = username
            self.save(session)
            return True
        return session.username == username


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


def take_snapshot(
    session: ChatSession, store: "SessionStore"
) -> None:
    """Persist a rollback snapshot before an orchestrator edit turn.

    Writes the current good state into ``zones_snapshot``,
    ``latex_code_snapshot``, ``header_snapshot``, and ``footer_snapshot``
    and immediately saves to disk.  If the subsequent compile fails the
    session can be restored via :func:`rollback_to_snapshot`.

    Args:
        session: The active :class:`ChatSession`.
        store: The :class:`SessionStore` instance to persist with.
    """
    session.zones_snapshot = [
        dict(z) for z in (session.zones or [])
    ]
    session.latex_code_snapshot = session.latex_code
    session.header_snapshot = session.header
    session.footer_snapshot = session.footer
    store.save(session)


def rollback_to_snapshot(
    session: ChatSession, store: "SessionStore"
) -> bool:
    """Restore session zones from the pre-edit snapshot.

    Should be called when Tectonic compilation fails after an orchestrator
    edit so the user is not left with a permanently broken session.

    Args:
        session: The active :class:`ChatSession`.
        store: The :class:`SessionStore` instance to persist with.

    Returns:
        ``True`` if a valid snapshot existed and was restored,
        ``False`` if no snapshot was available.
    """
    if not session.zones_snapshot and not session.latex_code_snapshot:
        return False
    session.zones = list(session.zones_snapshot)
    session.latex_code = session.latex_code_snapshot
    session.header = session.header_snapshot
    session.footer = session.footer_snapshot
    store.save(session)
    return True


# ---------------------------------------------------------------------------
# Per-turn undo history
# ---------------------------------------------------------------------------


def push_turn_snapshot(
    session: ChatSession,
    store: "SessionStore",
) -> TurnSnapshot:
    """Capture the current document state before an orchestrator turn.

    The snapshot is appended to ``session.turn_history`` (capped at
    :data:`MAX_UNDO_DEPTH`).  Call :func:`tag_turn_snapshot` once the
    resulting messages are known to attach their IDs.

    Returns the new :class:`TurnSnapshot` so the caller can tag it later.
    """
    snap = TurnSnapshot(
        latex_code=session.latex_code,
        zones=[dict(z) for z in (session.zones or [])],
        zone_order=list(session.zone_order or []),
        header=session.header,
        footer=session.footer,
    )
    session.turn_history.append(snap)
    # Trim oldest entries so we never exceed the ring-buffer cap
    if len(session.turn_history) > MAX_UNDO_DEPTH:
        session.turn_history = session.turn_history[-MAX_UNDO_DEPTH:]
    # Also keep the old single-slot snapshot for compile-failure auto-rollback
    session.zones_snapshot = snap.zones
    session.latex_code_snapshot = snap.latex_code
    session.header_snapshot = snap.header
    session.footer_snapshot = snap.footer
    store.save(session)
    return snap


def tag_turn_snapshot(
    session: ChatSession,
    snap: TurnSnapshot,
    message_ids: List[str],
    store: "SessionStore",
) -> None:
    """Attach real message IDs to a snapshot after the turn completes.

    Must be called with the ``snap`` returned by :func:`push_turn_snapshot`
    once you know the IDs of the user+assistant messages that were produced.
    """
    for s in reversed(session.turn_history):
        if s.turn_id == snap.turn_id:
            s.message_ids = list(message_ids)
            break
    store.save(session)


def pop_turn_snapshot(
    session: ChatSession,
    store: "SessionStore",
) -> Optional[TurnSnapshot]:
    """Remove and return the most recent undo snapshot.

    Restores ``session.latex_code``, ``session.zones``, etc. from that
    snapshot and removes the messages whose IDs were tagged onto it.

    Returns the :class:`TurnSnapshot` that was applied, or ``None`` when
    the history is empty.
    """
    if not session.turn_history:
        return None
    snap = session.turn_history.pop()
    # Restore document state
    session.latex_code = snap.latex_code
    session.zones = list(snap.zones)
    session.zone_order = list(snap.zone_order)
    session.header = snap.header
    session.footer = snap.footer
    # Remove the messages produced during that turn
    if snap.message_ids:
        msg_id_set = set(snap.message_ids)
        session.messages = [
            m for m in session.messages if m.id not in msg_id_set
        ]
    store.save(session)
    return snap


session_store = SessionStore()
