"""Shared pytest fixtures for base/spec tests."""

import pytest
import yaml
from pathlib import Path


# src/tests/base/spec/ -> src/ -> src/base/spec/
_SRC_ROOT = Path(__file__).parent.parent.parent.parent


@pytest.fixture
def spec_dir() -> Path:
    """Path to the spec source directory."""
    return _SRC_ROOT / "base" / "spec"


@pytest.fixture
def registry(spec_dir: Path) -> dict:
    """Loaded registry.yaml as a dict."""
    with open(spec_dir / "registry.yaml") as f:
        return yaml.safe_load(f)
