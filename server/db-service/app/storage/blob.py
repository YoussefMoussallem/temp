"""Azure Blob Storage for master PPTX bytes.

Three modes, picked from environment at startup:

* **Azurite (local dev)** — set ``AZURE_BLOB_CONNECTION_STRING`` to
  Azurite's connection string. The blob URL stored in Postgres includes
  the local endpoint and is openable from any service in the docker
  network.
* **Azure cloud (managed identity)** — set ``AZURE_BLOB_ACCOUNT_URL``
  to ``https://<account>.blob.core.windows.net`` (no SAS, no key). The
  client uses ``DefaultAzureCredential``; the db-service container
  must have ``Storage Blob Data Contributor`` on the masters container.
* **Disabled** — neither env var set. ``is_blob_enabled()`` returns
  ``False`` and callers fall back to the legacy ``masters.source_pptx``
  BYTEA column. Useful for running the test suite without Azurite.

The SDK's sync client is wrapped in ``asyncio.to_thread`` so the rest of
the service stays async without pulling in the aio extras (which add
``aiohttp`` to the dep tree). Blob operations are infrequent — at most
once per master upload and once per export — so the thread hop cost is
negligible.

Container name is configurable (``AZURE_BLOB_MASTERS_CONTAINER``,
default ``masters``). Blobs are addressed as
``{project_id}/{sha256-or-uuid}.pptx`` so re-uploading the same template
to the same project overwrites in place — matches the Postgres
``(project_id, source_sha256)`` upsert behaviour.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any
from urllib.parse import urlparse

from app_logger import get_logger

log = get_logger(__name__)

_DEFAULT_CONTAINER = "masters"
_PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

_lock = threading.Lock()
_service_client: Any | None = None
_container_name: str = _DEFAULT_CONTAINER
_account_url: str | None = None  # for constructing public blob URLs


def init_blob_client() -> None:
    """Initialise the global blob client from env. Call once at startup.

    Idempotent — safe to call multiple times. If neither connection
    string nor account URL is set the function returns silently and
    ``is_blob_enabled()`` stays ``False``.
    """
    global _service_client, _container_name, _account_url

    with _lock:
        if _service_client is not None:
            return

        # The service-wide .env is loaded into a Pydantic Settings class
        # which doesn't propagate to ``os.environ``. Load it explicitly
        # here so AZURE_BLOB_* vars from the .env are visible without
        # forcing every caller to pre-export them.
        try:
            from dotenv import load_dotenv  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415

            env_path = Path(__file__).resolve().parents[2] / ".env"
            if env_path.is_file():
                load_dotenv(env_path, override=False)
        except Exception:
            # python-dotenv missing or .env unreadable — fall through to
            # whatever's already in os.environ. Not worth crashing over.
            pass

        conn_str = os.environ.get("AZURE_BLOB_CONNECTION_STRING")
        account_url = os.environ.get("AZURE_BLOB_ACCOUNT_URL")
        container = os.environ.get("AZURE_BLOB_MASTERS_CONTAINER", _DEFAULT_CONTAINER)

        if not conn_str and not account_url:
            log.info(
                "Blob storage disabled (no AZURE_BLOB_CONNECTION_STRING or "
                "AZURE_BLOB_ACCOUNT_URL set); masters will use BYTEA column."
            )
            return

        # Imports are deferred so a service that doesn't use blob (e.g.
        # the test runner without Azurite) doesn't pay the SDK import
        # cost or fail if the package isn't installed in some
        # constrained environment.
        from azure.storage.blob import BlobServiceClient  # noqa: PLC0415

        if conn_str:
            client = BlobServiceClient.from_connection_string(conn_str)
            _account_url = client.url.rstrip("/")
            log.info("Blob storage enabled via connection string (Azurite/dev mode).")
        else:
            from azure.identity import DefaultAzureCredential  # noqa: PLC0415

            cred = DefaultAzureCredential()
            client = BlobServiceClient(account_url=account_url, credential=cred)
            _account_url = account_url.rstrip("/") if account_url else None
            log.info("Blob storage enabled via managed identity (cloud mode).")

        # Best-effort container create. Azurite needs this; in cloud
        # the container is created by Bicep but the create call is
        # idempotent so duplicating the work is fine.
        #
        # Azurite-only: enable public-blob access so the browser can
        # GET preview PNG URLs directly without SAS signing. We detect
        # Azurite via the connection-string path (the only mode that
        # uses the well-known dev account); cloud deployments leave
        # access private and rely on SAS or a proxy layer.
        try:
            if conn_str:
                client.create_container(container, public_access="blob")
            else:
                client.create_container(container)
            log.info("Created blob container: %s", container)
        except Exception:
            # Container already exists or we don't have create permission
            # (cloud + bicep-managed) — both expected paths. Log at debug
            # only so the startup log stays clean.
            log.debug("Container %s already exists or not creatable", container)
            # If we're on Azurite and the container already existed
            # (from a prior run before the public_access flag was set),
            # flip its access policy now so old containers also serve
            # blobs publicly. Best-effort.
            if conn_str:
                try:
                    client.get_container_client(container).set_container_access_policy(
                        signed_identifiers={},
                        public_access="blob",
                    )
                    log.info("Set Azurite container %s to public-blob access", container)
                except Exception:
                    log.debug("Could not flip container access on existing container")

        _service_client = client
        _container_name = container


def is_blob_enabled() -> bool:
    """``True`` once ``init_blob_client`` has wired a real client."""
    return _service_client is not None


def _blob_path(project_id: str, sha256: str | None, master_id: str) -> str:
    """Stable blob path for a master.

    Prefers the SHA so re-uploads of the same file land on the same
    blob (idempotent). Falls back to the master row's UUID when the
    caller didn't compute a SHA.
    """
    name = sha256 or master_id
    return f"{project_id}/{name}.pptx"


_PNG_CONTENT_TYPE = "image/png"

# Brand fonts uploaded alongside a master. The Azure SDK leaves the
# Content-Type empty when missing; setting it explicitly lets the
# browser fetch the file with a sane MIME hint when we eventually
# serve it through @font-face.
_FONT_CONTENT_TYPES = {
    "ttf": "font/ttf",
    "otf": "font/otf",
    "woff": "font/woff",
    "woff2": "font/woff2",
}


async def upload_master_font(
    project_id: str,
    sha256: str,
    filename: str,
    data: bytes,
) -> str:
    """Upload one bundled brand font and return its blob URL.

    Path is ``{project_id}/{sha256}/fonts/{filename}`` so re-uploading
    the same template (same source SHA) overwrites the existing font
    in place. Filename is preserved end-to-end — frontend uses it as
    the human-meaningful identifier in @font-face down the line.

    The caller is responsible for validating the filename (allowlist
    extensions, no path separators) before calling this.
    """
    if _service_client is None:
        raise RuntimeError("Blob storage not initialised; check init_blob_client().")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = _FONT_CONTENT_TYPES.get(ext, "application/octet-stream")
    container = _container_name
    path = f"{project_id}/{sha256}/fonts/{filename}"

    def _upload() -> str:
        from azure.storage.blob import ContentSettings  # noqa: PLC0415

        blob_client = _service_client.get_blob_client(container, path)
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        return blob_client.url

    return await asyncio.to_thread(_upload)


async def upload_layout_preview(
    project_id: str,
    sha256: str,
    master_index: int,
    layout_index: int,
    data: bytes,
) -> str:
    """Upload a layout preview PNG and return its blob URL.

    Path is ``{project_id}/{sha256}/layouts/{m_idx}_{l_idx}.png`` so
    re-rendering the same template (same source SHA) overwrites the
    existing PNG in place — keeps the storage account from
    accumulating versions on re-upload.
    """
    if _service_client is None:
        raise RuntimeError("Blob storage not initialised; check init_blob_client().")

    container = _container_name
    path = f"{project_id}/{sha256}/layouts/{master_index}_{layout_index}.png"

    def _upload() -> str:
        from azure.storage.blob import ContentSettings  # noqa: PLC0415

        blob_client = _service_client.get_blob_client(container, path)
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=_PNG_CONTENT_TYPE),
        )
        return blob_client.url

    return await asyncio.to_thread(_upload)


async def upload_master_pptx(
    project_id: str,
    master_id: str,
    sha256: str | None,
    data: bytes,
) -> str:
    """Upload bytes and return the canonical blob URL.

    Overwrites any existing blob at the same path — matches the
    Postgres upsert semantics. Returns the URL exactly as it should
    be stored in ``masters.source_pptx_blob_url``.
    """
    if _service_client is None:
        raise RuntimeError("Blob storage not initialised; check init_blob_client().")

    path = _blob_path(project_id, sha256, master_id)
    container = _container_name

    def _upload() -> str:
        from azure.storage.blob import ContentSettings  # noqa: PLC0415

        blob_client = _service_client.get_blob_client(container, path)
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=_PPTX_CONTENT_TYPE),
        )
        return blob_client.url

    return await asyncio.to_thread(_upload)


async def fetch_master_pptx(blob_url: str) -> bytes:
    """Download bytes for a previously uploaded master.

    The URL must be one produced by ``upload_master_pptx`` (same
    account + container as the live client). We re-derive the blob
    path from the URL rather than trusting it as-is, so a stale URL
    pointing at a different account triggers a clean error rather
    than a confused fetch.
    """
    if _service_client is None:
        raise RuntimeError("Blob storage not initialised; check init_blob_client().")

    container, path = _parse_blob_url(blob_url)
    if container != _container_name:
        raise ValueError(
            f"Blob URL points at container {container!r}, expected {_container_name!r}"
        )

    def _download() -> bytes:
        blob_client = _service_client.get_blob_client(container, path)
        downloader = blob_client.download_blob()
        return downloader.readall()

    return await asyncio.to_thread(_download)


async def delete_master_pptx(blob_url: str) -> None:
    """Best-effort delete. A 404 is not an error — the deck-level
    delete path may run after the blob was already cleaned up by an
    earlier retry."""
    if _service_client is None:
        return

    try:
        container, path = _parse_blob_url(blob_url)
    except ValueError:
        log.warning("delete_master_pptx: unparseable URL %s", blob_url)
        return

    def _delete() -> None:
        try:
            blob_client = _service_client.get_blob_client(container, path)
            blob_client.delete_blob()
        except Exception:  # noqa: BLE001
            # Already gone, or transient. Don't fail the row delete.
            log.debug("Blob delete failed for %s", path, exc_info=True)

    await asyncio.to_thread(_delete)


async def delete_master_derived_assets(project_id: str, sha256: str) -> None:
    """Sweep every derived asset for a master — layout previews under
    ``{project_id}/{sha256}/layouts/`` and bundled brand fonts under
    ``{project_id}/{sha256}/fonts/``.

    The source ``.pptx`` is at ``{project_id}/{sha256}.pptx`` (one level
    up) and is deleted separately by ``delete_master_pptx``. We only
    clean the derived directory here so a delete of one master doesn't
    accidentally wipe a sibling master's bytes.

    Best-effort: a missing prefix or transient list/delete failure
    logs a warning but doesn't fail the row delete. An orphaned blob
    is annoying but not fatal.
    """
    if _service_client is None or not sha256:
        return

    container = _container_name
    prefix = f"{project_id}/{sha256}/"

    def _sweep() -> int:
        try:
            container_client = _service_client.get_container_client(container)
            removed = 0
            # list_blobs is iterator-style; we materialise the names
            # before deleting so we don't mutate the listing under us.
            names = [b.name for b in container_client.list_blobs(name_starts_with=prefix)]
            for name in names:
                try:
                    container_client.delete_blob(name)
                    removed += 1
                except Exception:  # noqa: BLE001
                    log.debug("Blob delete failed for %s", name, exc_info=True)
            return removed
        except Exception:  # noqa: BLE001
            log.warning(
                "delete_master_derived_assets: sweep failed for prefix %s",
                prefix,
                exc_info=True,
            )
            return 0

    removed = await asyncio.to_thread(_sweep)
    if removed:
        log.info(
            "delete_master_derived_assets: removed %d blobs under %s",
            removed,
            prefix,
        )


def _parse_blob_url(blob_url: str) -> tuple[str, str]:
    """Return ``(container, blob_path)`` from a Blob Service URL.

    Accepts both Azurite-style (``http://127.0.0.1:10000/devstoreaccount1/<container>/<path>``)
    and cloud-style (``https://<account>.blob.core.windows.net/<container>/<path>``)
    URLs. The Azurite path includes the account name as the first
    segment, so we use the configured container name to find where
    the path starts rather than assuming a fixed segment count.
    """
    parsed = urlparse(blob_url)
    parts = [p for p in parsed.path.split("/") if p]
    # Find the container segment; it's whichever segment matches our
    # configured container name. This handles Azurite (account/<container>/...)
    # and cloud (<container>/...) uniformly.
    for i, seg in enumerate(parts):
        if seg == _container_name:
            return _container_name, "/".join(parts[i + 1 :])
    raise ValueError(f"Container {_container_name!r} not found in URL: {blob_url}")
