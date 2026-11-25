"""Writes the OpenAPI schema of the API to `openapi.json` at the root of the repository.

    uv run python scripts/export_openapi.py          # write it
    uv run python scripts/export_openapi.py --check  # fail when the committed file is not what the API produces

The frontend types and the SDK are generated from this file. The routes of the worker (`/api/internal`) are left out:
they are not for clients.
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.main import app

PREFIX = "#/components/schemas/"
OUTPUT = Path(__file__).resolve().parents[2] / "openapi.json"


def _used(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(PREFIX):
            found.add(ref.removeprefix(PREFIX))
        for value in node.values():
            _used(value, found)
    elif isinstance(node, list):
        for value in node:
            _used(value, found)


def schema() -> dict[str, Any]:
    document = app.openapi()
    document["paths"] = {path: item for path, item in document["paths"].items() if not path.startswith("/api/internal")}
    # The schemas that only the worker's routes used go with them: keep what the remaining routes reach.
    schemas = document["components"]["schemas"]
    wanted: set[str] = set()
    _used(document["paths"], wanted)
    pending = list(wanted)
    while pending:
        more: set[str] = set()
        _used(schemas[pending.pop()], more)
        pending.extend(more - wanted)
        wanted |= more
    document["components"]["schemas"] = {name: value for name, value in schemas.items() if name in wanted}
    return document


def render() -> str:
    return json.dumps(schema(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text() != render():
            sys.exit("openapi.json is not up to date: run `uv run python scripts/export_openapi.py` in backend/")
    else:
        OUTPUT.write_text(render())
        print(OUTPUT.name)
