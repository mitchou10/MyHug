import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"


@pytest.fixture(scope="module")
def export():
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_schema_is_what_the_api_produces(export):
    """The frontend types and the SDK come from `openapi.json`: change a route, regenerate it."""
    assert export.OUTPUT.exists()
    assert export.OUTPUT.read_text() == export.render(), (
        "openapi.json is stale: run `uv run python scripts/export_openapi.py` in backend/"
    )


def test_the_schema_has_nothing_of_the_worker(export):
    document = export.schema()
    assert not [path for path in document["paths"] if path.startswith("/api/internal")]
    assert not {"ClaimOut", "ResultIn", "FailureIn"} & set(document["components"]["schemas"])


def test_a_secret_is_never_in_what_the_api_answers(export):
    """`auth_value` is written, never read back: it may be in a request body, in no answer."""
    schemas = export.schema()["components"]["schemas"]
    assert "auth_value" in schemas["EndpointIn"]["properties"]
    assert "auth_value" not in schemas["EndpointOut"]["properties"]
