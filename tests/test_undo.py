"""Tests for chat undo functionality and snapshot rollbacks."""

import asyncio
import sys
import uuid
from pathlib import Path
import pytest
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.session_store import (  # noqa: E402
    session_store,
    push_turn_snapshot,
    tag_turn_snapshot,
    pop_turn_snapshot,
)
from core.auth_store import auth_store  # noqa: E402
from main import undo_last_turn  # noqa: E402


def test_turn_snapshot_push_tag_pop():
    session = session_store.create(
        latex_code=r"\documentclass{article}\begin{document}V1\end{document}",
        zones=[{"zone_no": 1, "body": "Z1", "kind": "body"}],
        zone_order=[1],
        header="HeaderV1",
        footer="FooterV1",
    )

    # Push snapshot before turn 1
    snap1 = push_turn_snapshot(session, session_store)
    assert snap1.latex_code == session.latex_code
    assert len(session.turn_history) == 1

    # Simulate turn 1 updates
    session_store.append_message(session, role="user", content="Change to V2")
    user_msg_id = session.messages[-1].id
    session_store.append_message(
        session, role="assistant", content="Done V2"
    )
    asst_msg_id = session.messages[-1].id

    session.latex_code = (
        r"\documentclass{article}\begin{document}V2\end{document}"
    )
    session.header = "HeaderV2"
    session_store.save(session)

    tag_turn_snapshot(
        session, snap1, [user_msg_id, asst_msg_id], session_store
    )

    # Now verify state before undo
    assert len(session.messages) == 2
    assert "V2" in session.latex_code

    # Pop turn snapshot
    popped = pop_turn_snapshot(session, session_store)
    assert popped is not None
    assert popped.turn_id == snap1.turn_id
    assert "V1" in session.latex_code
    assert session.header == "HeaderV1"
    assert len(session.messages) == 0
    assert len(session.turn_history) == 0

    # Clean up
    session_store.delete(session.session_id)


def test_undo_endpoint():
    username = f"undouser_{uuid.uuid4().hex[:6]}"
    auth_store.register(username, "pass123")
    token = auth_store.create_token(username)
    auth_header = f"Bearer {token}"

    session = session_store.create(
        latex_code=r"\documentclass{article}\begin{document}Base\end{document}",
        zones=[],
        zone_order=[],
        username=username,
    )
    sid = session.session_id

    # Trying to undo when empty raises HTTPException(400)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(undo_last_turn(session_id=sid, authorization=auth_header))
    assert excinfo.value.status_code == 400
    assert "Nothing to undo" in excinfo.value.detail

    # Push snapshot and make a turn
    original_code = session.latex_code
    snap = push_turn_snapshot(session, session_store)
    session_store.append_message(
        session, role="user", content="Add test text"
    )
    u_id = session.messages[-1].id
    session_store.append_message(
        session, role="assistant", content="Added test text"
    )
    a_id = session.messages[-1].id
    session.latex_code = original_code + "\n% modified"
    session_store.save(session)
    tag_turn_snapshot(session, snap, [u_id, a_id], session_store)

    # Now call undo_last_turn
    res_data = asyncio.run(
        undo_last_turn(session_id=sid, authorization=auth_header)
    )
    assert res_data["ok"] is True
    assert res_data["undo_depth"] == 0
    assert res_data["latex_code"] == original_code
    assert len(res_data["session"]["messages"]) == 0

    # Clean up
    session_store.delete(sid)
