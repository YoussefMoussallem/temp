"""Smoke tests — confirm the test harness itself works.

These are intentionally trivial. If they fail, the harness is broken;
no point running anything else. Keep this file small.
"""

from __future__ import annotations

import io

from pptx import Presentation


def test_pytest_runs() -> None:
    """A test that does nothing useful, just exists to confirm pytest
    discovered the suite and ran something."""
    assert True


def test_minimal_pptx_is_parseable(minimal_pptx: bytes) -> None:
    """The synthetic minimal fixture must round-trip through python-pptx
    cleanly. If this fails the synthetic-fixture builder is broken and
    every downstream test is meaningless."""
    prs = Presentation(io.BytesIO(minimal_pptx))
    assert prs.slide_width == 1280 * 9525
    assert prs.slide_height == 720 * 9525
    assert len(prs.slide_masters) >= 1
