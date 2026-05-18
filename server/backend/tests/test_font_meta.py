"""Filename → font metadata inference.

The backend's masters/upload route uses ``_infer_font_meta`` to derive
``family``, ``weight``, and ``style`` from a font filename (so the FE
doesn't have to compute it). The heuristics aren't perfect — they're
designed to give the right answer for vendor-typical naming conventions
(``Family-Weight[Italic].ext``) and gracefully fall back to weight=400
/ style=normal otherwise.
"""

from __future__ import annotations

import pytest

from app.agent.routes.masters.fonts import _infer_font_meta


@pytest.mark.parametrize(
    "filename,expected_weight,expected_style",
    [
        # Plain Family-Weight.ext
        ("STCForward-Regular.ttf", 400, "normal"),
        ("STCForward-Bold.ttf", 700, "normal"),
        ("STCForward-Light.ttf", 300, "normal"),
        ("Fund-Medium.otf", 500, "normal"),
        ("Inter-SemiBold.woff2", 600, "normal"),
        ("Inter-Black.ttf", 900, "normal"),
        ("Roboto-Thin.ttf", 100, "normal"),
        ("Roboto-ExtraLight.ttf", 200, "normal"),
        ("Lato-ExtraBold.otf", 800, "normal"),
        # Italic detection
        ("Fund-LightItalic.ttf", 300, "italic"),
        ("Inter-Italic.ttf", 400, "italic"),
        ("Lato-BoldOblique.otf", 700, "italic"),
        # No weight token → default 400 normal
        ("MyFamily.otf", 400, "normal"),
        # Underscore separator
        ("Source_Sans_Bold.ttf", 700, "normal"),
    ],
)
def test_infer_font_meta_weights_and_style(filename, expected_weight, expected_style):
    meta = _infer_font_meta(filename)
    assert meta["weight"] == expected_weight, (
        f"{filename}: weight {meta['weight']} != {expected_weight}"
    )
    assert meta["style"] == expected_style, f"{filename}: style {meta['style']} != {expected_style}"


def test_family_extracted_from_typical_filename():
    """Family is derived by stripping weight + style + extension."""
    meta = _infer_font_meta("STCForward-Bold.ttf")
    # Title-cased from the cleaned slug.
    assert "Stcforward" in meta["family"]


def test_no_weight_token_keeps_full_stem_as_family():
    meta = _infer_font_meta("MyCorporateFont.otf")
    assert meta["family"]  # non-empty
    # Either the original stem or its title-case — whichever, it must
    # carry the family identity.
    assert "Corporate" in meta["family"] or "corporate" in meta["family"].lower()
