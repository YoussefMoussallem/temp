"""Phase 1.2 — Azure Blob Storage module.

Two layers tested:

1. **Pure helpers** — URL parsing and blob-path generation. No I/O.
   These run without Azurite or any cloud connection.

2. **Round-trip** — upload → fetch → delete against a real Azurite
   container. Skipped cleanly when the SDK can't reach Azurite, so
   a checkout without ``docker compose up`` doesn't fail the suite.

We stay clear of mocking the Azure SDK in unit tests — its surface is
deep and any mock would lie about behaviour somewhere. Real Azurite
is fast (sub-100ms per call) and the tests are lean.
"""

from __future__ import annotations

import os

import pytest

from app.storage import blob as blob_mod


@pytest.fixture(scope="session", autouse=True)
def _force_dev_blob_env() -> None:
    """Ensure the SDK is configured against Azurite for the test
    process. Even if a developer's .env points at cloud, tests must
    not write to a real storage account.
    """
    os.environ["AZURE_BLOB_CONNECTION_STRING"] = "UseDevelopmentStorage=true"
    os.environ.pop("AZURE_BLOB_ACCOUNT_URL", None)
    blob_mod._service_client = None  # noqa: SLF001 — re-init for the test
    blob_mod.init_blob_client()


# ── Pure-helper tests ────────────────────────────────────────────────


def test_blob_path_uses_sha_when_present() -> None:
    """SHA-keyed path makes re-uploads land on the same blob — same
    file should never produce two paths."""
    path = blob_mod._blob_path(
        project_id="proj-uuid",
        sha256="abc" * 21 + "x",  # 64 chars
        master_id="m-1",
    )
    assert path == "proj-uuid/" + ("abc" * 21 + "x") + ".pptx"


def test_blob_path_falls_back_to_master_id_without_sha() -> None:
    """Callers can omit SHA (we don't enforce it). Master id keeps the
    path stable across that one row."""
    path = blob_mod._blob_path(project_id="p", sha256=None, master_id="m-1")
    assert path == "p/m-1.pptx"


def test_parse_url_azurite_form() -> None:
    url = "http://127.0.0.1:10000/devstoreaccount1/masters/proj/sha.pptx"
    container, path = blob_mod._parse_blob_url(url)
    assert container == "masters"
    assert path == "proj/sha.pptx"


def test_parse_url_cloud_form() -> None:
    url = "https://sttempslidemastersdev.blob.core.windows.net/masters/p/s.pptx"
    container, path = blob_mod._parse_blob_url(url)
    assert container == "masters"
    assert path == "p/s.pptx"


def test_parse_url_rejects_wrong_container() -> None:
    """Defensive: a URL pointing at a *different* container should not
    silently parse to ours. Catches stale URLs after a container
    migration."""
    with pytest.raises(ValueError):
        blob_mod._parse_blob_url("https://account.blob.core.windows.net/logs/proj/file.pptx")


# ── Round-trip tests against Azurite ─────────────────────────────────


def _azurite_reachable() -> bool:
    import socket

    try:
        sock = socket.create_connection(("127.0.0.1", 10000), timeout=0.5)
        sock.close()
        return True
    except OSError:
        return False


pytestmark_azurite = pytest.mark.skipif(
    not _azurite_reachable(),
    reason="Azurite not reachable on 127.0.0.1:10000 (run `docker compose up -d azurite`)",
)


@pytestmark_azurite
async def test_upload_and_fetch_round_trip() -> None:
    payload = b"PK\x03\x04 fake pptx round-trip " + b"X" * 4000
    url = await blob_mod.upload_master_pptx(
        project_id="pytest-proj",
        master_id="pytest-master",
        sha256="roundtrip",
        data=payload,
    )
    assert url
    fetched = await blob_mod.fetch_master_pptx(url)
    assert fetched == payload
    # Cleanup so Azurite doesn't accumulate test artefacts.
    await blob_mod.delete_master_pptx(url)


@pytestmark_azurite
async def test_re_upload_overwrites_in_place() -> None:
    """Same SHA → same path → second upload overwrites without
    error. Mirrors the Postgres upsert semantics."""
    sha = "overwrite-test"
    a = await blob_mod.upload_master_pptx(
        project_id="pytest-proj",
        master_id="m",
        sha256=sha,
        data=b"first",
    )
    b = await blob_mod.upload_master_pptx(
        project_id="pytest-proj",
        master_id="m",
        sha256=sha,
        data=b"second",
    )
    assert a == b  # same path
    assert (await blob_mod.fetch_master_pptx(a)) == b"second"
    await blob_mod.delete_master_pptx(a)


@pytestmark_azurite
async def test_delete_then_fetch_404s() -> None:
    """Sanity: delete actually removes the blob. (Catches a regression
    where the SDK silently no-ops the delete call.)"""
    url = await blob_mod.upload_master_pptx(
        project_id="pytest-proj",
        master_id="ephemeral",
        sha256=None,
        data=b"bye",
    )
    await blob_mod.delete_master_pptx(url)
    from azure.core.exceptions import ResourceNotFoundError

    with pytest.raises(ResourceNotFoundError):
        await blob_mod.fetch_master_pptx(url)
