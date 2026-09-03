"""Tests for multi-user session isolation and concurrency safety."""

import sys
import uuid
from pathlib import Path

import httpx
import pytest

# Ensure backend directory is in path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from core.auth_store import auth_store
from core.session_store import session_store
from main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.anyio
async def test_user_session_isolation(client):
    """Test that users cannot see or modify each other's sessions."""
    user_a_name = f"usera_{uuid.uuid4().hex[:6]}"
    user_b_name = f"userb_{uuid.uuid4().hex[:6]}"

    # 1. Register both users
    resp_a = await client.post(
        "/auth/register",
        json={"username": user_a_name, "password": "password123"},
    )
    assert resp_a.status_code == 200, resp_a.text
    token_a = resp_a.json()["token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    resp_b = await client.post(
        "/auth/register",
        json={"username": user_b_name, "password": "password123"},
    )
    assert resp_b.status_code == 200, resp_b.text
    token_b = resp_b.json()["token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 2. User A creates Session A
    create_a = await client.post(
        "/sessions",
        json={
            "template_name": "modern",
            "title": "User A Resume",
        },
        headers=headers_a,
    )
    assert create_a.status_code == 200, create_a.text
    session_a_id = create_a.json()["session_id"]

    # 3. User B creates Session B
    create_b = await client.post(
        "/sessions",
        json={
            "template_name": "modern",
            "title": "User B Resume",
        },
        headers=headers_b,
    )
    assert create_b.status_code == 200, create_b.text
    session_b_id = create_b.json()["session_id"]

    # 4. User A listing sessions should only contain session A, not session B
    list_a = await client.get("/sessions", headers=headers_a)
    assert list_a.status_code == 200
    ids_for_a = [s["session_id"] for s in list_a.json()["sessions"]]
    assert session_a_id in ids_for_a
    assert session_b_id not in ids_for_a

    # 5. User B listing sessions should only contain session B, not session A
    list_b = await client.get("/sessions", headers=headers_b)
    assert list_b.status_code == 200
    ids_for_b = [s["session_id"] for s in list_b.json()["sessions"]]
    assert session_b_id in ids_for_b
    assert session_a_id not in ids_for_b

    # 6. User B trying to access User A's session should receive 403 Forbidden
    get_b_attempts_a = await client.get(
        f"/sessions/{session_a_id}", headers=headers_b
    )
    assert get_b_attempts_a.status_code == 403

    # 7. User B trying to delete User A's session should receive 403 Forbidden
    del_b_attempts_a = await client.delete(
        f"/sessions/{session_a_id}", headers=headers_b
    )
    assert del_b_attempts_a.status_code == 403

    # Session A should still exist
    get_a_valid = await client.get(
        f"/sessions/{session_a_id}", headers=headers_a
    )
    assert get_a_valid.status_code == 200
    assert get_a_valid.json()["session_id"] == session_a_id


def test_atomic_token_persistence():
    """Verify rapid concurrent token creation without corruption."""
    username = f"user_{uuid.uuid4().hex[:6]}"
    user = auth_store.register(username, "secretpass")

    tokens = []
    for _ in range(10):
        t = auth_store.create_token(user.username)
        tokens.append(t)

    # Verify all tokens map back to user
    for t in tokens:
        resolved = auth_store.user_from_token(t)
        assert resolved is not None
        assert resolved.username == user.username


@pytest.mark.anyio
async def test_legacy_session_claiming(client):
    """Test that a legacy session with no username is safely claimed by owner."""
    user_name = f"user_{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/auth/register",
        json={"username": user_name, "password": "password123"},
    )
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create unowned legacy session directly
    legacy_session = session_store.create(
        username=None,
        template_name="modern",
        title="Legacy Unowned Resume",
    )
    legacy_id = legacy_session.session_id

    # User accesses legacy session -> should be claimed and allowed
    get_resp = await client.get(f"/sessions/{legacy_id}", headers=headers)
    assert get_resp.status_code == 200

    # Verify ownership is now assigned to user_name
    reloaded = session_store.get(legacy_id)
    assert reloaded.username == user_name


@pytest.mark.anyio
async def test_concurrent_compiles(client):
    """Test that multiple concurrent compilation requests succeed safely."""
    import asyncio

    minimal_latex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Hello Concurrent World!\n"
        "\\end{document}\n"
    )

    async def compile_task():
        return await client.post(
            "/compile",
            json={"latex_code": minimal_latex},
        )

    # Launch 3 simultaneous compiles
    responses = await asyncio.gather(
        compile_task(), compile_task(), compile_task()
    )

    for resp in responses:
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("pdf_base64") is not None
        assert data.get("compile_error") is None

