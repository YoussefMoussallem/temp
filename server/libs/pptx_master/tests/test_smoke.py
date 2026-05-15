"""Smoke test — verify the package imports and exposes its public surface.

Real extraction tests live in ``server/backend/tests/test_master_extractor.py``
because they depend on synthetic + private .pptx fixtures and syrupy
snapshots that are part of the backend's test infrastructure. This file
just guards against accidental breakage of the package's import path.
"""

from __future__ import annotations


def test_public_api_imports():
    from pptx_master import (
        MasterManifest,
        MasterEntry,
        LayoutDescriptor,
        MasterCanvas,
        MasterTheme,
        ThemeEntry,
        Scene,
        TextElement,
        extract_master_from_pptx,
    )

    assert callable(extract_master_from_pptx)
    assert MasterManifest is not None
    assert MasterEntry is not None
    assert LayoutDescriptor is not None
    assert MasterCanvas is not None
    assert MasterTheme is not None
    assert ThemeEntry is not None
    assert Scene is not None
    assert TextElement is not None
