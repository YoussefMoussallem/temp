"""FastAPI dependencies — Azure AD JWT validation.

What this does
--------------
MSAL on the frontend hands us a signed Azure AD ID token in the
``Authorization: Bearer <jwt>`` header. These dependencies validate
that token against Microsoft's public JWKS (keys rotated by Microsoft,
fetched + cached by PyJWT) and return a ``CurrentUser`` the rest of
the app can trust.

How to use
----------
Inject into any FastAPI handler that needs an authenticated caller::

    from fastapi import Depends
    from app.dependencies import get_current_user, CurrentUser

    @router.get("/me")
    async def me(user: CurrentUser = Depends(get_current_user)):
        return {"id": user.user_id, "email": user.email}

Two audiences
-------------
The project ships two Azure AD app registrations:

  * ``get_current_user`` - the normal end-user app (``azure_ad.client_id``).
    In dev, when ``AZURE_CLIENT_ID`` is unset, this returns an
    "anonymous" user so the backend is usable without Azure.
  * ``get_admin_user`` - the separate admin app
    (``azure_ad.admin_client_id``). No dev fallback: if admin auth is
    unconfigured we 503, because silently anon-ing an admin endpoint
    would be a dangerous default.

A token valid for the user app is NOT valid for the admin app (different
``aud`` claim), so routes guarded by ``get_admin_user`` can't be hit
with a plain user token.
"""

from __future__ import annotations

import os
import ssl
import threading
from dataclasses import dataclass

import certifi
import jwt
from fastapi import Header, HTTPException

from app.config import get_settings
from app_logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class CurrentUser:
    """Identity passed around by request handlers.

    Fields:
        user_id:      Stable per-user identifier - Azure ``oid`` when
                      available, otherwise ``sub``. Use this as the FK
                      into our own users table.
        email:        Best-effort email - claims vary by tenant config,
                      so we try ``preferred_username`` -> ``email`` ->
                      ``upn`` and fall back to "".
        display_name: Human-readable name (``name`` claim) or email.
        azure_oid:    Raw Azure object ID. Same as ``user_id`` today,
                      kept as a distinct field so call sites that
                      specifically need the Azure OID don't break if we
                      ever change how ``user_id`` is derived.
    """
    user_id: str
    email: str
    display_name: str
    azure_oid: str | None = None


# ── JWKS cache ────────────────────────────────────────────────────────
# Microsoft rotates signing keys; the PyJWKClient fetches + caches them
# so we don't hit Microsoft on every request. One shared client per
# process is enough - the tenant_id is fixed for the app's lifetime, so
# we don't key the cache by tenant.

_jwks_client: jwt.PyJWKClient | None = None
_jwks_lock = threading.Lock()


def _jwks_ssl_context() -> ssl.SSLContext:
    """Build the SSL context used for fetching Microsoft's JWKS.

    Cert resolution order:
      1. ``$SSL_CERT_FILE`` — system-level Python convention; respected
         here for parity with installs that already point Python at a
         custom bundle this way.
      2. ``certifi.where()`` — bundled CA roots, the default for direct
         internet access.
    """
    cafile = os.getenv("SSL_CERT_FILE") or certifi.where()
    return ssl.create_default_context(cafile=cafile)


def _get_jwks_client() -> jwt.PyJWKClient:
    """Lazily build the process-wide JWKS client (double-checked locking).

    The client is keyed only by ``tenant_id`` from settings, which is
    fixed for the lifetime of the process. Both the user-app and admin-
    app audiences live in the same tenant, so one client serves both.
    """
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                tenant_id = get_settings().azure_ad.tenant_id
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


# ── Shared token validation ──────────────────────────────────────────

def _validate_token(
    authorization: str | None,
    client_id: str,
    tenant_id: str,
) -> CurrentUser:
    """Parse + verify a bearer token against Azure AD.

    Validation steps (all must pass, order matters):
      1. Header must be ``Bearer <token>`` - otherwise 401.
      2. Pick the right signing key from Microsoft's JWKS by the token's
         ``kid`` header.
      3. Verify RS256 signature + standard claims:
           - ``aud`` must equal ``client_id`` (prevents tokens issued
             for a different app from being accepted here - this is
             what separates the user app from the admin app).
           - ``iss`` must be our tenant's v2.0 issuer URL.
           - ``exp``, ``iss``, ``aud``, ``sub`` must all be present.
      4. If any of the above fail, raise 401 with a generic message -
         we log the real reason but don't leak it to the client.

    Returns a ``CurrentUser`` built from the token's claims. Never
    trust header values beyond the token itself - the claims below
    come from a signature-verified payload.
    """
    # RFC 6750 says the scheme is case-insensitive ("Bearer", "bearer",
    # "BEARER" all valid). ``partition`` also tolerates extra whitespace
    # in the token portion without us having to maintain a magic offset.
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            options={"require": ["exp", "iss", "aud", "sub"]},
            # 60s leeway absorbs small clock skew between the caller's
            # machine and Azure. Microsoft's own SDKs use the same value.
            leeway=60,
        )
    except jwt.ExpiredSignatureError:
        # Split out so the frontend can distinguish "token expired,
        # silently refresh" from "token fundamentally bad, force re-login".
        # ``from None`` suppresses the PyJWT chain in any logged traceback.
        raise HTTPException(status_code=401, detail="Token has expired") from None
    except jwt.InvalidTokenError as exc:
        # Log the underlying reason (kid mismatch, bad aud, etc.) but
        # return a generic 401 - attackers don't need our diagnostics.
        log.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token") from None

    # ``oid`` is the stable Azure object ID; fall back to ``sub`` for
    # tokens where ``oid`` isn't issued (personal MS accounts, some
    # guest scenarios).
    oid = claims.get("oid") or claims.get("sub")
    # Email claim naming is inconsistent across tenants / account types,
    # so we try several in order of preference.
    email = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or ""
    )
    display_name = claims.get("name") or email

    return CurrentUser(
        user_id=oid,
        email=email,
        display_name=display_name,
        azure_oid=oid,
    )


# ── Dependencies ─────────────────────────────────────────────────────

async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """FastAPI dependency: validate the ID token for the user-facing app.

    Dev fallback: if ``azure_ad.client_id`` or ``azure_ad.tenant_id`` is
    unset, skip validation entirely and return a hard-coded anonymous
    user. This lets new contributors run the backend without an Azure
    setup. Do NOT deploy with these unset.
    """
    settings = get_settings()
    client_id = settings.azure_ad.client_id
    tenant_id = settings.azure_ad.tenant_id

    if not client_id or not tenant_id:
        return CurrentUser(
            user_id="anonymous",
            email="anonymous@dev.local",
            display_name="Anonymous (dev)",
        )

    return _validate_token(authorization, client_id, tenant_id)


async def get_admin_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """FastAPI dependency: validate the ID token for the admin app.

    No dev fallback on purpose - an unconfigured admin surface should
    be closed, not silently open. If ``admin_client_id`` is missing we
    return 503 so the admin UI shows "service unavailable" rather than
    handing an anonymous user admin rights.
    """
    settings = get_settings()
    admin_client_id = settings.azure_ad.admin_client_id
    tenant_id = settings.azure_ad.tenant_id

    if not admin_client_id or not tenant_id:
        raise HTTPException(
            status_code=503,
            detail="Admin authentication is not configured",
        )

    return _validate_token(authorization, admin_client_id, tenant_id)
