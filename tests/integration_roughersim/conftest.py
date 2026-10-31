"""Pytest hooks for the RougherSim golden-hash tests: the ``--update-goldens`` option.

The option is registered here, so run it as
``pytest tests/integration_roughersim --update-goldens``.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add ``--update-goldens`` (rewrite pin.json goldens from the current checkout)."""
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="rewrite the goldens in tests/integration_roughersim/pin.json",
    )
