"""Phase 1.3 — masters router HTTP contract.

Drives the FastAPI app via ``httpx.AsyncClient`` against the in-process
ASGI handler. Auth + project-access are overridden through fixtures
so each test asserts the route's behaviour, not the auth layer's.

Endpoint surface tested:

| Method | Path                                    | What |
|--------|-----------------------------------------|------|
| GET    | /api/projects/{id}/masters              | list, newest first |
| POST   | /api/projects/{id}/masters              | upload manifest [+ b64 bytes] |
| GET    | /api/masters/{id}                       | single |
| GET    | /api/masters/{id}/pptx                  | stream original .pptx |
| POST   | /api/masters/{id}/activate              | set projects.active_master_id |
| DELETE | /api/masters/{id}                       | row + blob |

A POST that includes ``source_pptx_b64`` exercises the blob path
(via Azurite). A POST that omits it exercises the metadata-only
path (useful for tests / dry-runs / when the bytes were uploaded
out-of-band).
"""

from __future__ import annotations

import base64

import pytest

pytestmark = pytest.mark.asyncio


def _manifest(name: str = "Test") -> dict:
    return {
        "name": name,
        "canvas": {"w": 1280, "h": 720},
        "theme": {
            "fonts": {"major": "Georgia", "minor": "Arial"},
            "colors": {
                "text": "#1A1A1A",
                "bg": "#FFFFFF",
                "primary": "#A32020",
                "secondary": "#888888",
                "neutral": [],
            },
        },
        "safe_area": {"x": 80, "y": 175, "w": 1120, "h": 470},
        "chrome": [],
        "layouts": [],
    }


async def test_list_empty_project_returns_empty(http_client, tmp_project):
    r = await http_client.get(f"/api/projects/{tmp_project['id']}/masters")
    assert r.status_code == 200
    # Phase 2.0: response carries the project's active_master_id so the
    # FE can pin the right card without a second request. NULL when
    # nothing is active yet.
    assert r.json() == {"masters": [], "active_master_id": None}


async def test_list_response_carries_active_master_id_after_activate(http_client, tmp_project):
    """Activate flips active_master_id; the next list reflects it.

    Bug surface this guards against: FE clicks Activate, server updates
    projects.active_master_id, FE navigates away and back, FE list re-fetch
    must show which master is active. Today the response shape doesn't
    even include the field — this test fails until the response is
    extended.
    """
    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={"name": "Pin me", "manifest": _manifest("Pin me")},
    )
    mid = create.json()["id"]

    pre = await http_client.get(f"/api/projects/{tmp_project['id']}/masters")
    assert pre.json()["active_master_id"] is None

    activate = await http_client.post(f"/api/masters/{mid}/activate")
    assert activate.status_code == 200

    post = await http_client.get(f"/api/projects/{tmp_project['id']}/masters")
    assert post.json()["active_master_id"] == mid


