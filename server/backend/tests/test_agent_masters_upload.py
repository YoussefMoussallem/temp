"""Phase 1.4 — agent backend's POST /api/agent/masters/upload.

This is the user-facing entry point for the FE file picker. Multipart
upload arrives here, we extract the manifest from the bytes via
slide_ir, then forward {manifest, sha256, b64} to db-service which
uploads bytes to blob and writes the row.

Tests run in-process via httpx ASGI transport. ``db_client.create_master``
is mocked because we don't want this layer's tests to require a live
db-service — that's covered by the integration smoke in 1.6.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


def _minimal_pptx_bytes() -> bytes:
    """Borrow the synthetic fixture builder from the slide_ir tests."""
    from tests.fixtures.synthetic import minimal_master_bytes

    return minimal_master_bytes()


@pytest_asyncio.fixture
async def http_client():
    """In-process httpx client with the auth dependency overridden."""
    import httpx
    from fastapi import FastAPI

    from app.dependencies import CurrentUser, get_current_user
    from app.agent.router import router as agent_router

    fake_user = CurrentUser(
        user_id="test-oid",
        email="t@local",
        display_name="t",
        azure_oid="test-oid",
    )

    app = FastAPI()
    app.include_router(agent_router, prefix="/api")

    async def _override():
        return fake_user

    app.dependency_overrides[get_current_user] = _override

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as c:
        yield c


async def test_upload_with_no_auth_header_returns_401(http_client):
    """The Authorization header is required — without it we cannot
    forward to db-service."""
    pptx = _minimal_pptx_bytes()
    files = {
        "file": (
            "test.pptx",
            pptx,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    }
    data = {"project_id": "proj-1"}
    r = await http_client.post("/api/agent/masters/upload", files=files, data=data)
    assert r.status_code == 401


async def test_upload_without_project_id_400(http_client):
    pptx = _minimal_pptx_bytes()
    files = {
        "file": (
            "t.pptx",
            pptx,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    }
    r = await http_client.post(
        "/api/agent/masters/upload",
        files=files,
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 400
    assert "project_id" in r.text.lower()


async def test_upload_wrong_extension_400(http_client):
    files = {"file": ("not-a-pptx.txt", b"hello", "text/plain")}
    r = await http_client.post(
        "/api/agent/masters/upload",
        files=files,
        data={"project_id": "p"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 400


async def test_upload_happy_path_extracts_and_forwards(http_client):
    """Full flow: minimal .pptx → manifest extracted → render layouts
    via sidecar (mocked) → db_client called with name, manifest,
    sha, b64, AND layouts list. We mock both the bridge and the
    renderer so the test stays in-process.
    """
    pptx = _minimal_pptx_bytes()

    fake_master = {
        "id": "fake-master",
        "name": "Test",
        "source_pptx_blob_url": "http://blob/x.pptx",
    }

    with (
        patch(
            "app.db.masters.create_master",
            new=AsyncMock(return_value=fake_master),
        ) as mock_create,
        patch(
            "app.services.pptx_renderer.PptxRenderer.render_layouts",
            new=AsyncMock(return_value={}),  # empty preview map = "no sidecar"
        ),
    ):
        files = {
            "file": (
                "deck.pptx",
                pptx,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        }
        r = await http_client.post(
            "/api/agent/masters/upload",
            files=files,
            data={"project_id": "proj-1"},
            headers={"Authorization": "Bearer xyz"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["master"]["id"] == "fake-master"
    assert "summary" in body
    assert body["summary"]["canvas"] == {"w": 1280, "h": 720}

    # Bridge was called with the right pieces. project_id is passed
    # positionally (along with the auth header), so it shows up in
    # call_args.args, not kwargs.
    assert mock_create.called
    args, kwargs = mock_create.call_args
    assert args[0] == "Bearer xyz"
    assert args[1] == "proj-1"
    assert kwargs["name"]  # falls back to "Imported master" for empty title
    assert "manifest" in kwargs and isinstance(kwargs["manifest"], dict)
    assert kwargs["source_sha256"]
    assert kwargs["source_pptx_b64"]  # base64 of the bytes

    # Phase 2.3d: layouts payload travels alongside the manifest
    layouts = kwargs.get("layouts")
    assert layouts is not None and isinstance(layouts, list)
    assert len(layouts) >= 1
    first = layouts[0]
    assert {"master_index", "layout_index", "name", "auto_kind", "position"} <= set(first.keys())
    # No previews because we mocked the renderer to return {}
    assert first.get("preview_b64") is None


async def test_upload_passes_renderer_previews_through(http_client):
    """When the sidecar (mocked) returns PNGs for some layouts, the
    bridge call carries each PNG as base64 on the matching layout
    payload. Layouts without previews carry preview_b64=None."""
    pptx = _minimal_pptx_bytes()

    # Pretend the sidecar rendered (0,0) and (0,2). (0,1) is missing.
    fake_pngs = {
        (0, 0): b"\x89PNG\r\n\x1a\n" + b"AAA" * 8,
        (0, 2): b"\x89PNG\r\n\x1a\n" + b"BBB" * 8,
    }

    with (
        patch(
            "app.db.masters.create_master",
            new=AsyncMock(return_value={"id": "x"}),
        ) as mock_create,
        patch(
            "app.services.pptx_renderer.PptxRenderer.render_layouts",
            new=AsyncMock(return_value=fake_pngs),
        ),
    ):
        r = await http_client.post(
            "/api/agent/masters/upload",
            files={
                "file": (
                    "d.pptx",
                    pptx,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
            data={"project_id": "proj"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200, r.text

    layouts = mock_create.call_args.kwargs["layouts"]
    by_idx = {(row["master_index"], row["layout_index"]): row for row in layouts}

    import base64

    assert by_idx[(0, 0)]["preview_b64"] == base64.b64encode(fake_pngs[(0, 0)]).decode()
    assert by_idx[(0, 2)]["preview_b64"] == base64.b64encode(fake_pngs[(0, 2)]).decode()
    # Layouts the renderer didn't cover get preview_b64=None — db-service
    # treats that as "skip blob upload".
    assert by_idx[(0, 1)]["preview_b64"] is None


async def test_upload_with_fonts_forwards_to_db_client(http_client):
    """Bundled fonts arrive as repeated multipart ``fonts`` fields. The
    backend reads each, infers family/weight/style from the filename,
    base64-encodes, and forwards to ``db_client.create_master(fonts=...)``."""
    pptx = _minimal_pptx_bytes()
    font_a = b"\x00\x01\x00\x00ttf-a-bytes" + b"A" * 200
    font_b = b"\x00\x01\x00\x00otf-b-bytes" + b"B" * 200

    with (
        patch(
            "app.db.masters.create_master",
            new=AsyncMock(return_value={"id": "fake"}),
        ) as mock_create,
        patch(
            "app.services.pptx_renderer.PptxRenderer.render_layouts",
            new=AsyncMock(return_value={}),
        ),
    ):
        # httpx multipart: pass ``files`` as a list to repeat field
        # names (the FastAPI form().getlist("fonts") path).
        r = await http_client.post(
            "/api/agent/masters/upload",
            files=[
                (
                    "file",
                    (
                        "d.pptx",
                        pptx,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    ),
                ),
                ("fonts", ("STCForward-Bold.ttf", font_a, "font/ttf")),
                ("fonts", ("Fund-LightItalic.otf", font_b, "font/otf")),
            ],
            data={"project_id": "proj"},
            headers={"Authorization": "Bearer xyz"},
        )

    assert r.status_code == 200, r.text
    fonts_kwarg = mock_create.call_args.kwargs.get("fonts")
    assert fonts_kwarg is not None and len(fonts_kwarg) == 2

    by_filename = {f["filename"]: f for f in fonts_kwarg}
    bold = by_filename["STCForward-Bold.ttf"]
    assert bold["weight"] == 700
    assert bold["style"] == "normal"
    assert bold["bytes_b64"]  # base64 of the file
    assert bold["source"] == "uploaded"

    italic = by_filename["Fund-LightItalic.otf"]
    assert italic["weight"] == 300
    assert italic["style"] == "italic"


async def test_upload_with_no_fonts_omits_field(http_client):
    """Empty fonts list → ``fonts`` kwarg is None (not []) so db-service
    leaves the column at its default rather than overwriting with []."""
    pptx = _minimal_pptx_bytes()

    with (
        patch(
            "app.db.masters.create_master",
            new=AsyncMock(return_value={"id": "fake"}),
        ) as mock_create,
        patch(
            "app.services.pptx_renderer.PptxRenderer.render_layouts",
            new=AsyncMock(return_value={}),
        ),
    ):
        r = await http_client.post(
            "/api/agent/masters/upload",
            files={
                "file": (
                    "d.pptx",
                    pptx,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
            data={"project_id": "proj"},
            headers={"Authorization": "Bearer x"},
        )

    assert r.status_code == 200
    assert mock_create.call_args.kwargs.get("fonts") is None


async def test_upload_with_bad_font_extension_returns_400(http_client):
    pptx = _minimal_pptx_bytes()
    with patch(
        "app.services.pptx_renderer.PptxRenderer.render_layouts",
        new=AsyncMock(return_value={}),
    ):
        r = await http_client.post(
            "/api/agent/masters/upload",
            files=[
                (
                    "file",
                    (
                        "d.pptx",
                        pptx,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    ),
                ),
                ("fonts", ("hostile.exe", b"\x4d\x5a", "application/octet-stream")),
            ],
            data={"project_id": "proj"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 400
    assert "extension" in r.text.lower()


async def test_upload_with_oversized_font_returns_413(http_client):
    pptx = _minimal_pptx_bytes()
    # Just over the 5 MB per-file cap.
    huge = b"\x00\x01\x00\x00" + b"A" * (5 * 1024 * 1024 + 1)
    with patch(
        "app.services.pptx_renderer.PptxRenderer.render_layouts",
        new=AsyncMock(return_value={}),
    ):
        r = await http_client.post(
            "/api/agent/masters/upload",
            files=[
                (
                    "file",
                    (
                        "d.pptx",
                        pptx,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    ),
                ),
                ("fonts", ("Big.ttf", huge, "font/ttf")),
            ],
            data={"project_id": "proj"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 413
    assert "cap" in r.text.lower() or "exceed" in r.text.lower()


async def test_upload_too_large_returns_413(http_client):
    """Payload over the cap returns 413 with a helpful message."""
    # Build a fake .pptx that's just oversized garbage; the size check
    # fires before extraction.
    big = b"PK" + b"\0" * (101 * 1024 * 1024)
    files = {
        "file": (
            "big.pptx",
            big,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    }
    r = await http_client.post(
        "/api/agent/masters/upload",
        files=files,
        data={"project_id": "p"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 413
