"""Backend test fixtures.

Two kinds of pytest fixtures:

* **Synthetic** — built in-process via ``tests.fixtures.synthetic``.
  Always available, deterministic, fast. Use for any test that
  doesn't need real-world weirdness.

* **Private** — real corporate templates dropped in
  ``tests/fixtures/private/<name>.pptx`` by the developer. Marked with
  the ``private`` marker (declared in pytest.ini); skipped with a
  clear message when missing so CI stays green and a fresh checkout
  doesn't fail before the developer can populate the directory.

The ``snapshot`` fixture comes from ``syrupy`` and is used by
``assert x == snapshot`` to record/compare golden outputs.
``pytest --snapshot-update`` regenerates the .ambr files when an
intended schema change makes them stale.
"""

from __future__ import annotations

import os
from pathlib import Path


def _bootstrap_ci_env() -> None:
    """Point pydantic-settings at ``ci.env`` when running on GitHub Actions.

    ``app.config`` resolves ``EDWIN_ENV_FILE`` / ``backend/.env`` at
    ``_EnvSettings`` instantiation time. Test modules that import
    ``app.*`` at collection time would otherwise see a missing env on
    CI — this runs before any other imports in this conftest.
    """
    if os.environ.get("CI") != "true":
        return
    env_path = Path(__file__).resolve().parent / "ci.env"
    if env_path.is_file():
        os.environ.setdefault("EDWIN_ENV_FILE", str(env_path))


_bootstrap_ci_env()

import pytest  # noqa: E402

from tests.fixtures.synthetic import (  # noqa: E402
    minimal_master_bytes,
    minimal_master_with_slides_bytes,
)

_PRIVATE_DIR = Path(__file__).parent / "fixtures" / "private"


@pytest.fixture
def minimal_pptx() -> bytes:
    """Smallest valid .pptx — default Office theme, 1280×720 canvas,
    zero slides. Use for tests that exercise master/layout walks
    without any slide content interfering.
    """
    return minimal_master_bytes()


@pytest.fixture
def minimal_pptx_with_slides() -> bytes:
    """Like ``minimal_pptx`` but with one slide on each of the first
    three layouts. Use this when the test needs
    ``find_layout_representative_slides`` to return non-empty —
    typically renderer integration tests.
    """
    return minimal_master_with_slides_bytes()


@pytest.fixture
def private_pptx_path(request) -> Path:
    """Returns the path to a private fixture by name; skips otherwise.

    Usage::

        def test_real_stc(private_pptx_path):
            path = private_pptx_path("stc-target-setting")
            data = path.read_bytes()
            ...

    The fixture is *parametrised by call*, not by ``request.param``,
    so tests can pull multiple privates in one function. We return a
    callable so missing files trigger ``pytest.skip`` from inside the
    test function (after any setup the test wants to do first).
    """

    def _resolve(name: str) -> Path:
        candidate = _PRIVATE_DIR / f"{name}.pptx"
        if not candidate.exists():
            pytest.skip(
                f"Private fixture not found: {candidate}. "
                f"Drop the .pptx in {_PRIVATE_DIR}/ to run this test."
            )
        return candidate

    return _resolve