async def test_post_master_with_layouts_persists_rows(http_client, tmp_project):
    """Phase 2.3c: POST master payload now accepts a ``layouts`` array.
    Each entry becomes a row in master_layouts via the upsert helper.
    Validates the row shape end-to-end through HTTP."""
    payload = {
        "name": "Multi-layout master",
        "manifest": _manifest("Multi-layout master"),
        "layouts": [
            {
                "master_index": 0,
                "layout_index": 0,
                "name": "Title Slide",
                "auto_kind": "title",
                "position": 0,
                "placeholders": [],
                "safe_area": None,
                "theme_index": 1,
                "font_major": "Georgia",
                "font_minor": "Arial",
                "palette": {"primary": "#A32020"},
                "preview_b64": None,
            },
            {
                "master_index": 0,
                "layout_index": 1,
                "name": "Two Columns",
                "auto_kind": "two_column",
                "position": 1,
                "placeholders": [{"role": "body", "x": 0, "y": 0, "w": 1, "h": 1}],
                "safe_area": {"x": 80, "y": 175, "w": 1120, "h": 470},
                "theme_index": 1,
                "font_major": "Georgia",
                "font_minor": "Arial",
                "palette": {"primary": "#A32020"},
                "preview_b64": None,
            },
        ],
    }
    r = await http_client.post(f"/api/projects/{tmp_project['id']}/masters", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    mid = body["id"]

    # GET the layouts via the new endpoint
    listing = await http_client.get(f"/api/masters/{mid}/layouts")
    assert listing.status_code == 200
    rows = listing.json()["layouts"]
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["Title Slide"]["auto_kind"] == "title"
    assert by_name["Two Columns"]["auto_kind"] == "two_column"
    assert by_name["Title Slide"]["enabled"] is True
    assert by_name["Title Slide"]["user_kind"] is None


async def test_patch_master_layout_updates_user_fields(http_client, tmp_project):
    """PATCH endpoint for the curation UI: edit user_kind, enabled,
    notes, position. Confirms three-state semantics."""
    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "P",
            "manifest": _manifest("P"),
            "layouts": [
                {
                    "master_index": 0,
                    "layout_index": 0,
                    "name": "L",
                    "auto_kind": "content",
                    "position": 0,
                    "placeholders": [],
                    "safe_area": None,
                    "theme_index": 1,
                    "font_major": None,
                    "font_minor": None,
                    "palette": {},
                    "preview_b64": None,
                }
            ],
        },
    )
    mid = create.json()["id"]
    layouts = (await http_client.get(f"/api/masters/{mid}/layouts")).json()["layouts"]
    lid = layouts[0]["id"]

    # Override kind, disable, add notes
    r = await http_client.patch(
        f"/api/master_layouts/{lid}",
        json={"user_kind": "cover", "enabled": False, "notes": "executive only"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_kind"] == "cover"
    assert body["enabled"] is False
    assert body["notes"] == "executive only"

    # Clear user_kind via empty-string sentinel
    r2 = await http_client.patch(f"/api/master_layouts/{lid}", json={"user_kind": ""})
    assert r2.json()["user_kind"] is None


async def test_post_master_layout_default_clears_others(http_client, tmp_project):
    """POST /api/master_layouts/{id}/default flips is_default; the
    transaction clears any existing default of the same kind on the
    same master."""
    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "D",
            "manifest": _manifest("D"),
            "layouts": [
                {
                    "master_index": 0,
                    "layout_index": 0,
                    "name": "A",
                    "auto_kind": "title",
                    "position": 0,
                    "placeholders": [],
                    "safe_area": None,
                    "theme_index": 1,
                    "font_major": None,
                    "font_minor": None,
                    "palette": {},
                    "preview_b64": None,
                },
                {
                    "master_index": 0,
                    "layout_index": 1,
                    "name": "B",
                    "auto_kind": "title",
                    "position": 1,
                    "placeholders": [],
                    "safe_area": None,
                    "theme_index": 1,
                    "font_major": None,
                    "font_minor": None,
                    "palette": {},
                    "preview_b64": None,
                },
            ],
        },
    )
    mid = create.json()["id"]
    rows = (await http_client.get(f"/api/masters/{mid}/layouts")).json()["layouts"]
    a_id = rows[0]["id"]
    b_id = rows[1]["id"]

    r1 = await http_client.post(f"/api/master_layouts/{a_id}/default")
    assert r1.status_code == 200, r1.text
    assert r1.json()["is_default"] is True

    r2 = await http_client.post(f"/api/master_layouts/{b_id}/default")
    assert r2.status_code == 200
    assert r2.json()["is_default"] is True

    # A should now be cleared
    listing = (await http_client.get(f"/api/masters/{mid}/layouts")).json()["layouts"]
    by_name = {r["name"]: r for r in listing}
    assert by_name["A"]["is_default"] is False
    assert by_name["B"]["is_default"] is True


async def test_post_master_with_layout_preview_b64_uploads_to_blob(http_client, tmp_project):
    """When a layout payload carries preview bytes (b64), the router
    uploads to blob and stores the URL on the row. Sidecar isn't
    needed — this layer just receives bytes from the backend."""
    import base64

    fake_png = b"\x89PNG\r\n\x1a\n" + b"X" * 256
    payload = {
        "name": "WithPreview",
        "manifest": _manifest("WithPreview"),
        "source_sha256": "preview-sha-12345",
        "source_pptx_b64": base64.b64encode(b"PK\x03\x04 fake pptx" + b"X" * 4000).decode(),
        "layouts": [
            {
                "master_index": 0,
                "layout_index": 0,
                "name": "L",
                "auto_kind": "title",
                "position": 0,
                "placeholders": [],
                "safe_area": None,
                "theme_index": 1,
                "font_major": None,
                "font_minor": None,
                "palette": {},
                "preview_b64": base64.b64encode(fake_png).decode(),
            }
        ],
    }
    r = await http_client.post(f"/api/projects/{tmp_project['id']}/masters", json=payload)
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    layouts = (await http_client.get(f"/api/masters/{mid}/layouts")).json()["layouts"]
    assert layouts[0]["preview_blob_url"] is not None
    assert "/layouts/" in layouts[0]["preview_blob_url"]
    assert "0_0.png" in layouts[0]["preview_blob_url"]


