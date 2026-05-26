import json
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def load_example_json(*parts: str) -> dict:
    """Load a committed sample response, e.g. load_example_json('item', 'manifest')."""
    path = EXAMPLES.joinpath(*parts) / "response.json"
    return json.loads(path.read_text())


def load_example_bytes(*parts: str, name: str) -> bytes:
    return (EXAMPLES.joinpath(*parts) / name).read_bytes()


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES
