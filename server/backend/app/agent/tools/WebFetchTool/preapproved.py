"""
Preapproved hosts for WebFetchTool.

Port of src/tools/WebFetchTool/preapproved.ts (166 lines in source).

The source ships a curated list of well-known doc/reference sites that
bypass the permission prompt (Anthropic docs, MDN, Python docs, etc.).
v1 keeps the structure but ships an empty list — domain allowlisting is
a Phase 4 hooks/permission concern. Until then, all hosts go through the
normal permission flow (default-allow per v1).
"""

from __future__ import annotations

# Phase 4: populate from a curated allowlist or settings.json
# {hostname: optional path-prefix list}
_PREAPPROVED_HOSTS: dict[str, list[str] | None] = {
    # Examples (uncomment to enable):
    # "docs.anthropic.com": None,
    # "developer.mozilla.org": None,
    # "docs.python.org": None,
}


def is_preapproved_host(hostname: str, pathname: str = "") -> bool:
    """
    Return True if the host (and optionally path-prefix) is in the
    preapproved allowlist. v1 always returns False (empty list).
    """
    if hostname not in _PREAPPROVED_HOSTS:
        return False
    paths = _PREAPPROVED_HOSTS[hostname]
    if paths is None:
        return True
    return any(pathname.startswith(p) for p in paths)


def is_preapproved_url(url: str) -> bool:
    """Convenience wrapper that parses the URL first."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return is_preapproved_host(parsed.hostname or "", parsed.path or "")
    except Exception:
        return False