async def test_active_master_id_clears_when_active_master_deleted(http_client, tmp_project):
    """ON DELETE SET NULL on projects.active_master_id is wired in
    migration 0010; this test confirms the response reflects it."""
    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={"name": "Doomed", "manifest": _manifest("Doomed")},
    )
    mid = create.json()["id"]
    await http_client.post(f"/api/masters/{mid}/activate")

    # Confirm activated
    pre = await http_client.get(f"/api/projects/{tmp_project['id']}/masters")
    assert pre.json()["active_master_id"] == mid

    # Delete the master; the FK should null the pointer
    await http_client.delete(f"/api/masters/{mid}")
    post = await http_client.get(f"/api/projects/{tmp_project['id']}/masters")
    assert post.json()["active_master_id"] is None


async def test_post_metadata_only_creates_row(http_client, tmp_project):
    r = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "Bare",
            "manifest": _manifest("Bare"),
            "source_sha256": "barez" * 12 + "1234",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Bare"
    assert body["source_pptx_blob_url"] is None
    assert "id" in body


async def test_post_with_bytes_uploads_to_blob(http_client, tmp_project):
    """Smoke that bytes round-trip through blob storage. Requires
    Azurite running."""
    payload = b"PK\x03\x04 router-test-bytes" + b"X" * 256
    r = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "With bytes",
            "manifest": _manifest("With bytes"),
            "source_sha256": "router1" * 8 + "abcd",
            "source_pptx_b64": base64.b64encode(payload).decode("ascii"),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_pptx_blob_url"] is not None
    assert "masters/" in body["source_pptx_blob_url"]
    assert str(tmp_project["id"]) in body["source_pptx_blob_url"]

    # Fetch /pptx and confirm bytes match
    r2 = await http_client.get(f"/api/masters/{body['id']}/pptx")
    assert r2.status_code == 200
    assert r2.content == payload


async def test_post_with_fonts_uploads_to_blob(http_client, tmp_project):
    """Bundled brand fonts round-trip through blob; ``masters.fonts_assets``
    surfaces the metadata + URL on the response."""
    pptx = b"PK\x03\x04 fonts-test" + b"X" * 256
    font_a = b"\x00\x01\x00\x00ttf-a-bytes" + b"A" * 256  # ~270 bytes, well under cap
    font_b = b"\x00\x01\x00\x00otf-b-bytes" + b"B" * 256

    r = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "With fonts",
            "manifest": _manifest("With fonts"),
            "source_sha256": "fonts" * 12 + "abcd",
            "source_pptx_b64": base64.b64encode(pptx).decode("ascii"),
            "fonts": [
                {
                    "filename": "STCForward-Bold.ttf",
                    "family": "STC Forward",
                    "weight": 700,
                    "style": "normal",
                    "bytes_b64": base64.b64encode(font_a).decode("ascii"),
                    "source": "uploaded",
                },
                {
                    "filename": "Fund-LightItalic.otf",
                    "family": "Fund",
                    "weight": 300,
                    "style": "italic",
                    "bytes_b64": base64.b64encode(font_b).decode("ascii"),
                    "source": "uploaded",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["fonts_assets"], list)
    assert len(body["fonts_assets"]) == 2
    by_name = {f["filename"]: f for f in body["fonts_assets"]}
    assert by_name["STCForward-Bold.ttf"]["family"] == "STC Forward"
    assert by_name["STCForward-Bold.ttf"]["weight"] == 700
    assert by_name["Fund-LightItalic.otf"]["style"] == "italic"
    for f in body["fonts_assets"]:
        # Each blob URL points at the project's fonts/ prefix.
        assert "/fonts/" in f["blob_url"]
        assert str(tmp_project["id"]) in f["blob_url"]


async def test_post_with_fonts_rejects_bad_extension(http_client, tmp_project):
    r = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "Bad ext",
            "manifest": _manifest("Bad ext"),
            "source_sha256": "ext" * 22 + "ab",
            "source_pptx_b64": base64.b64encode(b"PK\x03\x04 anything").decode(),
            "fonts": [
                {
                    "filename": "not-a-font.exe",
                    "family": "Anything",
                    "weight": 400,
                    "style": "normal",
                    "bytes_b64": base64.b64encode(b"hostile").decode(),
                },
            ],
        },
    )
    assert r.status_code == 400
    assert "extension" in r.json()["detail"].lower()


async def test_delete_master_cleans_up_font_blobs(http_client, tmp_project):
    """Deleting the master should remove the source pptx, layout
    previews, AND bundled fonts under the SHA prefix. Otherwise
    re-uploading the same template after a delete leaves orphaned
    bytes in the storage account."""
    from app.storage import blob as blob_mod  # noqa: PLC0415

    pptx = b"PK\x03\x04 delete-test" + b"X" * 256
    font_a = b"\x00\x01\x00\x00ttf-a" + b"A" * 200
    font_b = b"\x00\x01\x00\x00ttf-b" + b"B" * 200
    sha = "delete1" * 8 + "abcd"

    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "delete-me",
            "manifest": _manifest("delete-me"),
            "source_sha256": sha,
            "source_pptx_b64": base64.b64encode(pptx).decode("ascii"),
            "fonts": [
                {
                    "filename": "Brand-Bold.ttf",
                    "family": "Brand",
                    "weight": 700,
                    "style": "normal",
                    "bytes_b64": base64.b64encode(font_a).decode("ascii"),
                    "source": "uploaded",
                },
                {
                    "filename": "Brand-Regular.ttf",
                    "family": "Brand",
                    "weight": 400,
                    "style": "normal",
                    "bytes_b64": base64.b64encode(font_b).decode("ascii"),
                    "source": "uploaded",
                },
            ],
        },
    )
    assert create.status_code == 200, create.text
    mid = create.json()["id"]

    # Confirm font blobs exist before delete by listing the SHA prefix.
    if blob_mod._service_client is None:  # noqa: SLF001
        pytest.skip("Blob storage not initialised — Azurite required")
    container_client = blob_mod._service_client.get_container_client(
        blob_mod._container_name,
    )
    prefix = f"{tmp_project['id']}/{sha}/"
    pre_names = [b.name for b in container_client.list_blobs(name_starts_with=prefix)]
    assert any(n.endswith("Brand-Bold.ttf") for n in pre_names), pre_names
    assert any(n.endswith("Brand-Regular.ttf") for n in pre_names), pre_names

    # Delete and confirm the prefix is empty.
    delete_res = await http_client.delete(f"/api/masters/{mid}")
    assert delete_res.status_code == 204

    post_names = [b.name for b in container_client.list_blobs(name_starts_with=prefix)]
    assert post_names == [], f"font blobs should be swept, got {post_names}"


async def test_post_with_fonts_requires_sha(http_client, tmp_project):
    """Font blob path is keyed on the source SHA so re-upload overwrites
    in place. Reject early when the SHA isn't provided."""
    r = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={
            "name": "No SHA",
            "manifest": _manifest("No SHA"),
            "fonts": [
                {
                    "filename": "Anything-Regular.ttf",
                    "family": "Anything",
                    "weight": 400,
                    "style": "normal",
                    "bytes_b64": base64.b64encode(b"\x00\x01\x00\x00").decode(),
                },
            ],
        },
    )
    assert r.status_code == 400
    assert "source_sha256" in r.json()["detail"]


async def test_get_single_master(http_client, tmp_project):
    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={"name": "G", "manifest": _manifest("G")},
    )
    mid = create.json()["id"]
    r = await http_client.get(f"/api/masters/{mid}")
    assert r.status_code == 200
    assert r.json()["name"] == "G"


async def test_get_unknown_master_404(http_client):
    import uuid

    r = await http_client.get(f"/api/masters/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_list_orders_newest_first(http_client, tmp_project):
    names = ["alpha", "beta", "gamma"]
    for n in names:
        r = await http_client.post(
            f"/api/projects/{tmp_project['id']}/masters",
            json={"name": n, "manifest": _manifest(n)},
        )
        assert r.status_code == 200
    r = await http_client.get(f"/api/projects/{tmp_project['id']}/masters")
    listed = r.json()["masters"]
    # newest-first => names reversed
    assert [m["name"] for m in listed] == list(reversed(names))


async def test_activate_sets_active_master_id(http_client, tmp_project, pool):
    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={"name": "A", "manifest": _manifest("A")},
    )
    mid = create.json()["id"]
    r = await http_client.post(f"/api/masters/{mid}/activate")
    assert r.status_code == 200, r.text

    active = await pool.fetchval(
        "SELECT active_master_id::text FROM projects WHERE id = $1",
        tmp_project["id"],
    )
    assert active == mid


async def test_delete_removes_row(http_client, tmp_project):
    create = await http_client.post(
        f"/api/projects/{tmp_project['id']}/masters",
        json={"name": "to-delete", "manifest": _manifest()},
    )
    mid = create.json()["id"]
    r = await http_client.delete(f"/api/masters/{mid}")
    assert r.status_code == 204
    r2 = await http_client.get(f"/api/masters/{mid}")
    assert r2.status_code == 404
