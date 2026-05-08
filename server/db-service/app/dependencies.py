"""Azure AD JWT validation — shared by all routers."""

from __future__ import annotations

import logging
import os
import ssl
import threading
from dataclasses import dataclass

import certifi
import jwt
from fastapi import Header, HTTPException

from app.config import get_settings
from app.db import Pool, get_pool
from app.db.users.repository import get_or_create_user

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str
    display_name: str
    azure_oid: str | None = None


_jwks_client: jwt.PyJWKClient | None = None
_jwks_lock = threading.Lock()


def _jwks_ssl_context() -> ssl.SSLContext:
    """Use a CA bundle that works with local Python installs behind TLS inspection."""
    cafile = os.getenv("AZURE_CACERT_PATH") or os.getenv("SSL_CERT_FILE") or certifi.where()
    return ssl.create_default_context(cafile=cafile)


def _get_jwks_client(tenant_id: str) -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                jwks_url = (
                    f"https://login.microsoftonline.com/{tenant_id}"
                    "/discovery/v2.0/keys"
                )
                _jwks_client = jwt.PyJWKClient(
                    jwks_url,
                    cache_keys=True,
                    ssl_context=_jwks_ssl_context(),
                )
    return _jwks_client


def _validate_token(
    authorization: str | None,
    client_id: str,
    tenant_id: str,
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization[7:]

    try:
        jwks_client = _get_jwks_client(tenant_id)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as exc:
        log.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")

    oid = claims.get("oid") or claims.get("sub")
    email = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or f"{oid}@azure.local"
    )
    display_name = claims.get("name") or email

    return CurrentUser(
        user_id=oid,
        email=email,
        display_name=display_name,
        azure_oid=oid,
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    settings = get_settings()
    client_id = settings.azure_ad.client_id
    tenant_id = settings.azure_ad.tenant_id

    if not client_id or not tenant_id:
        return CurrentUser(
            user_id="anonymous",
            email="anonymous@dev.local",
            display_name="Anonymous (dev)",
        )

    user = _validate_token(authorization, client_id, tenant_id)
    pool: Pool = await get_pool()
    await get_or_create_user(
        pool,
        azure_oid=user.azure_oid or user.user_id,
        email=user.email,
        display_name=user.display_name,
    )
    return user


async def get_admin_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    settings = get_settings()
    admin_client_id = settings.azure_ad.admin_client_id
    tenant_id = settings.azure_ad.tenant_id

    if not admin_client_id or not tenant_id:
        raise HTTPException(status_code=503, detail="Admin authentication is not configured")

    return _validate_token(authorization, admin_client_id, tenant_id)
