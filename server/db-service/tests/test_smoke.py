"""Smoke tests for db-service — proves the harness wires up.

Imports the FastAPI app object so any module-level breakage (broken
import, syntax error in a router, missing config field) shows up as
a test failure rather than a runtime crash.
"""

from __future__ import annotations


def test_pytest_runs() -> None:
    assert True


def test_app_imports() -> None:
    """Importing ``app.main`` validates the entire module graph: every
    router, every db query module, every config field. Catches
    regressions a long time before they'd surface in a uvicorn boot.
    """
    from app.main import app

    # Quick sanity that the FastAPI app actually has routes registered.
    assert len(app.routes) > 5
