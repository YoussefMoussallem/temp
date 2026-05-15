"""Storage clients — Azure Blob today, possibly more later.

The db-service is the *only* service in the repo that talks to durable
storage (Postgres, Redis, Blob). This package keeps the blob client
behind a small surface so callers (repositories, routers) don't import
the SDK directly.
"""

from .blob import (
    delete_master_derived_assets,
    delete_master_pptx,
    fetch_master_pptx,
    init_blob_client,
    is_blob_enabled,
    upload_layout_preview,
    upload_master_font,
    upload_master_pptx,
)

__all__ = [
    "delete_master_derived_assets",
    "delete_master_pptx",
    "fetch_master_pptx",
    "init_blob_client",
    "is_blob_enabled",
    "upload_layout_preview",
    "upload_master_font",
    "upload_master_pptx",
]
