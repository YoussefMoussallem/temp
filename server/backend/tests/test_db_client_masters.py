"""Phase 1.4 — backend's db_client masters bridge.

These functions live on the backend service and call out to the
db-service over HTTP. Tests mock httpx so we don't need a live
db-service to assert the bridge layer's contract:

  * URL templating is correct
  * Authorization header passes through verbatim
  * Successful responses are returned untouched
  * raise_for_status fires on critical-path errors

The actual round-trip-against-real-db-service test is a higher layer
(end-to-end smoke in 1.6). Here we just trust httpx.
"""

from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.db import masters

pytestmark = pytest.mark.asyncio


def _mock_response(status: int = 200, json_body=None, content: bytes = b""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body or {}
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def _patch_async_client(resp):
    """Patch httpx.AsyncClient so __aenter__ yields a client whose
    HTTP methods all return ``resp``. Returns the patched mock so
    tests can assert call args."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    client.delete = AsyncMock(return_value=resp)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm), client


async def test_list_masters_url_and_returns_payload():
    resp = _mock_response(200, {"masters": [{"id": "abc"}]})
    p, client = _patch_async_client(resp)
    with p:
        out = await masters.list_masters("Bearer xyz", "proj-id")
    assert out == [{"id": "abc"}]
    args, kwargs = client.get.call_args
    assert args[0].endswith("/api/projects/proj-id/masters")
    assert kwargs["headers"] == {"Authorization": "Bearer xyz"}


async def test_create_master_posts_metadata():
    resp = _mock_response(200, {"id": "m1", "name": "T"})
    p, client = _patch_async_client(resp)
    with p:
        out = await masters.create_master(
            "Bearer xyz",
            "proj-id",
            name="T",
            manifest={"canvas": {"w": 1280, "h": 720}},
            source_sha256="abc",
            source_pptx_b64="payload",
        )
    assert out["id"] == "m1"
    args, kwargs = client.post.call_args
    assert args[0].endswith("/api/projects/proj-id/masters")
    body = kwargs["json"]
    assert body["name"] == "T"
    assert body["source_sha256"] == "abc"
    assert body["source_pptx_b64"] == "payload"


async def test_get_master_pptx_returns_bytes():
    resp = _mock_response(200, content=b"PK\x03\x04 fake")
    p, client = _patch_async_client(resp)
    with p:
        data = await masters.get_master_pptx("Bearer x", "m-1")
    assert data == b"PK\x03\x04 fake"


async def test_activate_master_posts_to_activate_path():
    resp = _mock_response(200, {"active_master_id": "m-1"})
    p, client = _patch_async_client(resp)
    with p:
        out = await masters.activate_master("Bearer x", "m-1")
    assert out["active_master_id"] == "m-1"
    args, _ = client.post.call_args
    assert args[0].endswith("/api/masters/m-1/activate")


async def test_delete_master_returns_none():
    resp = _mock_response(204)
    p, client = _patch_async_client(resp)
    with p:
        out = await masters.delete_master("Bearer x", "m-1")
    assert out is None
    args, _ = client.delete.call_args
    assert args[0].endswith("/api/masters/m-1")
